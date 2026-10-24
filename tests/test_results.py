import tempfile
import unittest
from pathlib import Path

from experiment.results import group_of, read_results_csv, write_results_csv


def _row(trial_id: str, mttd: float, mttr: float) -> dict:
    return {
        "trial_id": trial_id,
        "fault_type": trial_id.rsplit("_", 1)[0],
        "mttd_sec": mttd,
        "mttr_sec": mttr,
        "success": True,
    }


class TestResults(unittest.TestCase):
    def test_group_of_strips_numeric_suffix(self) -> None:
        self.assertEqual(group_of("process_kill_001"), "process_kill")
        self.assertEqual(group_of("process_hang_resume_014"), "process_hang_resume")
        self.assertEqual(group_of("process_hang_restart_003"), "process_hang_restart")

    def test_rewrite_replaces_same_trial_ids(self) -> None:
        # Re-running a fault group must update its rows, never duplicate them
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "results.csv"

            write_results_csv([_row("process_kill_001", 0.1, 0.2)], csv_path=path)
            write_results_csv(
                [_row("process_kill_001", 0.3, 0.4), _row("memory_pressure_001", 0.5, 0.6)],
                csv_path=path,
            )

            rows = read_results_csv(path)
            self.assertEqual(len(rows), 2)
            by_id = {r["trial_id"]: r for r in rows}
            self.assertEqual(by_id["process_kill_001"]["mttd_sec"], 0.3)
            self.assertEqual(by_id["memory_pressure_001"]["mttd_sec"], 0.5)

    def test_read_write_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "results.csv"
            write_results_csv(
                [
                    _row("process_kill_001", 0.1, 0.2),
                    _row("process_hang_resume_001", 3.0, 3.2),
                    _row("fd_exhaustion_001", 6.0, None),
                ],
                csv_path=path,
            )

            rows = read_results_csv(path)
            self.assertEqual(rows[0]["mttd_sec"], 0.1)
            self.assertTrue(rows[0]["success"])
            self.assertEqual(rows[1]["trial_id"], "process_hang_resume_001")
            self.assertIsNone(rows[2]["mttr_sec"])
            self.assertTrue(rows[2]["success"])


if __name__ == "__main__":
    unittest.main()
