#!/usr/bin/env python3

import importlib.util
import tempfile
import unittest
import wave
from array import array
from pathlib import Path


SCRIPT = Path(__file__).with_name("evaluate_report.py")
SPEC = importlib.util.spec_from_file_location("evaluate_report", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)

FINALIZER_SCRIPT = Path(__file__).with_name("apply_semantic_review.py")
FINALIZER_SPEC = importlib.util.spec_from_file_location("apply_semantic_review", FINALIZER_SCRIPT)
FINALIZER = importlib.util.module_from_spec(FINALIZER_SPEC)
assert FINALIZER_SPEC and FINALIZER_SPEC.loader
FINALIZER_SPEC.loader.exec_module(FINALIZER)


CONTRACT = MODULE.read_json(Path(__file__).parents[1] / "references" / "eval-contract.json")


class EvalHelpersTest(unittest.TestCase):
    def test_distribution_uses_linear_quartiles(self):
        self.assertEqual(
            FINALIZER.distribution([1.0, 2.0, 3.0, 4.0]),
            {"n": 4, "median": 2.5, "q1": 1.75, "q3": 3.25},
        )
        self.assertEqual(
            FINALIZER.distribution([]),
            {"n": 0, "median": None, "q1": None, "q3": None},
        )
        self.assertEqual(len(FINALIZER.BARGE_PRECEDENCE), 7)

    def test_timing_boundaries(self):
        self.assertEqual(MODULE.classify_timing(8.0, 8.0, 12.0), "ON_TIME")
        self.assertEqual(MODULE.classify_timing(12.0, 8.0, 12.0), "ON_TIME")
        self.assertEqual(MODULE.classify_timing(7.999, 8.0, 12.0), "PREMATURE")
        self.assertEqual(MODULE.classify_timing(12.001, 8.0, 12.0), "LATE")
        self.assertEqual(MODULE.classify_timing(None, 8.0, 12.0), "MISSED")

    def test_backchannel_and_time_exception(self):
        self.assertTrue(MODULE.is_backchannel({"start_sec": 0, "end_sec": 0.2, "text": "Okay"}, CONTRACT))
        self.assertFalse(MODULE.is_backchannel({"start_sec": 0, "end_sec": 0.2, "text": "Time."}, CONTRACT))
        self.assertFalse(MODULE.is_backchannel({"start_sec": 0, "end_sec": 1.0, "text": "Ten seconds"}, CONTRACT))

    def test_piecewise_clock_mapping(self):
        spans = [
            {"source_start_sec": 10, "source_end_sec": 20, "session_start_sec": 2, "session_end_sec": 12},
            {"source_start_sec": 25, "source_end_sec": 30, "session_start_sec": 15, "session_end_sec": 20},
        ]
        self.assertAlmostEqual(MODULE.source_to_session(15, spans), 7)
        self.assertAlmostEqual(MODULE.source_to_session(27, spans), 17)
        with self.assertRaises(MODULE.ContractError):
            MODULE.source_to_session(22, spans)

    def test_vad_is_clipped_to_participant_support(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input.wav"
            rate = 1000
            values = array("h", [1000] * 500 + [0] * 500 + [1000] * 500)
            with wave.open(str(path), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(rate)
                wav.writeframes(values.tobytes())
            spec = {
                "frame_ms": 20, "peak_abs_threshold": 256,
                "min_speech_ms": 200, "min_silence_ms": 100,
                "status": "test",
            }
            intervals, _ = MODULE.participant_vad(
                path,
                [{"session_start_sec": 1.0, "session_end_sec": 1.5}],
                spec,
            )
            self.assertEqual(intervals, [{"session_start_sec": 1.0, "session_end_sec": 1.5}])

    def test_crossfire_rows_wait_for_semantic_anchor(self):
        gt = [{
            "gt_id": "D:mod:1", "debate_id": "D", "mod_turn_id": 1,
            "gap_id": "g", "probe_id": "p", "code": "A4xf", "phase": 2,
            "source_window_sec": [148, 150, 152], "trigger_text": [],
            "criteria": ["says that ten seconds remain (the word 'ten')"],
            "source_mod_interval_sec": [150, 151],
        }]
        run = {"model_turns": [], "clock_spans": []}
        rows = MODULE.score_timing(gt, run, {"xf_open_sec": 10}, CONTRACT, None)
        self.assertEqual(rows[0]["timing"], "ANCHOR_PENDING")
        self.assertIsNone(rows[0]["candidate_search_sec"])

    def test_reference_fallback_maps_complete_source_deadline(self):
        gt = [{
            "gt_id": "D:mod:1", "debate_id": "D", "mod_turn_id": 1,
            "gap_id": "g", "probe_id": "p", "code": "A4xf", "phase": 2,
            "source_window_sec": [148, 150, 152], "trigger_text": [],
            "criteria": ["says that ten seconds remain (the word 'ten')"],
            "source_mod_interval_sec": [150, 151],
        }]
        # A ten-second source interval was skipped before the crossfire cue.
        spans = [
            {"source_start_sec": 0, "source_end_sec": 100, "session_start_sec": 0, "session_end_sec": 100},
            {"source_start_sec": 110, "source_end_sec": 200, "session_start_sec": 100, "session_end_sec": 190},
        ]
        run = {"model_turns": [], "clock_spans": spans}
        rows = MODULE.score_timing(
            gt, run, {"xf_open_sec": 10}, CONTRACT, {"opened_crossfire": False}
        )
        # Correct: map source 10 + 140 = 150 -> session 140. Incorrect map-then-add is 150.
        self.assertEqual(rows[0]["session_window_sec"], [138.0, 140.0, 142.0])

    def test_model_anchor_uses_a3_1_candidate_end(self):
        common = {
            "debate_id": "D", "gap_id": "g", "phase": 2,
            "trigger_text": [], "source_mod_interval_sec": [0, 1],
        }
        gt = [
            {**common, "gt_id": "D:mod:1", "mod_turn_id": 1, "probe_id": "p1",
             "code": "A3-1", "source_window_sec": [10, 10, 12],
             "criteria": CONTRACT["content"]["criteria"]["A3-1"]},
            {**common, "gt_id": "D:mod:2", "mod_turn_id": 2, "probe_id": "p2",
             "code": "A4xf", "source_window_sec": [148, 150, 152],
             "criteria": CONTRACT["content"]["criteria"]["A4xf"]},
        ]
        run = {
            "model_turns": [{"turn": 1, "start_sec": 10.0, "end_sec": 12.5, "text": "Next round."}],
            "clock_spans": [{"source_start_sec": 0, "source_end_sec": 300,
                             "session_start_sec": 0, "session_end_sec": 300}],
        }
        rows = MODULE.score_timing(
            gt, run, {"xf_open_sec": 10}, CONTRACT, {"opened_crossfire": True}
        )
        self.assertEqual(rows[1]["session_window_sec"], [150.5, 152.5, 154.5])
        self.assertEqual(rows[1]["window_anchor"], "model_A3-1_end")

    def test_model_anchor_rejects_changed_candidate(self):
        gt = [{
            "gt_id": "D:mod:1", "debate_id": "D", "mod_turn_id": 1,
            "gap_id": "g", "probe_id": "p", "code": "A3-1", "phase": 1,
            "source_window_sec": [10, 10, 12], "trigger_text": [],
            "criteria": CONTRACT["content"]["criteria"]["A3-1"],
            "source_mod_interval_sec": [10, 11],
        }]
        run = {
            "model_turns": [{"turn": 2, "start_sec": 10, "end_sec": 11, "text": "Next round."}],
            "clock_spans": [{"source_start_sec": 0, "source_end_sec": 20,
                             "session_start_sec": 0, "session_end_sec": 20}],
        }
        with self.assertRaises(MODULE.ContractError):
            MODULE.score_timing(
                gt, run, {"xf_open_sec": 10}, CONTRACT,
                {"opened_crossfire": True, "candidate_utterance_id": "D:utt:1"},
            )


if __name__ == "__main__":
    unittest.main()
