from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class GenerationResult:
    output_audio: Path
    output_text: Path | None
    sample_rate: int
    duration_sec: float
    wall_time_sec: float
    runtime_metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["output_audio"] = str(self.output_audio.resolve())
        value["output_text"] = str(self.output_text.resolve()) if self.output_text else None
        return value


class ModelAdapter(Protocol):
    def generate(
        self,
        manifest: dict[str, Any],
        model_config: dict[str, Any],
        output_dir: Path,
    ) -> GenerationResult:
        """Replay one probe and return the complete agent-side waveform."""
