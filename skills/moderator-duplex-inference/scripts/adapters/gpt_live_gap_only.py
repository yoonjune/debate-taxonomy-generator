"""Run GPT-Live with input gating only inside registered MOD gaps.

This is the self-contained canonical adapter bundled with moderator-duplex-inference.
The API key is read only from OPENAI_API_KEY. Existing outputs are not overwritten.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import hashlib
import json
import math
import os
import platform
import signal
import sys
import time
from pathlib import Path

import numpy as np
import openai
import soundfile as sf
import websockets


ROOT = Path.cwd().resolve()
RATE = 24000
FRAME = 1920


def set_workspace_root(value: str | Path) -> None:
    """Bind relative plan paths to the campaign workspace, not the skill install."""
    global ROOT
    ROOT = Path(value).resolve()


def resolve(value: str) -> Path:
    candidate = Path(value)
    return candidate if candidate.is_absolute() else ROOT / candidate


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def output_dir(run: dict) -> Path:
    return resolve(run["output_dir"])


def load_gaps(run: dict, source: np.ndarray) -> list[dict]:
    gap_path = resolve(run["conditional_gap_file"])
    assert sha(gap_path) == run["conditional_gap_sha256"]
    payload = json.loads(gap_path.read_text())
    assert payload["sample_rate"] == RATE
    previous_end = 0
    for gap in payload["gaps"]:
        start, end = gap["start_sample"], gap["end_sample"]
        assert 0 <= start < end <= len(source) and start >= previous_end
        assert np.count_nonzero(source[start:end]) == 0
        previous_end = end
    return payload["gaps"]


def conditional_gap(gaps: list[dict], source_cursor: int) -> dict | None:
    return next(
        (gap for gap in gaps if gap["start_sample"] <= source_cursor < gap["end_sample"]),
        None,
    )


def frame_end_at_gap_boundary(
    gaps: list[dict], source_cursor: int, proposed_end: int
) -> int:
    """Never let one input append straddle a registered gap boundary."""
    boundaries = [
        boundary
        for gap in gaps
        for boundary in (gap["start_sample"], gap["end_sample"])
        if source_cursor < boundary < proposed_end
    ]
    return min(boundaries, default=proposed_end)


def gap_audio_arrived_in_time(
    gap_state: dict, gate_events: list[dict]
) -> bool:
    """Return whether active model PCM qualified before this gap's cap deadline."""
    if gap_state["gate_closed_on_entry"]:
        return True
    return any(
        event.get("kind") == "first_audio"
        and gap_state["start_session_sec"] <= event["session_sec"]
        <= gap_state["deadline_session_sec"]
        for event in gate_events[gap_state["first_gate_event_index"] :]
    )


def gap_silence_cap_due(
    gap_state: dict, gate_events: list[dict], now_session_sec: float
) -> bool:
    """Cap only a registered gap that received no active model PCM in time."""
    return (
        now_session_sec >= gap_state["deadline_session_sec"]
        and not gap_audio_arrived_in_time(gap_state, gate_events)
    )


def retained_pcm_hash(
    pcm: np.ndarray, trim: int, skips: list[dict], source_cursor: int
) -> tuple[str, int]:
    digest = hashlib.sha256()
    cursor = 0
    samples = 0
    for skip in skips:
        start = skip["source_start_sample"] - trim
        end = skip["source_end_sample"] - trim
        assert cursor <= start < end <= source_cursor - trim
        digest.update(pcm[cursor:start].astype("<i2").tobytes())
        samples += start - cursor
        cursor = end
    final = source_cursor - trim
    assert cursor <= final <= len(pcm)
    digest.update(pcm[cursor:final].astype("<i2").tobytes())
    return digest.hexdigest(), samples + final - cursor


def validate(
    plan: dict, expected_resume_pad_sec: float | None = None
) -> list[dict]:
    assert plan["model"] == "gpt-live-1"
    assert plan["endpoint"] == "wss://api.openai.com/v1/live/sessions"
    assert plan["audio_format"] == {"type": "audio/pcm", "rate": RATE}
    assert plan["selected_debates"] == ["L107"]
    assert plan["concurrency"] == 1
    controller = plan["input_controller"]
    resume_pad_sec = controller.get("resume_pad_sec")
    assert isinstance(resume_pad_sec, (int, float))
    assert math.isfinite(resume_pad_sec) and 0 <= resume_pad_sec <= 10
    if expected_resume_pad_sec is not None:
        assert math.isclose(
            resume_pad_sec, expected_resume_pad_sec, rel_tol=0, abs_tol=1e-9
        )
    silence_cap_sec = controller.get("silence_cap_sec")
    assert isinstance(silence_cap_sec, (int, float))
    assert math.isclose(silence_cap_sec, 2.0, rel_tol=0, abs_tol=1e-9)
    gated_input_transport = controller.get(
        "gated_input_transport", {"type": "no_appends"}
    )
    assert gated_input_transport in (
        {"type": "no_appends"},
        {"type": "zero_pcm_fill", "frame_ms": 80, "pcm_value": 0},
    )
    assert {
        key: value
        for key, value in controller.items()
        if key not in {"resume_pad_sec", "gated_input_transport", "silence_cap_sec"}
    } == {
        "type": "registered_gap_only_model_audio_gate",
        "gate_timeout_sec": 120,
        "completion_basis": "speech_active_playback_queue_drain_plus_pad",
        "output_activity_detector": {
            "type": "pcm_peak_absolute",
            "active_if_peak_abs_gte": 256,
            "calibration": "L107_invalid_attempt_1",
        },
        "outside_registered_gap": "continue_input_during_model_audio",
        "inside_registered_gap": "pause_then_skip_remaining_exact_zero_gap; if the model produces no audio within silence_cap_sec of the gap start, skip the remaining gap and resume the debater input immediately",
        "pause_sends_all_audio": True,
        "phase_cues": False,
    }
    assert plan["conditional_skip"] == {
        "type": "remaining_mod_gap_after_completed_model_audio",
        "gap_file_field": "conditional_gap_file",
        "completion_is_controller_proxy": True,
    }
    cue_path = resolve(plan["start_cue"]["audio"])
    cue_info = sf.info(cue_path)
    assert cue_info.samplerate == RATE and cue_info.channels == 1
    assert sha(cue_path) == plan["start_cue"]["sha256"]
    rows = []
    seen: set[str] = set()
    for run in plan["runs"]:
        assert run["run_id"] not in seen
        seen.add(run["run_id"])
        assert run["condition"].startswith("B0_GAP_ONLY_GATE")
        source_dir = resolve(run["input_dir"])
        source_path = source_dir / "user.wav"
        prompt_path = source_dir / "system_prompt.txt"
        source, rate = sf.read(source_path, dtype="int16")
        assert rate == RATE and source.ndim == 1
        assert sha(source_path) == run["source_audio_sha256"]
        assert sha(prompt_path) == run["prompt_sha256"]
        assert prompt_path.read_text().strip()
        trim = run["leading_trim_sample"]
        assert trim == round(run["trim_leading_silence_sec"] * RATE)
        assert np.count_nonzero(source[:trim]) == 0
        load_gaps(run, source)
        rows.append(
            {
                "run_id": run["run_id"],
                "debate_id": run["debate_id"],
                "participant_sec": (len(source) - trim) / RATE,
                "existing": output_dir(run).exists(),
            }
        )
    return rows


async def run_session(plan: dict, run: dict, plan_hash: str) -> bool:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    destination = output_dir(run)
    source_dir = resolve(run["input_dir"])
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.mkdir()

    source, rate = sf.read(source_dir / "user.wav", dtype="int16")
    assert rate == RATE and source.ndim == 1
    trim = run["leading_trim_sample"]
    pcm = source[trim:].copy()
    gaps = load_gaps(run, source)
    cue, cue_rate = sf.read(resolve(plan["start_cue"]["audio"]), dtype="int16")
    assert cue_rate == RATE and cue.ndim == 1
    prompt = (source_dir / "system_prompt.txt").read_text()
    sf.write(destination / "participant.wav", pcm, RATE, subtype="PCM_16")
    (destination / "system_prompt.txt").write_text(prompt)

    meta = {
        **run,
        "status": "CONNECTING",
        "model": plan["model"],
        "endpoint": plan["endpoint"],
        "voice": plan["voice"],
        "audio_format": plan["audio_format"],
        "backend_delegation": "none_client_default",
        "store": False,
        "plan_sha256": plan_hash,
        "source_audio_sha256": sha(source_dir / "user.wav"),
        "prompt_sha256": sha(source_dir / "system_prompt.txt"),
        "cue_audio_sha256": sha(resolve(plan["start_cue"]["audio"])),
        "planned_participant_pcm_sha256": hashlib.sha256(
            pcm.astype("<i2").tobytes()
        ).hexdigest(),
        "planned_participant_samples": len(pcm),
        "input_duration_sec": len(pcm) / RATE,
        "frame_ms": plan["frame_ms"],
        "trimmed_original_leading_silence_sec": trim / RATE,
        "input_controller": plan["input_controller"],
        "conditional_skip": plan["conditional_skip"],
        "output_boundary_provenance": (
            "client proxy: PCM speech-active arrival-paced playback queue drain "
            f"plus {plan['input_controller']['resume_pad_sec'] * 1000:g} ms; "
            "GPT-Live provides no output-audio-done event and was "
            "observed to stream exact-zero output PCM while not speaking; the "
            "participant gate is applied only while the source cursor is inside "
            "a registered exact-zero MOD gap"
        ),
        "openai_package": openai.__version__,
        "websockets_package": websockets.__version__,
        "python": platform.python_version(),
        "key_persisted": False,
        "startup_success": False,
        "start_cue_status": "PENDING",
        "chunks_sent": 0,
        "max_send_lag_sec": 0.0,
        "participant_spans": [],
        "automatic_output_pauses": [],
        "outside_gap_output_overlap_spans": [],
        "runtime_silence_skips": [],
        "silence_cap_events": [],
        "gate_events": [],
        "gate_release_audits": [],
        "gate_zero_fill_frames": 0,
        "gate_zero_fill_samples": 0,
        "output_generations": [],
        "input_transcript_fragments": [],
        "output_transcript_fragments": [],
        "server_event_counts": {},
        "session_usage": None,
    }
    write_json(destination / "generation.json", meta)

    raw_output: list[np.ndarray] = []
    played_output: list[tuple[int, np.ndarray]] = []
    sent_input: list[tuple[int, np.ndarray, str]] = []
    sent_participant_hash = hashlib.sha256()
    sent_participant_samples = 0
    source_cursor = trim
    cumulative_pause = 0.0
    cumulative_skipped_samples = 0
    handled_generation_ids: set[int] = set()
    current_generation: dict | None = None
    active_gap_state: dict | None = None
    playback_end = 0.0
    output_stream_end = 0.0
    raw_output_samples = 0
    active_output_samples = 0
    start_time: float | None = None
    receiver: asyncio.Task | None = None
    ws = None
    session_started = asyncio.Event()
    session_closed = asyncio.Event()
    first_output = asyncio.Event()
    gate_changed = asyncio.Event()
    fatal_error: str | None = None
    participant_inflight: dict | None = None
    participant_last_end: float | None = None

    def elapsed() -> float:
        return time.monotonic() - start_time if start_time is not None else 0.0

    def gate_closed() -> bool:
        return elapsed() < playback_end + plan["input_controller"]["resume_pad_sec"]

    def check_receiver() -> None:
        nonlocal fatal_error
        if fatal_error:
            raise RuntimeError(fatal_error)
        if receiver is not None and receiver.done() and not session_closed.is_set():
            receiver.result()
            raise RuntimeError("Live receiver stopped before session.closed")

    async def receive_events(events_file, transcript_file, chunks_file) -> None:
        nonlocal playback_end, output_stream_end, raw_output_samples
        nonlocal active_output_samples, current_generation, fatal_error
        assert ws is not None
        async for raw in ws:
            arrival = elapsed()
            event = json.loads(raw)
            event_type = event.get("type", "UNKNOWN")
            meta["server_event_counts"][event_type] = (
                meta["server_event_counts"].get(event_type, 0) + 1
            )
            events_file.write(
                json.dumps({"arrival_sec": arrival, "event": event}, ensure_ascii=False)
                + "\n"
            )
            events_file.flush()
            if event_type == "session.started":
                meta["session_id"] = event.get("session", {}).get("id")
                meta["resolved_session"] = event.get("session")
                session_started.set()
            elif event_type == "session.output_audio.delta":
                data = np.frombuffer(base64.b64decode(event["delta"]), dtype="<i2").copy()
                peak_abs = int(np.max(np.abs(data.astype(np.int32)))) if len(data) else 0
                detector = plan["input_controller"]["output_activity_detector"]
                speech_active = peak_abs >= detector["active_if_peak_abs_gte"]
                stream_onset_sample = max(
                    round(arrival * RATE), round(output_stream_end * RATE)
                )
                output_stream_end = (stream_onset_sample + len(data)) / RATE
                raw_output.append(data)
                played_output.append((stream_onset_sample, data))
                chunks_file.write(
                    json.dumps(
                        {
                            "arrival_sec": arrival,
                            "playback_start_sec": stream_onset_sample / RATE,
                            "samples": len(data),
                            "raw_start_sample": raw_output_samples,
                            "peak_abs": peak_abs,
                            "speech_active": speech_active,
                        }
                    )
                    + "\n"
                )
                chunks_file.flush()
                raw_output_samples += len(data)
                if not speech_active:
                    continue
                previous_end = playback_end
                onset_sample = stream_onset_sample
                playback_end = (onset_sample + len(data)) / RATE
                if (
                    current_generation is None
                    or arrival >= previous_end + plan["input_controller"]["resume_pad_sec"]
                ):
                    current_generation = {
                        "generation_id": len(meta["output_generations"]),
                        "first_chunk_arrival_sec": arrival,
                        "playback_start_sec": onset_sample / RATE,
                        "audio_chunks": 0,
                        "audio_samples": 0,
                    }
                    meta["output_generations"].append(current_generation)
                    inflight_end = (
                        participant_inflight["scheduled_session_sec"]
                        + participant_inflight["samples"] / RATE
                        if participant_inflight
                        else arrival
                    )
                    race = max(
                        0.0,
                        max(participant_last_end or arrival, inflight_end) - arrival,
                    )
                    meta["gate_events"].append(
                        {
                            "event_id": len(meta["gate_events"]),
                            "kind": "first_audio",
                            "session_sec": arrival,
                            "generation_id": current_generation["generation_id"],
                            "model_playback_onset_sec": onset_sample / RATE,
                            "detection_race_sec": race,
                            "inflight_participant_send": (
                                dict(participant_inflight) if participant_inflight else None
                            ),
                        }
                    )
                current_generation["audio_chunks"] += 1
                current_generation["audio_samples"] += len(data)
                active_output_samples += len(data)
                current_generation["last_chunk_arrival_sec"] = arrival
                current_generation["playback_end_session_sec"] = playback_end
                first_output.set()
                gate_changed.set()
            elif event_type in {
                "session.input_transcript.delta",
                "session.output_transcript.delta",
            }:
                fragment = {
                    "arrival_sec": arrival,
                    "delta": event.get("delta", ""),
                    "start_ms": event.get("start_ms"),
                    "end_ms": event.get("end_ms"),
                }
                target = (
                    meta["input_transcript_fragments"]
                    if event_type == "session.input_transcript.delta"
                    else meta["output_transcript_fragments"]
                )
                target.append(fragment)
                transcript_file.write(
                    json.dumps(
                        {"kind": event_type, **fragment}, ensure_ascii=False
                    )
                    + "\n"
                )
                transcript_file.flush()
            elif event_type == "error":
                fatal_error = json.dumps(event.get("error", {}), ensure_ascii=False)
                gate_changed.set()
                session_started.set()
            elif event_type == "session.closed":
                meta["session_usage"] = event.get("usage")
                session_closed.set()
                gate_changed.set()
                return

    async def wait_event_or_receiver(event: asyncio.Event, timeout: float, label: str) -> None:
        waiter = asyncio.create_task(event.wait())
        assert receiver is not None
        done, _ = await asyncio.wait(
            [waiter, receiver], timeout=timeout, return_when=asyncio.FIRST_COMPLETED
        )
        if receiver in done:
            check_receiver()
        if waiter not in done:
            waiter.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await waiter
            raise TimeoutError(f"Timed out waiting for {label}")
        check_receiver()

    async def drain_output_gate(context: str, sends_file) -> tuple[float, int | None]:
        deadline = time.monotonic() + plan["input_controller"]["gate_timeout_sec"]
        observed_generation = (
            current_generation["generation_id"] if current_generation else None
        )
        fill_frame_start = meta["gate_zero_fill_frames"]
        fill_sample_start = meta["gate_zero_fill_samples"]
        next_fill = elapsed()
        while True:
            check_receiver()
            gate_changed.clear()
            release_at = playback_end + plan["input_controller"]["resume_pad_sec"]
            now = elapsed()
            if now >= release_at:
                observed_quiet_sec = now - playback_end
                required_quiet_sec = plan["input_controller"]["resume_pad_sec"]
                assert observed_quiet_sec + 1e-6 >= required_quiet_sec
                audit = {
                    "audit_id": len(meta["gate_release_audits"]),
                    "context": context,
                    "generation_id": observed_generation,
                    "model_playback_end_proxy_sec": playback_end,
                    "required_quiet_sec": required_quiet_sec,
                    "release_session_sec": now,
                    "observed_quiet_sec": observed_quiet_sec,
                    "zero_fill_frames": meta["gate_zero_fill_frames"]
                    - fill_frame_start,
                    "zero_fill_samples": meta["gate_zero_fill_samples"]
                    - fill_sample_start,
                    "status": "PASS",
                }
                meta["gate_release_audits"].append(audit)
                if current_generation is not None:
                    current_generation.setdefault("controller_drains", []).append(
                        audit["audit_id"]
                    )
                    current_generation.setdefault("controller_drain_sec", now)
                    current_generation["last_controller_drain_sec"] = now
                    current_generation["completion_basis"] = (
                        "speech_active_playback_queue_drain_plus_pad"
                    )
                return now, observed_generation
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"Output gate timeout: {context}")
            gated_transport = plan["input_controller"].get(
                "gated_input_transport", {"type": "no_appends"}
            )
            if gated_transport["type"] == "zero_pcm_fill":
                scheduled = max(now, next_fill)
                if scheduled < release_at:
                    samples = min(
                        FRAME,
                        max(1, round((release_at - scheduled) * RATE)),
                    )
                    zero = np.zeros(samples, dtype=np.int16)
                    actual = await send_audio(zero, "gate_zero_fill", scheduled)
                    meta["gate_zero_fill_frames"] += 1
                    meta["gate_zero_fill_samples"] += samples
                    sends_file.write(
                        json.dumps(
                            {
                                "kind": "gate_zero_fill",
                                "context": context,
                                "scheduled_session_sec": scheduled,
                                "send_session_sec": actual,
                                "session_end_sec": scheduled + samples / RATE,
                                "samples": samples,
                                "pcm_nonzero_samples": 0,
                            }
                        )
                        + "\n"
                    )
                    sends_file.flush()
                    next_fill = scheduled + samples / RATE
                    continue
            waiter = asyncio.create_task(gate_changed.wait())
            assert receiver is not None
            try:
                done, _ = await asyncio.wait(
                    [waiter, receiver],
                    timeout=min(remaining, max(0.0, release_at - now)),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if receiver in done:
                    check_receiver()
            finally:
                waiter.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await waiter

    async def send_audio(data: np.ndarray, kind: str, scheduled: float) -> float:
        assert ws is not None
        await asyncio.sleep(max(0.0, start_time + scheduled - time.monotonic()))
        actual = elapsed()
        await ws.send(
            json.dumps(
                {
                    "type": "session.input_audio.append",
                    "audio": base64.b64encode(data.astype("<i2").tobytes()).decode(
                        "ascii"
                    ),
                }
            )
        )
        sent_input.append((round(scheduled * RATE), data.copy(), kind))
        return actual

    try:
        async with websockets.connect(
            plan["endpoint"],
            additional_headers={"Authorization": f"Bearer {key}"},
            max_size=None,
        ) as connection:
            ws = connection
            start_time = time.monotonic()
            meta["status"] = "STARTING"
            with (
                (destination / "events.jsonl").open("w") as events_file,
                (destination / "transcripts.jsonl").open("w") as transcript_file,
                (destination / "chunks.jsonl").open("w") as chunks_file,
                (destination / "input_sends.jsonl").open("w") as sends_file,
            ):
                receiver = asyncio.create_task(
                    receive_events(events_file, transcript_file, chunks_file)
                )
                await ws.send(
                    json.dumps(
                        {
                            "type": "session.start",
                            "event_id": "experiment_start",
                            "session": {
                                "model": plan["model"],
                                "instructions": prompt,
                                "audio": {
                                    "format": plan["audio_format"],
                                    "output": {"voice": plan["voice"]},
                                },
                                "store": False,
                            },
                        }
                    )
                )
                await wait_event_or_receiver(session_started, 30, "session.started")
                meta["status"] = "RUNNING"
                write_json(destination / "generation.json", meta)

                cue_origin = elapsed()
                for offset in range(0, len(cue), FRAME):
                    frame = cue[offset : offset + FRAME]
                    scheduled = cue_origin + offset / RATE
                    actual = await send_audio(frame, "start_cue", scheduled)
                    sends_file.write(
                        json.dumps(
                            {
                                "kind": "start_cue",
                                "offset_sample": offset,
                                "scheduled_session_sec": scheduled,
                                "send_session_sec": actual,
                                "samples": len(frame),
                            }
                        )
                        + "\n"
                    )
                meta["start_cue_end_session_sec"] = cue_origin + len(cue) / RATE

                startup_deadline = time.monotonic() + plan["start_cue"]["timeout_sec"]
                silence = np.zeros(FRAME, dtype=np.int16)
                startup_silence_frames = 0
                next_silence = meta["start_cue_end_session_sec"]
                while not first_output.is_set():
                    check_receiver()
                    if time.monotonic() >= startup_deadline:
                        raise TimeoutError("No model audio after start cue")
                    actual = await send_audio(silence, "startup_silence", next_silence)
                    sends_file.write(
                        json.dumps(
                            {
                                "kind": "startup_silence",
                                "scheduled_session_sec": next_silence,
                                "send_session_sec": actual,
                                "samples": len(silence),
                            }
                        )
                        + "\n"
                    )
                    startup_silence_frames += 1
                    next_silence += len(silence) / RATE
                startup_drained, _ = await drain_output_gate(
                    "startup response", sends_file
                )
                startup_release_audit = meta["gate_release_audits"][-1]
                assert startup_release_audit["context"] == "startup response"
                meta.update(
                    startup_success=True,
                    start_cue_status="AUDIO_RECEIVED_AND_QUEUE_DRAINED",
                    startup_silence_frames=startup_silence_frames,
                    debate_start_session_sec=startup_drained,
                    startup_release_audit_id=startup_release_audit["audit_id"],
                    reference_time_shift_sec=startup_drained - trim / RATE,
                )
                write_json(destination / "generation.json", meta)

                debate_start = startup_drained
                offset = 0
                frame_index = 0
                while offset < len(pcm):
                    scheduled = (
                        debate_start
                        + offset / RATE
                        + cumulative_pause
                        - cumulative_skipped_samples / RATE
                    )
                    await asyncio.sleep(max(0.0, start_time + scheduled - time.monotonic()))
                    gap_at_cursor = conditional_gap(gaps, trim + offset)
                    if gap_at_cursor is None:
                        active_gap_state = None
                    elif (
                        active_gap_state is None
                        or active_gap_state["gap_id"] != gap_at_cursor["gap_id"]
                    ):
                        active_gap_state = {
                            "gap_id": gap_at_cursor["gap_id"],
                            "start_session_sec": scheduled,
                            "deadline_session_sec": scheduled
                            + plan["input_controller"]["silence_cap_sec"],
                            "first_gate_event_index": len(meta["gate_events"]),
                            "gate_closed_on_entry": gate_closed(),
                        }
                    if (
                        gate_closed()
                        and gap_at_cursor is not None
                        and gap_audio_arrived_in_time(
                            active_gap_state, meta["gate_events"]
                        )
                    ):
                        trigger = (
                            current_generation["generation_id"]
                            if current_generation
                            else None
                        )
                        first_event = next(
                            (
                                event
                                for event in reversed(meta["gate_events"])
                                if event["kind"] == "first_audio"
                            ),
                            None,
                        )
                        pause = {
                            "pause_id": len(meta["automatic_output_pauses"]),
                            "pause_start_session_sec": scheduled,
                            "source_sec": (trim + offset) / RATE,
                            "source_offset_sample": offset,
                            "original_source_sample": trim + offset,
                            "triggering_generation_id": trigger,
                            "triggering_model_onset_sec": (
                                first_event["model_playback_onset_sec"]
                                if first_event
                                else None
                            ),
                            "detection_race_sec": (
                                first_event["detection_race_sec"] if first_event else 0.0
                            ),
                        }
                        meta["automatic_output_pauses"].append(pause)
                        resumed, drained_generation = await drain_output_gate(
                            "participant", sends_file
                        )
                        release_audit = meta["gate_release_audits"][-1]
                        assert release_audit["context"] == "participant"
                        pause_duration = resumed - scheduled
                        cumulative_pause += pause_duration
                        pause.update(
                            resume_session_sec=resumed,
                            pause_duration_sec=pause_duration,
                            completion_basis=(
                                "speech_active_playback_queue_drain_plus_pad"
                            ),
                            release_audit_id=release_audit["audit_id"],
                            required_post_output_quiet_sec=release_audit[
                                "required_quiet_sec"
                            ],
                            observed_post_output_quiet_sec=release_audit[
                                "observed_quiet_sec"
                            ],
                        )
                        scheduled = resumed
                        if (
                            drained_generation is not None
                            and drained_generation not in handled_generation_ids
                        ):
                            gap = gap_at_cursor
                            handled_generation_ids.add(drained_generation)
                            if gap is not None:
                                before = trim + offset
                                end = gap["end_sample"]
                                assert np.count_nonzero(source[before:end]) == 0
                                skip = {
                                    "skip_id": len(meta["runtime_silence_skips"]),
                                    "gap_id": gap["gap_id"],
                                    "source_start_sample": before,
                                    "source_end_sample": end,
                                    "source_start_sec": before / RATE,
                                    "source_end_sec": end / RATE,
                                    "skipped_samples": end - before,
                                    "skipped_sec": (end - before) / RATE,
                                    "session_sec": resumed,
                                    "pause_id": pause["pause_id"],
                                    "triggering_generation_id": drained_generation,
                                    "completion_basis": pause["completion_basis"],
                                }
                                meta["runtime_silence_skips"].append(skip)
                                cumulative_skipped_samples += end - before
                                offset = end - trim
                                source_cursor = end
                                pause["conditional_skip_id"] = skip["skip_id"]
                                active_gap_state = None
                        meta["gate_events"].append(
                            {
                                "event_id": len(meta["gate_events"]),
                                "kind": "participant_resume",
                                "session_sec": resumed,
                                "source_sec": (trim + offset) / RATE,
                            }
                        )
                    if (
                        gap_at_cursor is not None
                        and active_gap_state is not None
                        and gap_silence_cap_due(
                            active_gap_state, meta["gate_events"], elapsed()
                        )
                    ):
                        before = trim + offset
                        end = gap_at_cursor["end_sample"]
                        assert before < end
                        assert np.count_nonzero(source[before:end]) == 0
                        cap_event = {
                            "event_id": len(meta["silence_cap_events"]),
                            "gap_id": gap_at_cursor["gap_id"],
                            "gap_start_session_sec": active_gap_state[
                                "start_session_sec"
                            ],
                            "deadline_session_sec": active_gap_state[
                                "deadline_session_sec"
                            ],
                            "cap_sec": plan["input_controller"]["silence_cap_sec"],
                            "resume_session_sec": elapsed(),
                            "source_start_sample": before,
                            "source_end_sample": end,
                            "skipped_samples": end - before,
                            "status": "NO_ACTIVE_MODEL_AUDIO_WITHIN_CAP",
                        }
                        skip = {
                            "skip_id": len(meta["runtime_silence_skips"]),
                            "gap_id": gap_at_cursor["gap_id"],
                            "source_start_sample": before,
                            "source_end_sample": end,
                            "source_start_sec": before / RATE,
                            "source_end_sec": end / RATE,
                            "skipped_samples": end - before,
                            "skipped_sec": (end - before) / RATE,
                            "session_sec": cap_event["resume_session_sec"],
                            "pause_id": None,
                            "triggering_generation_id": None,
                            "completion_basis": (
                                "no_speech_active_model_audio_within_silence_cap"
                            ),
                            "silence_cap_event_id": cap_event["event_id"],
                        }
                        meta["silence_cap_events"].append(cap_event)
                        meta["runtime_silence_skips"].append(skip)
                        cumulative_skipped_samples += end - before
                        offset = end - trim
                        source_cursor = end
                        active_gap_state = None
                        continue
                    check_receiver()
                    source_frame_end = frame_end_at_gap_boundary(
                        gaps, trim + offset, min(trim + offset + FRAME, trim + len(pcm))
                    )
                    frame = pcm[offset : source_frame_end - trim]
                    output_active_at_send = gate_closed()
                    overlap_generation_id = (
                        current_generation["generation_id"]
                        if output_active_at_send and current_generation is not None
                        else None
                    )
                    send_start = elapsed()
                    participant_inflight = {
                        "source_offset_sample": offset,
                        "source_start_sec": (trim + offset) / RATE,
                        "source_end_sec": (trim + offset + len(frame)) / RATE,
                        "scheduled_session_sec": scheduled,
                        "send_start_session_sec": send_start,
                        "samples": len(frame),
                    }
                    try:
                        actual = await send_audio(frame, "participant", scheduled)
                    finally:
                        participant_inflight = None
                    lag = actual - scheduled
                    meta["max_send_lag_sec"] = max(meta["max_send_lag_sec"], lag)
                    if lag >= 1.0:
                        raise RuntimeError("Input pacing lag >= 1 second")
                    session_end = scheduled + len(frame) / RATE
                    participant_last_end = session_end
                    source_start = (trim + offset) / RATE
                    source_end = (trim + offset + len(frame)) / RATE
                    if output_active_at_send:
                        assert conditional_gap(gaps, trim + offset) is None
                        overlap_spans = meta["outside_gap_output_overlap_spans"]
                        if (
                            overlap_spans
                            and overlap_spans[-1]["generation_id"]
                            == overlap_generation_id
                            and abs(overlap_spans[-1]["session_end_sec"] - scheduled)
                            < 1e-7
                            and abs(overlap_spans[-1]["source_end_sec"] - source_start)
                            < 1e-7
                        ):
                            overlap_spans[-1].update(
                                session_end_sec=session_end,
                                source_end_sec=source_end,
                                frames=overlap_spans[-1]["frames"] + 1,
                            )
                        else:
                            overlap_spans.append(
                                {
                                    "overlap_id": len(overlap_spans),
                                    "generation_id": overlap_generation_id,
                                    "session_start_sec": scheduled,
                                    "session_end_sec": session_end,
                                    "source_start_sec": source_start,
                                    "source_end_sec": source_end,
                                    "frames": 1,
                                    "policy": "continued_input_outside_registered_gap",
                                }
                            )
                    spans = meta["participant_spans"]
                    if (
                        spans
                        and abs(spans[-1]["session_end_sec"] - scheduled) < 1e-7
                        and abs(spans[-1]["source_end_sec"] - source_start) < 1e-7
                    ):
                        spans[-1].update(
                            source_end_sec=source_end, session_end_sec=session_end
                        )
                    else:
                        spans.append(
                            {
                                "source_start_sec": source_start,
                                "source_end_sec": source_end,
                                "session_start_sec": scheduled,
                                "session_end_sec": session_end,
                            }
                        )
                    sent_participant_hash.update(frame.astype("<i2").tobytes())
                    sent_participant_samples += len(frame)
                    source_cursor = trim + offset + len(frame)
                    frame_index += 1
                    meta["chunks_sent"] = frame_index
                    meta["participant_source_cursor_sec"] = source_cursor / RATE
                    sends_file.write(
                        json.dumps(
                            {
                                "kind": "participant",
                                "source_offset_sample": offset,
                                "source_start_sec": source_start,
                                "source_end_sec": source_end,
                                "scheduled_session_sec": scheduled,
                                "send_session_sec": actual,
                                "session_start_sec": scheduled,
                                "session_end_sec": session_end,
                                "samples": len(frame),
                                "cumulative_pause_sec": cumulative_pause,
                                "cumulative_skipped_sec": cumulative_skipped_samples
                                / RATE,
                                "model_output_active_at_send": output_active_at_send,
                                "overlap_generation_id": overlap_generation_id,
                            }
                        )
                        + "\n"
                    )
                    if frame_index % 375 == 0:
                        sends_file.flush()
                        write_json(destination / "generation.json", meta)
                        print(
                            f"{run['run_id']}: participant {offset / RATE:.1f}/{len(pcm) / RATE:.1f}s",
                            flush=True,
                        )
                    offset += len(frame)

                participant_end = elapsed()
                meta["participant_end_session_sec"] = participant_end
                tail_deadline = time.monotonic() + plan["tail_sec"]
                tail_frames = 0
                next_tail = elapsed()
                while time.monotonic() < tail_deadline:
                    check_receiver()
                    if gate_closed():
                        await drain_output_gate("tail silence", sends_file)
                        next_tail = elapsed()
                        if time.monotonic() >= tail_deadline:
                            break
                    actual = await send_audio(silence, "tail_silence", next_tail)
                    sends_file.write(
                        json.dumps(
                            {
                                "kind": "tail_silence",
                                "scheduled_session_sec": next_tail,
                                "send_session_sec": actual,
                                "samples": len(silence),
                            }
                        )
                        + "\n"
                    )
                    tail_frames += 1
                    next_tail += len(silence) / RATE
                await drain_output_gate("final output drain", sends_file)
                meta["tail_silence_frames"] = tail_frames
                await ws.send(json.dumps({"type": "session.close", "event_id": "experiment_close"}))
                await wait_event_or_receiver(session_closed, 20, "session.closed")
                meta["status"] = "COMPLETE"
                if receiver is not None:
                    await receiver
    except BaseException as exc:
        meta.update(
            status="ERROR",
            error_type=type(exc).__name__,
            error=str(exc).replace(key, "[REDACTED]"),
        )
    finally:
        if receiver is not None and not receiver.done():
            receiver.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await receiver
        final_elapsed = elapsed()
        all_pieces = [(start, data) for start, data, _ in sent_input] + played_output
        length = max(
            round(final_elapsed * RATE),
            max((start + len(data) for start, data in all_pieces), default=0),
        )
        stereo = np.zeros((length, 2), dtype=np.int16)
        for onset, data, _ in sent_input:
            end = min(length, onset + len(data))
            stereo[onset:end, 0] = data[: end - onset]
        for onset, data in played_output:
            end = min(length, onset + len(data))
            stereo[onset:end, 1] = data[: end - onset]
        sf.write(destination / "input.wav", stereo[:, 0], RATE, subtype="PCM_16")
        sf.write(destination / "model_timeline.wav", stereo[:, 1], RATE, subtype="PCM_16")
        sf.write(destination / "stereo.wav", stereo, RATE, subtype="PCM_16")
        sf.write(
            destination / "raw_model_chunks.wav",
            np.concatenate(raw_output) if raw_output else np.zeros(0, dtype=np.int16),
            RATE,
            subtype="PCM_16",
        )
        expected_hash, expected_samples = retained_pcm_hash(
            pcm, trim, meta["runtime_silence_skips"], source_cursor
        )
        actual_hash = sent_participant_hash.hexdigest()
        transmission_ok = (
            expected_hash == actual_hash
            and expected_samples == sent_participant_samples
            and source_cursor == trim + len(pcm)
        )
        if meta["status"] == "COMPLETE" and not transmission_ok:
            meta.update(
                status="ERROR",
                error_type="TransmissionIntegrityError",
                error="Sent participant PCM did not match the frozen source minus exact registered skips",
            )
        meta.update(
            expected_transmitted_participant_pcm_sha256=expected_hash,
            actual_transmitted_participant_pcm_sha256=actual_hash,
            expected_transmitted_participant_samples=expected_samples,
            participant_samples_sent=sent_participant_samples,
            transmission_integrity_pass=transmission_ok,
            participant_source_cursor_sec=source_cursor / RATE,
            cumulative_pause_sec=cumulative_pause,
            cumulative_skipped_sec=cumulative_skipped_samples / RATE,
            outside_gap_output_overlap_sec=sum(
                row["session_end_sec"] - row["session_start_sec"]
                for row in meta["outside_gap_output_overlap_spans"]
            ),
            elapsed_sec=final_elapsed,
            output_audio_sec=raw_output_samples / RATE,
            output_activity_audio_sec=active_output_samples / RATE,
            played_audio_sec=sum(len(data) for _, data in played_output) / RATE,
            output_sha256=sha(destination / "model_timeline.wav"),
        )
        write_json(destination / "generation.json", meta)
        print(
            f"{run['run_id']}: {meta['status']}; startup={meta['start_cue_status']}; "
            f"output={meta['output_audio_sec']:.2f}s; transport={transmission_ok}",
            flush=True,
        )
    return meta["status"] == "COMPLETE"


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace-root",
        help="Base directory for relative plan, input, gap, cue, and output paths.",
    )
    parser.add_argument("--plan", required=True)
    parser.add_argument("--only-run", action="append")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--billing-confirmed", choices=["paid-authorized"])
    parser.add_argument(
        "--resume-pad-sec",
        type=float,
        help="Must match input_controller.resume_pad_sec in the immutable plan.",
    )
    parser.add_argument("--worker", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.workspace_root:
        set_workspace_root(args.workspace_root)
    plan_path = resolve(args.plan)
    plan = json.loads(plan_path.read_text())
    plan_hash = sha(plan_path)
    validation = validate(plan, args.resume_pad_sec)
    if args.worker:
        if not args.billing_confirmed:
            raise RuntimeError("Billing confirmation required")
        run = next(row for row in plan["runs"] if row["run_id"] == args.worker)
        return 0 if await run_session(plan, run, plan_hash) else 1
    selected = plan["runs"]
    if args.only_run:
        requested = set(args.only_run)
        unknown = requested - {row["run_id"] for row in selected}
        assert not unknown
        selected = [row for row in selected if row["run_id"] in requested]
    print(
        json.dumps(
            {
                "plan_sha256": plan_hash,
                "concurrency": plan["concurrency"],
                "selected": [
                    row for row in validation if row["run_id"] in {x["run_id"] for x in selected}
                ],
            },
            indent=2,
        ),
        flush=True,
    )
    if args.dry_run:
        return 0
    if not args.billing_confirmed:
        raise RuntimeError("Pass --billing-confirmed paid-authorized")
    pending = []
    for run in selected:
        destination = output_dir(run)
        if destination.exists():
            status = (
                json.loads((destination / "generation.json").read_text()).get("status")
                if (destination / "generation.json").exists()
                else "MISSING_METADATA"
            )
            if status != "COMPLETE":
                raise RuntimeError(
                    f"Existing noncomplete run {run['run_id']} ({status}); no retry"
                )
            print(f"SKIP existing COMPLETE {run['run_id']}", flush=True)
        else:
            pending.append(run)
    summary_path = plan_path.parent / (
        "execution_" + time.strftime("%Y%m%dT%H%M%S") + ".json"
    )
    summary = {
        "plan_sha256": plan_hash,
        "selected_run_ids": [run["run_id"] for run in selected],
        "completed": [],
        "errors": [],
        "status": "RUNNING",
    }
    write_json(summary_path, summary)
    active: dict[asyncio.Task, tuple[dict, asyncio.subprocess.Process]] = {}
    stopped = False
    while pending or active:
        while pending and not stopped and len(active) < plan["concurrency"]:
            run = pending.pop(0)
            command = [
                sys.executable,
                str(Path(__file__).resolve()),
                "--workspace-root",
                str(ROOT),
                "--plan",
                str(plan_path),
                "--worker",
                run["run_id"],
                "--billing-confirmed",
                "paid-authorized",
            ]
            if args.resume_pad_sec is not None:
                command.extend(["--resume-pad-sec", str(args.resume_pad_sec)])
            process = await asyncio.create_subprocess_exec(*command)
            active[asyncio.create_task(process.wait())] = (run, process)
        if not active:
            break
        done, _ = await asyncio.wait(active, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            run, process = active.pop(task)
            code = task.result()
            summary["completed" if code == 0 else "errors"].append(
                {"run_id": run["run_id"], "exit_code": code}
            )
            if code:
                stopped = True
        write_json(summary_path, summary)
    summary.update(
        status="STOPPED_ERROR" if stopped else "COMPLETE",
        not_started=[run["run_id"] for run in pending],
    )
    write_json(summary_path, summary)
    return 1 if stopped else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
