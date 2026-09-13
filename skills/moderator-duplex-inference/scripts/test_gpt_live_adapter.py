#!/usr/bin/env python3
import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parent / "adapters/gpt_live_gap_only.py"
SPEC = importlib.util.spec_from_file_location("gpt_live_gap_only", SCRIPT)
ADAPTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ADAPTER)


class SilenceCapTests(unittest.TestCase):
    def state(self, *, active_on_entry=False):
        return {
            "start_session_sec": 10.0,
            "deadline_session_sec": 12.0,
            "first_gate_event_index": 0,
            "gate_closed_on_entry": active_on_entry,
        }

    def test_waits_before_two_seconds_when_model_is_silent(self):
        self.assertFalse(ADAPTER.gap_silence_cap_due(self.state(), [], 11.999))

    def test_caps_at_two_seconds_when_model_is_silent(self):
        self.assertTrue(ADAPTER.gap_silence_cap_due(self.state(), [], 12.0))

    def test_active_audio_before_deadline_disables_cap(self):
        events = [{"kind": "first_audio", "session_sec": 11.5}]
        self.assertFalse(ADAPTER.gap_silence_cap_due(self.state(), events, 12.5))

    def test_active_audio_after_deadline_does_not_disable_cap(self):
        events = [{"kind": "first_audio", "session_sec": 12.001}]
        self.assertTrue(ADAPTER.gap_silence_cap_due(self.state(), events, 12.1))

    def test_output_already_active_at_gap_entry_disables_cap(self):
        self.assertFalse(
            ADAPTER.gap_silence_cap_due(
                self.state(active_on_entry=True), [], 15.0
            )
        )

    def test_earlier_gate_events_are_ignored(self):
        state = self.state()
        state["first_gate_event_index"] = 1
        events = [
            {"kind": "first_audio", "session_sec": 10.5},
            {"kind": "participant_resume", "session_sec": 11.0},
        ]
        self.assertTrue(ADAPTER.gap_silence_cap_due(state, events, 12.0))


if __name__ == "__main__":
    unittest.main()
