import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import psutil
import config
from monitor.detector import (
    check_cgroup_memory_pressure,
    check_cpu_pressure,
    check_disk_usage,
    check_fd_ratio,
    check_heartbeat_staleness,
    check_zombie_leak,
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

    def test_check_heartbeat_fresh_no_detection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            hb = Path(tmpdir) / "heartbeat.log"
            now = datetime(2026, 10, 24, 12, 0, 0)
            hb.write_text((now - timedelta(seconds=1)).isoformat() + "\n")

            stale, details = check_heartbeat_staleness(hb, now=now)
            self.assertFalse(stale)
            self.assertEqual(details, "")

    def test_check_heartbeat_stale_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            hb = Path(tmpdir) / "heartbeat.log"
            now = datetime(2026, 10, 24, 12, 0, 0)
            # Last heartbeat is older than HEARTBEAT_TIMEOUT_SEC
            hb.write_text(
                (now - timedelta(seconds=10)).isoformat() + "\n"
                + (now - timedelta(seconds=config.HEARTBEAT_TIMEOUT_SEC + 1.0)).isoformat() + "\n"
            )

            stale, details = check_heartbeat_staleness(hb, now=now)
            self.assertTrue(stale)
            self.assertIn("Heartbeat stale", details)

    def test_check_heartbeat_boundary_not_stale_at_exact_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            hb = Path(tmpdir) / "heartbeat.log"
            now = datetime(2026, 10, 24, 12, 0, 0)
            # Age exactly equal to the timeout is not stale (detection requires age > timeout)
            hb.write_text((now - timedelta(seconds=config.HEARTBEAT_TIMEOUT_SEC)).isoformat() + "\n")

            stale, _ = check_heartbeat_staleness(hb, now=now)
            self.assertFalse(stale)

    def test_check_heartbeat_missing_file_is_stale(self) -> None:
        missing = Path("/path/that/does/not/exist/heartbeat.log")
        stale, details = check_heartbeat_staleness(missing)
        self.assertTrue(stale)
        self.assertIn("No heartbeat", details)

    def test_check_heartbeat_skips_unparseable_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            hb = Path(tmpdir) / "heartbeat.log"
            now = datetime(2026, 10, 24, 12, 0, 0)
            hb.write_text("not-a-timestamp\n" + (now - timedelta(seconds=0.5)).isoformat() + "\n")

            stale, _ = check_heartbeat_staleness(hb, now=now)
            self.assertFalse(stale)

    def test_check_disk_usage_debounce_and_detection(self) -> None:
        with patch("monitor.detector.psutil.disk_usage") as mock_du:
            mock_du.return_value = MagicMock(percent=95.0)
            needed = config.CONSECUTIVE_POLLS_THRESHOLD

            breaches = 0
            for i in range(1, needed):
                detected, breaches, _ = check_disk_usage(Path("/tmp/fault_disk"), consecutive_breaches=breaches)
                self.assertFalse(detected)
                self.assertEqual(breaches, i)

            detected, breaches, details = check_disk_usage(Path("/tmp/fault_disk"), consecutive_breaches=breaches)
            self.assertTrue(detected)
            self.assertEqual(breaches, needed)
            self.assertIn("Disk usage exceeded", details)

    def test_check_disk_usage_below_threshold_resets(self) -> None:
        with patch("monitor.detector.psutil.disk_usage") as mock_du:
            mock_du.return_value = MagicMock(percent=50.0)

            detected, breaches, _ = check_disk_usage(Path("/tmp/fault_disk"), consecutive_breaches=2)
            self.assertFalse(detected)
            self.assertEqual(breaches, 0)

    def test_check_disk_usage_missing_path_no_detection(self) -> None:
        with patch("monitor.detector.psutil.disk_usage") as mock_du:
            mock_du.side_effect = OSError("No such file or directory")

            detected, breaches, _ = check_disk_usage(Path("/tmp/fault_disk"), consecutive_breaches=2)
            self.assertFalse(detected)
            self.assertEqual(breaches, 0)

    def test_check_fd_ratio_debounce_and_detection(self) -> None:
        with patch("monitor.detector.psutil.Process") as mock_p:
            mock_p.return_value.rlimit.return_value = (config.FD_LIMIT, config.FD_LIMIT)
            mock_p.return_value.num_fds.return_value = int(config.FD_LIMIT * 0.95)
            needed = config.CONSECUTIVE_POLLS_THRESHOLD

            breaches = 0
            for i in range(1, needed):
                detected, breaches, _ = check_fd_ratio(pid=1234, consecutive_breaches=breaches)
                self.assertFalse(detected)
                self.assertEqual(breaches, i)

            detected, breaches, details = check_fd_ratio(pid=1234, consecutive_breaches=breaches)
            self.assertTrue(detected)
            self.assertEqual(breaches, needed)
            self.assertIn("FD usage exceeded", details)

    def test_check_fd_ratio_below_threshold_resets(self) -> None:
        with patch("monitor.detector.psutil.Process") as mock_p:
            mock_p.return_value.rlimit.return_value = (config.FD_LIMIT, config.FD_LIMIT)
            mock_p.return_value.num_fds.return_value = int(config.FD_LIMIT * 0.5)

            detected, breaches, _ = check_fd_ratio(pid=1234, consecutive_breaches=2)
            self.assertFalse(detected)
            self.assertEqual(breaches, 0)

    def test_check_fd_ratio_dead_process_no_detection(self) -> None:
        with patch("monitor.detector.psutil.Process") as mock_p:
            mock_p.side_effect = psutil.NoSuchProcess(pid=1234)

            detected, breaches, _ = check_fd_ratio(pid=1234, consecutive_breaches=2)
            self.assertFalse(detected)
            self.assertEqual(breaches, 0)

    def test_check_fd_ratio_unlimited_limit_no_detection(self) -> None:
        # A process with an unlimited soft limit (RLIM_INFINITY = -1) has no meaningful ratio
        with patch("monitor.detector.psutil.Process") as mock_p:
            mock_p.return_value.rlimit.return_value = (-1, -1)
            mock_p.return_value.num_fds.return_value = 500

            detected, breaches, _ = check_fd_ratio(pid=1234, consecutive_breaches=2)
            self.assertFalse(detected)
            self.assertEqual(breaches, 0)

    def test_check_zombie_leak_debounce_and_detection(self) -> None:
        with patch("monitor.detector.count_zombie_children", return_value=config.ZOMBIE_THRESHOLD + 5):
            needed = config.CONSECUTIVE_POLLS_THRESHOLD

            breaches = 0
            for i in range(1, needed):
                detected, breaches, _ = check_zombie_leak(parent_pid=1234, consecutive_breaches=breaches)
                self.assertFalse(detected)
                self.assertEqual(breaches, i)

            detected, breaches, details = check_zombie_leak(parent_pid=1234, consecutive_breaches=breaches)
            self.assertTrue(detected)
            self.assertEqual(breaches, needed)
            self.assertIn("Zombie children detected", details)

    def test_check_zombie_leak_below_threshold_resets(self) -> None:
        with patch("monitor.detector.count_zombie_children", return_value=config.ZOMBIE_THRESHOLD - 10):

            detected, breaches, _ = check_zombie_leak(parent_pid=1234, consecutive_breaches=2)
            self.assertFalse(detected)
            self.assertEqual(breaches, 0)

    def test_check_zombie_leak_at_threshold_not_fired(self) -> None:
        # Detection requires strictly above the threshold
        with patch("monitor.detector.count_zombie_children", return_value=config.ZOMBIE_THRESHOLD):

            detected, breaches, _ = check_zombie_leak(parent_pid=1234, consecutive_breaches=2)
            self.assertFalse(detected)
            self.assertEqual(breaches, 0)


if __name__ == "__main__":
    unittest.main()
