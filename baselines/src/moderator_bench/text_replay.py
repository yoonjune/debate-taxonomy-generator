from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .data import Dataset, sha256_file


TEXT_PAD_TOKEN_ID = 3


class OffsetTokenizer(Protocol):
    def encode(self, text: str, *, out_type: str) -> Any: ...


@dataclass(frozen=True)
class TextReplaySchedule:
    token_ids: list[int]
    lexical_rows: list[dict[str, Any]]
    frame_rate_hz: float
    release_frame: int

    @property
    def sha256(self) -> str:
        payload = json.dumps(self.token_ids, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def artifact(self) -> dict[str, Any]:
        return {
            "schema_version": "0.1",
            "fill_token_id": TEXT_PAD_TOKEN_ID,
            "frame_rate_hz": self.frame_rate_hz,
            "release_frame": self.release_frame,
            "forced_frame_count": len(self.token_ids),
            "lexical_token_count": len(self.lexical_rows),
            "dense_token_ids_sha256": self.sha256,
            "lexical_rows": self.lexical_rows,
        }


def attach_moderator_alignments(
    dataset: Dataset,
    debate_id: str,
    release_sec: float,
    alignment_index_path: str | Path,
) -> dict[str, Any]:
    """Validate and attach exactly the moderator turns needed before release."""

    index_path = Path(alignment_index_path).resolve()
    index = json.loads(index_path.read_text(encoding="utf-8"))
    rows: dict[tuple[str, int], dict[str, Any]] = {}
    for row in index.get("rows", []):
        key = (str(row.get("debate_id")), int(row.get("turn_index", -1)))
        if key in rows:
            raise ValueError(f"duplicate alignment row for {key}")
        rows[key] = row

    timeline = json.loads(dataset.timeline_path(debate_id).read_text(encoding="utf-8"))
    needed = [
        turn
        for turn in timeline["turns"]
        if turn["speaker"] == "MOD" and float(turn["start_sec"]) < release_sec
    ]
    attached = []
    for turn in needed:
        if float(turn["end_sec"]) > release_sec + 1e-6:
            raise ValueError(
                f"{debate_id}:{turn['i']} crosses release; partial text replay is not defined"
            )
        key = (debate_id, int(turn["i"]))
        row = rows.get(key)
        if row is None or row.get("status") != "ALIGNED":
            raise ValueError(f"missing usable alignment for {debate_id}:{turn['i']}")
        artifact_path = Path(row["artifact"])
        if not artifact_path.is_absolute():
            artifact_path = index_path.parent / artifact_path
        artifact_path = artifact_path.resolve()
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        _validate_attached_artifact(dataset, debate_id, turn, artifact)
        attached.append({
            "turn_index": int(turn["i"]),
            "artifact": str(artifact_path),
            "artifact_sha256": sha256_file(artifact_path),
        })

    return {
        "alignment_index": str(index_path),
        "alignment_index_sha256": sha256_file(index_path),
        "aligner": _shared_aligner_metadata(attached),
        "turns": attached,
    }


def build_text_replay_schedule(
    alignment_input: dict[str, Any],
    tokenizer: OffsetTokenizer,
    *,
    frame_rate_hz: float,
    release_sec: float,
) -> TextReplaySchedule:
    release_frame = int(math.floor(release_sec * frame_rate_hz))
    dense = [TEXT_PAD_TOKEN_ID] * release_frame
    lexical_rows: list[dict[str, Any]] = []
    previous_frame = -1
    for turn_ref in alignment_input["turns"]:
        artifact_path = Path(turn_ref["artifact"])
        if sha256_file(artifact_path) != turn_ref["artifact_sha256"]:
            raise ValueError(f"alignment artifact hash changed: {artifact_path}")
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        if not artifact["quality"]["usable"]:
            raise ValueError(
                f"alignment {artifact_path} has quality flags {artifact['quality']['flags']}"
            )
        rows = _turn_token_rows(artifact, tokenizer, frame_rate_hz, release_frame)
        for row in rows:
            frame = int(row["frame_index"])
            if frame <= previous_frame:
                raise ValueError("moderator token frames are not globally increasing")
            if dense[frame] != TEXT_PAD_TOKEN_ID:
                raise ValueError(f"two text tokens map to frame {frame}")
            dense[frame] = int(row["token_id"])
            lexical_rows.append(row)
            previous_frame = frame
    return TextReplaySchedule(
        token_ids=dense,
        lexical_rows=lexical_rows,
        frame_rate_hz=frame_rate_hz,
        release_frame=release_frame,
    )


def _turn_token_rows(
    artifact: dict[str, Any],
    tokenizer: OffsetTokenizer,
    frame_rate_hz: float,
    release_frame: int,
) -> list[dict[str, Any]]:
    transcript = artifact["transcript"]
    word_spans = _locate_aligned_units(transcript, artifact["words"])
    proto = tokenizer.encode(transcript, out_type="immutable_proto")
    pieces = list(proto.pieces)
    if not pieces:
        raise ValueError(f"no PersonaPlex text tokens for {artifact['debate_id']}:{artifact['turn_index']}")

    piece_units = [_nearest_unit(int(piece.begin), int(piece.end), word_spans) for piece in pieces]
    unit_counts: dict[int, int] = {}
    for unit in piece_units:
        unit_counts[unit] = unit_counts.get(unit, 0) + 1
    unit_seen: dict[int, int] = {}
    desired: list[float] = []
    for unit in piece_units:
        position = unit_seen.get(unit, 0)
        count = unit_counts[unit]
        word = artifact["words"][unit]
        within_turn = float(word["start_sec"]) + (
            (position + 0.5) / count * (float(word["end_sec"]) - float(word["start_sec"]))
        )
        desired.append((float(artifact["timeline_start_sec"]) + within_turn) * frame_rate_hz)
        unit_seen[unit] = position + 1

    lower = int(math.floor(float(artifact["timeline_start_sec"]) * frame_rate_hz))
    upper = min(
        release_frame - 1,
        int(math.ceil(float(artifact["timeline_end_sec"]) * frame_rate_hz)) - 1,
    )
    frames = _pack_unique_frames(desired, lower, upper)
    rows = []
    for piece, unit, frame, target in zip(pieces, piece_units, frames, desired):
        rows.append({
            "debate_id": artifact["debate_id"],
            "turn_index": int(artifact["turn_index"]),
            "frame_index": frame,
            "time_sec": round(frame / frame_rate_hz, 6),
            "desired_time_sec": round(target / frame_rate_hz, 6),
            "token_id": int(piece.id),
            "piece": str(piece.piece),
            "aligned_unit_index": unit,
            "aligned_unit": artifact["words"][unit]["text"],
            "aligned_unit_zero_duration": (
                artifact["words"][unit]["start_sec"] == artifact["words"][unit]["end_sec"]
            ),
        })
    return rows


def _locate_aligned_units(
    transcript: str, words: list[dict[str, Any]]
) -> list[tuple[int, int]]:
    cursor = 0
    spans = []
    for index, word in enumerate(words):
        target = _clean_unit(str(word["text"]))
        if not target:
            raise ValueError(f"aligned unit {index} is empty after normalization")
        accumulated = ""
        start = None
        end = None
        for char_index in range(cursor, len(transcript)):
            char = transcript[char_index]
            cleaned = _clean_unit(char)
            if not cleaned and start is None:
                continue
            if cleaned:
                if start is None:
                    start = char_index
                accumulated += cleaned
                if not target.startswith(accumulated):
                    raise ValueError(
                        f"aligned unit {word['text']!r} does not match transcript near {cursor}"
                    )
                if accumulated == target:
                    end = char_index + 1
                    break
        if start is None or end is None:
            raise ValueError(f"could not locate aligned unit {word['text']!r} in transcript")
        spans.append((start, end))
        cursor = end
    remaining = _clean_unit(transcript[cursor:])
    if remaining:
        raise ValueError(f"unaligned lexical transcript suffix: {transcript[cursor:]!r}")
    return spans


def _nearest_unit(begin: int, end: int, spans: list[tuple[int, int]]) -> int:
    best_index = -1
    best_key: tuple[int, int] | None = None
    for index, (word_start, word_end) in enumerate(spans):
        overlap = max(0, min(end, word_end) - max(begin, word_start))
        distance = 0 if overlap else min(abs(end - word_start), abs(begin - word_end))
        key = (-overlap, distance)
        if best_key is None or key < best_key:
            best_index = index
            best_key = key
    if best_index < 0:
        raise ValueError("cannot map tokenizer piece without aligned units")
    return best_index


def _pack_unique_frames(desired: list[float], lower: int, upper: int) -> list[int]:
    if upper < lower or upper - lower + 1 < len(desired):
        raise ValueError(
            f"not enough text frames: need {len(desired)}, available {max(0, upper - lower + 1)}"
        )
    frames: list[int] = []
    for target in desired:
        frame = max(lower, int(round(target)))
        if frames:
            frame = max(frame, frames[-1] + 1)
        frames.append(frame)
    if frames[-1] > upper:
        frames[-1] = upper
        for index in range(len(frames) - 2, -1, -1):
            frames[index] = min(frames[index], frames[index + 1] - 1)
    if frames[0] < lower:
        raise ValueError("text token packing crossed the turn start")
    return frames


def _clean_unit(text: str) -> str:
    return "".join(
        char.casefold()
        for char in unicodedata.normalize("NFKC", text)
        if char == "'" or unicodedata.category(char).startswith(("L", "N"))
    )


def _validate_attached_artifact(
    dataset: Dataset, debate_id: str, turn: dict[str, Any], artifact: dict[str, Any]
) -> None:
    if artifact.get("status") != "ALIGNED":
        raise ValueError(f"alignment artifact is not ALIGNED for {debate_id}:{turn['i']}")
    if artifact.get("debate_id") != debate_id or int(artifact.get("turn_index", -1)) != int(turn["i"]):
        raise ValueError(f"alignment identity mismatch for {debate_id}:{turn['i']}")
    if artifact.get("transcript") != turn["text"]:
        raise ValueError(f"alignment transcript mismatch for {debate_id}:{turn['i']}")
    if artifact["audio"]["sha256"] != sha256_file(dataset.turn_audio_path(debate_id, int(turn["i"]))):
        raise ValueError(f"alignment audio hash mismatch for {debate_id}:{turn['i']}")
    if abs(float(artifact["timeline_start_sec"]) - float(turn["start_sec"])) > 1e-6:
        raise ValueError(f"alignment start mismatch for {debate_id}:{turn['i']}")
    if abs(float(artifact["timeline_end_sec"]) - float(turn["end_sec"])) > 1e-6:
        raise ValueError(f"alignment end mismatch for {debate_id}:{turn['i']}")
    if not artifact["quality"]["usable"]:
        raise ValueError(
            f"alignment quality flags for {debate_id}:{turn['i']}: {artifact['quality']['flags']}"
        )


def _shared_aligner_metadata(attached: list[dict[str, Any]]) -> dict[str, Any] | None:
    metadata = None
    for turn in attached:
        artifact = json.loads(Path(turn["artifact"]).read_text(encoding="utf-8"))
        if metadata is None:
            metadata = artifact["aligner"]
        elif metadata != artifact["aligner"]:
            raise ValueError("attached turns use different aligner versions")
    return metadata
