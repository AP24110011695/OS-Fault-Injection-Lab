import tempfile
import unittest
from pathlib import Path

import event_log


class TestEventLog(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.log_path = Path(self.temp_dir.name) / "test_events.jsonl"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_log_event_and_read_events(self) -> None:
        entry = event_log.log_event(
            trial_id="test_001",
            fault_type="process_kill",
            event="INJECTED",
            details="SIGKILL sent to PID 123",
            log_path=self.log_path,
        )

        self.assertEqual(entry["trial_id"], "test_001")
        self.assertEqual(entry["fault_type"], "process_kill")
        self.assertEqual(entry["event"], "INJECTED")
        self.assertIn("timestamp", entry)

        events = event_log.read_events(log_path=self.log_path)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["trial_id"], "test_001")
        self.assertEqual(events[0]["event"], "INJECTED")
        self.assertEqual(events[0]["details"], "SIGKILL sent to PID 123")

    def test_filter_by_trial_id_and_fault_type(self) -> None:
        event_log.log_event("t1", "process_kill", "STARTED", log_path=self.log_path)
        event_log.log_event("t1", "process_kill", "INJECTED", log_path=self.log_path)
        event_log.log_event("t2", "cpu_hog", "STARTED", log_path=self.log_path)
        event_log.log_event("t2", "cpu_hog", "INJECTED", log_path=self.log_path)

        # Filter by trial_id
        t1_events = event_log.read_events(trial_id="t1", log_path=self.log_path)
        self.assertEqual(len(t1_events), 2)
        for e in t1_events:
            self.assertEqual(e["trial_id"], "t1")

        # Filter by fault_type
        cpu_events = event_log.read_events(fault_type="cpu_hog", log_path=self.log_path)
        self.assertEqual(len(cpu_events), 2)
        for e in cpu_events:
            self.assertEqual(e["fault_type"], "cpu_hog")

        # Filter by both
        none_events = event_log.read_events(trial_id="t1", fault_type="cpu_hog", log_path=self.log_path)
        self.assertEqual(len(none_events), 0)

    def test_clear_log(self) -> None:
        event_log.log_event("t1", "process_kill", "STARTED", log_path=self.log_path)
        self.assertEqual(len(event_log.read_events(log_path=self.log_path)), 1)

        event_log.clear_log(log_path=self.log_path)
        self.assertEqual(len(event_log.read_events(log_path=self.log_path)), 0)

    def test_read_empty_or_nonexistent_log(self) -> None:
        non_existent = Path(self.temp_dir.name) / "non_existent.jsonl"
        self.assertEqual(event_log.read_events(log_path=non_existent), [])


if __name__ == "__main__":
    unittest.main()
