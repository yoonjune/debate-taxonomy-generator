from __future__ import annotations

import importlib.metadata
import json
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import soundfile as sf

from .config import read_config
from .data import Dataset, sha256_file, sha256_text


class ForcedAligner(Protocol):
    def align(self, *, audio: str, text: str, language: str) -> Any: ...


@dataclass(frozen=True)
class AlignmentSelection:
    debate_id: str
    turn_index: int
    audio_path: Path
    transcript: str
    timeline_start_sec: float
    timeline_end_sec: float


def align_moderator_turns(
    data_root: str | Path,
    aligner_config_path: str | Path,
    output_dir: str | Path,
    *,
    debate_id: str | None = None,
    limit: int | None = None,
    aligner_override: ForcedAligner | None = None,
) -> Path:
    """Align isolated moderator turns and preserve one artifact per attempt.

    Qwen produces word timestamps relative to each isolated turn. Timeline
    offsets are stored separately so this artifact remains independent of any
    PersonaPlex frame rate or tokenizer.
    """

    dataset = Dataset.load(data_root)
    config_path = Path(aligner_config_path).resolve()
    config = read_config(config_path)
    _validate_aligner_config(config)
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    index_path = output_dir / "alignment_index.json"
    if index_path.exists():
        raise FileExistsError(
            f"{index_path} already exists; use a new output directory to preserve the prior run"
        )

    selections = _select_moderator_turns(dataset, debate_id=debate_id, limit=limit)
    aligner = aligner_override or _load_qwen_aligner(config)
    package_version = config["package_version"]
    if aligner_override is None:
        installed_version = importlib.metadata.version(config["package"])
        if installed_version != package_version:
            raise RuntimeError(
                f"{config['package']} version {installed_version} is installed; "
                f"expected pinned version {package_version}"
            )
    rows: list[dict[str, Any]] = []
    for selection in selections:
        turn_dir = output_dir / selection.debate_id
        turn_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = turn_dir / f"turn_{selection.turn_index:03d}.json"
        if artifact_path.exists():
            raise FileExistsError(
                f"{artifact_path} already exists; use a new output directory to preserve it"
            )
        try:
            raw = aligner.align(
                audio=str(selection.audio_path),
                text=selection.transcript,
                language=config["language"],
            )
            words = _normalize_qwen_result(raw)
            duration_sec = float(sf.info(selection.audio_path).duration)
            quality = _validate_words(words, duration_sec)
            artifact = {
                "schema_version": "0.1",
                "status": "ALIGNED",
                "debate_id": selection.debate_id,
                "turn_index": selection.turn_index,
                "timeline_start_sec": selection.timeline_start_sec,
                "timeline_end_sec": selection.timeline_end_sec,
                "transcript": selection.transcript,
                "audio": {
                    "path": str(selection.audio_path.resolve()),
                    "sha256": sha256_file(selection.audio_path),
                    "duration_sec": duration_sec,
                },
                "aligner": {
                    "model_id": config["model_id"],
                    "revision": config["revision"],
                    "package": config["package"],
                    "package_version": package_version,
                    "language": config["language"],
                },
                "words": words,
                "quality": quality,
            }
            artifact_path.write_text(
                json.dumps(artifact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            rows.append({
                "debate_id": selection.debate_id,
                "turn_index": selection.turn_index,
                "status": "ALIGNED",
                "artifact": str(artifact_path.relative_to(output_dir)),
                "quality_flags": quality["flags"],
            })
        except Exception as exc:  # Preserve failures and continue without changing settings.
            failure_path = turn_dir / f"turn_{selection.turn_index:03d}.error.json"
            failure = {
                "schema_version": "0.1",
                "status": "ERROR",
                "debate_id": selection.debate_id,
                "turn_index": selection.turn_index,
                "audio_path": str(selection.audio_path.resolve()),
                "audio_sha256": sha256_file(selection.audio_path),
                "transcript": selection.transcript,
                "transcript_sha256": sha256_text(selection.transcript),
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }
            failure_path.write_text(
                json.dumps(failure, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            rows.append({
                "debate_id": selection.debate_id,
                "turn_index": selection.turn_index,
                "status": "ERROR",
                "artifact": str(failure_path.relative_to(output_dir)),
                "error_type": type(exc).__name__,
                "error": str(exc),
            })

    index = {
        "schema_version": "0.1",
        "data_root": str(dataset.root),
        "aligner_config": str(config_path),
        "aligner_config_sha256": sha256_file(config_path),
        "filters": {"debate_id": debate_id, "limit": limit},
        "n": len(rows),
        "rows": rows,
    }
    index_path.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return index_path


def _select_moderator_turns(
    dataset: Dataset, *, debate_id: str | None, limit: int | None
) -> list[AlignmentSelection]:
    if debate_id is not None and debate_id not in dataset.debates:
        raise ValueError(f"unknown debate_id={debate_id}")
    selected: list[AlignmentSelection] = []
    debate_ids = [debate_id] if debate_id else sorted(dataset.debates)
    for current_id in debate_ids:
        timeline = json.loads(dataset.timeline_path(current_id).read_text(encoding="utf-8"))
        for turn in timeline["turns"]:
            if turn["speaker"] != "MOD":
                continue
            selected.append(AlignmentSelection(
                debate_id=current_id,
                turn_index=int(turn["i"]),
                audio_path=dataset.turn_audio_path(current_id, int(turn["i"])),
                transcript=str(turn["text"]),
                timeline_start_sec=float(turn["start_sec"]),
                timeline_end_sec=float(turn["end_sec"]),
            ))
    if limit is not None:
        if limit < 0:
            raise ValueError("limit must be non-negative")
        selected = selected[:limit]
    return selected


def _normalize_qwen_result(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, (list, tuple)) or len(raw) != 1:
        raise ValueError("Qwen aligner must return exactly one result for one audio/text pair")
    try:
        items = list(raw[0])
    except TypeError as exc:
        raise TypeError("Qwen alignment result must contain iterable timestamp items") from exc
    words = []
    for item in items:
        if isinstance(item, dict):
            text = item.get("text")
            start = item.get("start_time")
            end = item.get("end_time")
        else:
            text = getattr(item, "text", None)
            start = getattr(item, "start_time", None)
            end = getattr(item, "end_time", None)
        if not isinstance(text, str) or not text:
            raise ValueError("alignment item has no non-empty text")
        words.append({
            "text": text,
            "start_sec": round(float(start), 6),
            "end_sec": round(float(end), 6),
        })
    if not words:
        raise ValueError("Qwen aligner returned no timestamp items")
    return words


def _validate_words(words: list[dict[str, Any]], duration_sec: float) -> dict[str, Any]:
    flags: list[str] = []
    previous_start = -1.0
    previous_end = -1.0
    for index, word in enumerate(words):
        start = float(word["start_sec"])
        end = float(word["end_sec"])
        if start < 0 or end < start:
            raise ValueError(f"word {index} has invalid span [{start}, {end}]")
        if start + 1e-6 < previous_start or end + 1e-6 < previous_end:
            raise ValueError(f"word {index} is not monotonic")
        if end > duration_sec + 0.25:
            raise ValueError(
                f"word {index} ends at {end:.3f}s beyond audio duration {duration_sec:.3f}s"
            )
        if end == start:
            flags.append("ZERO_DURATION_WORD")
        if start < previous_end:
            flags.append("OVERLAPPING_WORD_SPANS")
        previous_start = start
        previous_end = end
    return {
        "usable": not flags,
        "flags": sorted(set(flags)),
        "word_count": len(words),
        "aligned_start_sec": words[0]["start_sec"],
        "aligned_end_sec": words[-1]["end_sec"],
    }


def _validate_aligner_config(config: dict[str, Any]) -> None:
    required = {
        "model_id", "revision", "package", "package_version", "language", "device_map", "dtype"
    }
    missing = sorted(required - set(config))
    if missing:
        raise ValueError(f"aligner config missing fields: {missing}")
    if not config["revision"]:
        raise ValueError("aligner model revision must be pinned")


def _load_qwen_aligner(config: dict[str, Any]) -> ForcedAligner:
    try:
        import torch
        from huggingface_hub import snapshot_download
        from qwen_asr import Qwen3ForcedAligner
    except ImportError as exc:
        raise RuntimeError(
            "Qwen aligner runtime is not installed. Install baselines/requirements-aligner.txt "
            "in an isolated environment."
        ) from exc
    dtype = getattr(torch, config["dtype"])
    snapshot_path = snapshot_download(
        repo_id=config["model_id"],
        revision=config["revision"],
    )
    return Qwen3ForcedAligner.from_pretrained(
        snapshot_path,
        dtype=dtype,
        device_map=config["device_map"],
    )
