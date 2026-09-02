from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import soundfile as sf

from moderator_bench.alignment import align_moderator_turns


ROOT = Path(__file__).resolve().parents[2]


class FakeAlignmentResult:
    def __init__(self, items):
        self.items = items

    def __iter__(self):
        return iter(self.items)


class FakeAligner:
    def align(self, *, audio: str, text: str, language: str):
        assert Path(audio).is_file()
        assert language == "English"
        words = text.split()
        step = sf.info(audio).duration / len(words)
        return [FakeAlignmentResult([
            SimpleNamespace(text=word, start_time=i * step, end_time=(i + 1) * step)
            for i, word in enumerate(words)
        ])]


def test_alignment_artifact_is_turn_relative_and_pinned(tmp_path: Path) -> None:
    index_path = align_moderator_turns(
        ROOT / "data_sample",
        ROOT / "baselines" / "configs" / "aligners" / "qwen3_forced_aligner.json",
        tmp_path,
        debate_id="L000",
        limit=1,
        aligner_override=FakeAligner(),
    )
    index = json.loads(index_path.read_text())
    assert index["n"] == 1
    artifact = json.loads((index_path.parent / index["rows"][0]["artifact"]).read_text())
    assert artifact["turn_index"] == 0
    assert artifact["timeline_start_sec"] == 0.0
    assert artifact["aligner"]["revision"] == "c7cbfc2048c462b0d63a45797104fc9db3ad62b7"
    assert artifact["quality"]["usable"] is True
    assert artifact["words"][0]["start_sec"] == 0.0


def test_alignment_refuses_to_overwrite_run(tmp_path: Path) -> None:
    kwargs = dict(
        data_root=ROOT / "data_sample",
        aligner_config_path=(
            ROOT / "baselines" / "configs" / "aligners" / "qwen3_forced_aligner.json"
        ),
        output_dir=tmp_path,
        debate_id="L000",
        limit=1,
        aligner_override=FakeAligner(),
    )
    align_moderator_turns(**kwargs)
    try:
        align_moderator_turns(**kwargs)
    except FileExistsError:
        pass
    else:
        raise AssertionError("prior alignment run was overwritten")


class ZeroDurationAligner:
    def align(self, *, audio: str, text: str, language: str):
        words = text.split()
        items = []
        for index, word in enumerate(words):
            start = index * 0.1
            end = start if index == 1 else start + 0.1
            items.append(SimpleNamespace(text=word, start_time=start, end_time=end))
        return [FakeAlignmentResult(items)]


def test_zero_duration_word_is_preserved_as_nonfatal_warning(tmp_path: Path) -> None:
    index_path = align_moderator_turns(
        ROOT / "data_sample",
        ROOT / "baselines" / "configs" / "aligners" / "qwen3_forced_aligner.json",
        tmp_path,
        debate_id="L000",
        limit=1,
        aligner_override=ZeroDurationAligner(),
    )
    index = json.loads(index_path.read_text())
    artifact = json.loads((index_path.parent / index["rows"][0]["artifact"]).read_text())
    assert artifact["quality"]["usable"] is True
    assert artifact["quality"]["warnings"] == ["ZERO_DURATION_WORD"]
    assert artifact["quality"]["fatal_flags"] == []
    assert artifact["words"][1]["start_sec"] == artifact["words"][1]["end_sec"]
