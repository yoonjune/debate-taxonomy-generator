#!/usr/bin/env python3
import copy
import hashlib
import importlib.util
import json
import tempfile
import unittest
import wave
from array import array
from pathlib import Path


SCRIPT = Path(__file__).with_name("run_campaign.py")
SPEC = importlib.util.spec_from_file_location("run_campaign", SCRIPT)
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)
PROFILE = json.loads((SCRIPT.parents[1] / "references/gpt-live-canonical.json").read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n")


class CampaignTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        source_dir = self.root / "prepared/L001"
        source_dir.mkdir(parents=True)
        samples = array("h", [0] * 2400)
        samples[900] = 1000
        self.source = source_dir / "user.wav"
        with wave.open(str(self.source), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(24000)
            handle.writeframes(samples.tobytes())
        self.prompt = source_dir / "system_prompt.txt"
        self.prompt.write_text("Moderate the debate.\n")
        self.cue = self.root / "cue.mp3"
        self.cue.write_bytes(b"frozen cue")
        self.gap = self.root / "gaps/L001.json"
        save(self.gap, {"sample_rate": 24000, "gaps": [{"gap_id": "g1", "start_sample": 200, "end_sample": 500}]})
        self.plan = {
            "model": PROFILE["model"],
            "endpoint": PROFILE["endpoint"],
            "audio_format": PROFILE["audio_format"],
            "frame_ms": PROFILE["frame_ms"],
            "concurrency": PROFILE["concurrency"],
            "tail_sec": PROFILE["tail_sec"],
            "start_cue": {"audio": "cue.mp3", "text": PROFILE["start_cue_text"], "sha256": digest(self.cue)},
            "input_controller": copy.deepcopy(PROFILE["input_controller"]),
            "conditional_skip": copy.deepcopy(PROFILE["conditional_skip"]),
            "selected_debates": ["L001"],
            "runs": [{
                "run_id": "gpt-L001-r1",
                "debate_id": "L001",
                "condition": "B0_GAP_ONLY_GATE_ZERO_FILL_1000MS",
                "input_dir": "prepared/L001",
                "output_dir": "outputs/L001",
                "trim_leading_silence_sec": 0.005,
                "leading_trim_sample": 120,
                "source_audio_sha256": digest(self.source),
                "prompt_sha256": digest(self.prompt),
                "conditional_gap_file": "gaps/L001.json",
                "conditional_gap_sha256": digest(self.gap),
            }],
        }

    def tearDown(self):
        self.temp.cleanup()

    def test_provider_defaults_to_gpt_live(self):
        self.assertEqual(RUNNER.provider_name({}), "gpt-live")

    def test_canonical_gpt_plan_passes(self):
        rows = RUNNER.validate_gpt_plan(self.plan, self.root, PROFILE)
        self.assertEqual([row["case_id"] for row in rows], ["L001"])

    def test_gpt_threshold_drift_fails(self):
        plan = copy.deepcopy(self.plan)
        plan["input_controller"]["output_activity_detector"]["active_if_peak_abs_gte"] = 251
        with self.assertRaisesRegex(RUNNER.ContractError, "controller drift"):
            RUNNER.validate_gpt_plan(plan, self.root, PROFILE)

    def test_gpt_resume_pad_drift_fails(self):
        plan = copy.deepcopy(self.plan)
        plan["input_controller"]["resume_pad_sec"] = 0.5
        with self.assertRaisesRegex(RUNNER.ContractError, "controller drift"):
            RUNNER.validate_gpt_plan(plan, self.root, PROFILE)

    def test_registered_gap_must_be_exact_zero(self):
        samples = array("h", [0] * 2400)
        samples[300] = 1
        with wave.open(str(self.source), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(24000)
            handle.writeframes(samples.tobytes())
        self.plan["runs"][0]["source_audio_sha256"] = digest(self.source)
        with self.assertRaisesRegex(RUNNER.ContractError, "not exact zero"):
            RUNNER.validate_gpt_plan(self.plan, self.root, PROFILE)

    def test_existing_complete_is_skippable(self):
        output = self.root / "outputs/L001"
        output.mkdir(parents=True)
        save(output / "generation.json", {"status": "COMPLETE"})
        self.assertEqual(RUNNER.output_state(output), "COMPLETE_EXISTING")

    def test_existing_partial_blocks(self):
        output = self.root / "outputs/L001"
        output.mkdir(parents=True)
        save(output / "generation.json", {"status": "ERROR"})
        self.assertEqual(RUNNER.output_state(output), "EXISTING_NONCOMPLETE")

    def test_moshi_plan_maps_selected_cases(self):
        prepared = self.root / "moshi-prepared"
        manifests = []
        for case_id in ("L001", "L002"):
            manifest = prepared / case_id / "input.json"
            save(manifest, {
                "user_audio": str(self.source),
                "system_prompt": str(self.prompt),
                "voice": str(self.cue),
                "hashes": {
                    "user": digest(self.source),
                    "prompt": digest(self.prompt),
                    "voice": digest(self.cue),
                },
            })
            manifests.append(str(manifest))
        save(prepared / "index.json", manifests)
        plan = {
            "schema_version": "moderator-duplex-moshi/v1",
            "prepared_dir": "moshi-prepared",
            "output_dir": "moshi-output",
            "model": "base",
            "selected_debates": ["L002"],
            "concurrency": 1,
        }
        rows = RUNNER.validate_moshi_plan(plan, self.root)
        self.assertEqual(rows[0]["case_id"], "L002")

    def test_moshi_absolute_paths_can_be_remapped_without_source_edit(self):
        local = self.root / "local/L001/input.json"
        save(local, {"debate_id": "L001"})
        plan = {"path_remap": [{"from": "/remote/prepared", "to": "local"}]}
        resolved = RUNNER.remap_moshi_path(self.root, plan, "/remote/prepared/L001/input.json")
        self.assertEqual(resolved, local)


if __name__ == "__main__":
    unittest.main()
