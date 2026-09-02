from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_config(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value
