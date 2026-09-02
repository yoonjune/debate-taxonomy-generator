from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
    return rows


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Dataset:
    root: Path
    debates: dict[str, dict[str, Any]]
    probes: dict[str, dict[str, Any]]

    @classmethod
    def load(cls, root: str | Path) -> "Dataset":
        root = Path(root).resolve()
        debates_rows = read_jsonl(root / "debates.jsonl")
        probes_rows = read_jsonl(root / "probes.jsonl")
        debates = _unique_by(debates_rows, "debate_id", root / "debates.jsonl")
        probes = _unique_by(probes_rows, "probe_id", root / "probes.jsonl")
        dataset = cls(root=root, debates=debates, probes=probes)
        dataset.validate()
        return dataset

    def validate(self) -> None:
        required = [
            self.root / "system_prompt.md",
            self.root / "voices" / "voices.json",
        ]
        missing = [str(path) for path in required if not path.is_file()]
        if missing:
            raise ValueError(f"missing dataset files: {missing}")

        for debate_id, debate in self.debates.items():
            if set(debate.get("speakers", {})) != {"MOD", "PRO", "CON"}:
                raise ValueError(f"{debate_id}: expected MOD/PRO/CON speakers")
            timeline_path = self.timeline_path(debate_id)
            if not timeline_path.is_file():
                raise ValueError(f"{debate_id}: missing timeline {timeline_path}")
            timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
            indices = [turn.get("i") for turn in timeline.get("turns", [])]
            if indices != sorted(indices) or len(indices) != len(set(indices)):
                raise ValueError(f"{debate_id}: timeline turn indices are invalid")
            for turn in timeline.get("turns", []):
                if float(turn["end_sec"]) <= float(turn["start_sec"]):
                    raise ValueError(f"{debate_id}:{turn['i']}: non-positive duration")
                if not self.turn_audio_path(debate_id, int(turn["i"])).is_file():
                    raise ValueError(f"{debate_id}:{turn['i']}: missing isolated turn audio")
            voice_id = debate["speakers"]["MOD"]["voice_id"]
            if not self.voice_path(voice_id).is_file():
                raise ValueError(f"{debate_id}: missing moderator reference voice {voice_id}")

        for probe_id, probe in self.probes.items():
            debate_id = probe.get("debate_id")
            if debate_id not in self.debates:
                raise ValueError(f"{probe_id}: unknown debate {debate_id}")
            if probe.get("label") != "none":
                for key in ("t_earliest", "t_deadline", "t_latest"):
                    if probe.get(key) is None:
                        raise ValueError(f"{probe_id}: positive probe missing {key}")

    def timeline_path(self, debate_id: str) -> Path:
        return self.root / "audio" / "mix" / f"{debate_id}.json"

    def turn_audio_path(self, debate_id: str, turn_index: int) -> Path:
        stem = self.root / "audio" / "turns" / f"{debate_id}_{turn_index:03d}"
        matches = [path for path in stem.parent.glob(stem.name + ".*") if path.suffix.lower() in AUDIO_SUFFIXES]
        if len(matches) != 1:
            return stem.with_suffix(".missing")
        return matches[0]

    def voice_path(self, voice_id: str) -> Path:
        return self.root / "voices" / f"{voice_id}.wav"

    def rendered_prompt(self, debate_id: str) -> str:
        debate = self.debates[debate_id]
        prompt = (self.root / "system_prompt.md").read_text(encoding="utf-8")
        replacements = {
            "{{MOTION}}": debate["motion"].rstrip("."),
            "{{PRO_NAME}}": debate["speakers"]["PRO"]["name"],
            "{{CON_NAME}}": debate["speakers"]["CON"]["name"],
            "{{CROSSFIRE_SEC}}": str(debate["crossfire_end_sec"]),
        }
        for source, target in replacements.items():
            prompt = prompt.replace(source, target)
        if "{{" in prompt or "}}" in prompt:
            raise ValueError(f"{debate_id}: unresolved system-prompt placeholder")
        return prompt.strip()


def _unique_by(rows: Iterable[dict[str, Any]], key: str, path: Path) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for row in rows:
        value = row.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError(f"{path}: missing string key {key}")
        if value in output:
            raise ValueError(f"{path}: duplicate {key}={value}")
        output[value] = row
    return output


AUDIO_SUFFIXES = {".wav", ".mp3", ".flac", ".ogg"}
