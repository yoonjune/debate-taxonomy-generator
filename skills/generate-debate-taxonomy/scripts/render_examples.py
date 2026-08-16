#!/usr/bin/env python3
"""Render every positive taxonomy fixture into one human-readable catalog."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = SKILL_ROOT / "examples"
RENDERER = SKILL_ROOT / "scripts" / "render_sample.py"
DEFAULT_OUTPUT = SKILL_ROOT / "references" / "example-catalog.md"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    sections = [
        "# Taxonomy example catalog",
        "",
        "아래 9개 fixture는 각 taxonomy의 선행 trigger, MOD action, 결과와 한국어 해석을 보여준다.",
        "표시된 PASS는 deterministic structural/timing validation이며 human correctness가 아니다.",
        "B1과 B2는 별도 semantic review가 필요하다.",
        "",
    ]
    for path in sorted(EXAMPLES.glob("*.json")):
        result = subprocess.run(
            [sys.executable, str(RENDERER), str(path)],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            sys.stderr.write(result.stdout)
            sys.stderr.write(result.stderr)
            return result.returncode
        sections.extend([result.stdout.rstrip(), "", "---", ""])

    args.output.write_text("\n".join(sections).rstrip() + "\n", encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
