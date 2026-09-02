from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np


@dataclass(frozen=True)
class SpeechSegment:
    start_sec: float
    end_sec: float
    peak_dbfs: float

    def to_dict(self) -> dict[str, float]:
        return asdict(self)


def detect_speech_segments(
    waveform: np.ndarray,
    sample_rate: int,
    start_sec: float,
    end_sec: float,
    config: dict,
) -> list[SpeechSegment]:
    """Energy-VAD used only to locate the onset of model output speech.

    This is deliberately deterministic. The threshold is part of the frozen
    evaluation config and must be validated on development outputs before test
    freeze.
    """
    frame_samples = max(1, int(round(sample_rate * float(config["frame_ms"]) / 1000)))
    first_sample = max(0, int(round(start_sec * sample_rate)))
    last_sample = min(len(waveform), int(round(end_sec * sample_rate)))
    if last_sample <= first_sample:
        return []
    chunk = waveform[first_sample:last_sample]
    n_frames = int(np.ceil(len(chunk) / frame_samples))
    padded = np.pad(chunk, (0, n_frames * frame_samples - len(chunk)))
    frames = padded.reshape(n_frames, frame_samples)
    rms = np.sqrt(np.mean(np.square(frames, dtype=np.float64), axis=1) + 1e-12)
    dbfs = 20.0 * np.log10(rms)
    active = dbfs >= float(config["threshold_dbfs"])

    min_speech_frames = max(1, int(np.ceil(float(config["min_speech_ms"]) / config["frame_ms"])))
    max_gap_frames = max(0, int(np.floor(float(config["min_silence_ms"]) / config["frame_ms"])))
    runs = _active_runs(active)
    runs = [(start, end) for start, end in runs if end - start >= min_speech_frames]
    runs = _merge_runs(runs, max_gap_frames)

    output: list[SpeechSegment] = []
    for start_frame, end_frame in runs:
        absolute_start = first_sample + start_frame * frame_samples
        absolute_end = min(last_sample, first_sample + end_frame * frame_samples)
        output.append(SpeechSegment(
            start_sec=round(absolute_start / sample_rate, 6),
            end_sec=round(absolute_end / sample_rate, 6),
            peak_dbfs=round(float(np.max(dbfs[start_frame:end_frame])), 3),
        ))
    return output


def _active_runs(active: np.ndarray) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    start = None
    for index, value in enumerate(active):
        if value and start is None:
            start = index
        if not value and start is not None:
            runs.append((start, index))
            start = None
    if start is not None:
        runs.append((start, len(active)))
    return runs


def _merge_runs(runs: list[tuple[int, int]], max_gap: int) -> list[tuple[int, int]]:
    if not runs:
        return []
    merged = [runs[0]]
    for start, end in runs[1:]:
        previous_start, previous_end = merged[-1]
        if start - previous_end <= max_gap:
            merged[-1] = (previous_start, end)
        else:
            merged.append((start, end))
    return merged
