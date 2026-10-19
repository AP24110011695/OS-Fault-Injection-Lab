import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import config
from monitor.detector import (
    check_cgroup_memory_pressure,
    check_cpu_pressure,
    is_process_alive,
)


class TestDetector(unittest.TestCase):
    def test_check_cpu_pressure_below_threshold(self) -> None:
        detected, breaches, details = check_cpu_pressure(
            cpu_percent=config.CPU_THRESHOLD_PERCENT - 10.0,
            consecutive_breaches=2,
        )
        self.assertFalse(detected)
        self.assertEqual(breaches, 0)
        self.assertEqual(details, "")

    def test_check_cpu_pressure_debounce_and_detection(self) -> None:
        threshold = config.CPU_THRESHOLD_PERCENT
        needed = config.CONSECUTIVE_POLLS_THRESHOLD

        breaches = 0
        for i in range(1, needed):
            detected, breaches, _ = check_cpu_pressure(cpu_percent=threshold + 5.0, consecutive_breaches=breaches)
            self.assertFalse(detected)
            self.assertEqual(breaches, i)

        # The N-th consecutive breach triggers detection
        detected, breaches, details = check_cpu_pressure(cpu_percent=threshold + 5.0, consecutive_breaches=breaches)
        self.assertTrue(detected)
        self.assertEqual(breaches, needed)
        self.assertIn("CPU threshold exceeded", details)

    def test_check_cgroup_memory_pressure_oom_kill(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cg_path = Path(tmpdir)
            events_file = cg_path / "memory.events"
            events_file.write_text("low 0\nhigh 0\nmax 0\noom 0\noom_kill 2\noom_group_kill 0\n")

            detected, breaches, details = check_cgroup_memory_pressure(cg_path, consecutive_breaches=0)
            self.assertTrue(detected)
            self.assertIn("OOM kill triggered", details)
            self.assertIn("2 kill(s)", details)

    def test_check_cgroup_memory_pressure_ratio_debounce(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cg_path = Path(tmpdir)
            cur_file = cg_path / "memory.current"
            max_file = cg_path / "memory.max"

            # 95MB / 100MB = 95% (above default 90% threshold)
            cur_file.write_text(str(95 * 1024 * 1024))
            max_file.write_text(str(100 * 1024 * 1024))

            needed = config.CONSECUTIVE_POLLS_THRESHOLD
            breaches = 0
            for i in range(1, needed):
                detected, breaches, _ = check_cgroup_memory_pressure(cg_path, consecutive_breaches=breaches)
                self.assertFalse(detected)
                self.assertEqual(breaches, i)

            detected, breaches, details = check_cgroup_memory_pressure(cg_path, consecutive_breaches=breaches)
            self.assertTrue(detected)
            self.assertEqual(breaches, needed)
            self.assertIn("Memory threshold exceeded", details)

    def test_check_cgroup_memory_pressure_below_threshold_resets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cg_path = Path(tmpdir)
            cur_file = cg_path / "memory.current"
            max_file = cg_path / "memory.max"

            # 50MB / 100MB = 50%
            cur_file.write_text(str(50 * 1024 * 1024))
            max_file.write_text(str(100 * 1024 * 1024))

            detected, breaches, _ = check_cgroup_memory_pressure(cg_path, consecutive_breaches=2)
            self.assertFalse(detected)
            self.assertEqual(breaches, 0)

    def test_check_cgroup_missing_dir(self) -> None:
        missing = Path("/path/that/does/not/exist/at/all")
        detected, breaches, details = check_cgroup_memory_pressure(missing, consecutive_breaches=0)
        self.assertFalse(detected)
        self.assertEqual(breaches, 0)

    def test_is_process_alive_with_terminated_popen(self) -> None:
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0
        self.assertFalse(is_process_alive(123456, proc=mock_proc))

    def test_is_process_alive_nonexistent_pid(self) -> None:
        # High unlikely PID
        self.assertFalse(is_process_alive(9999999))


if __name__ == "__main__":
    unittest.main()
