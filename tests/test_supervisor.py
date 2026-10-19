import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from recovery.supervisor import get_last_process, restart_target


class TestSupervisor(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.log_path = Path(self.temp_dir.name) / "test_supervisor.jsonl"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_restart_target_success_first_attempt(self) -> None:
        with patch("event_log.config.EVENT_LOG_PATH", str(self.log_path)):
            mock_proc = MagicMock()
            mock_proc.pid = 12345
            mock_proc.poll.return_value = None

            with patch("subprocess.Popen", return_value=mock_proc):
                with patch("recovery.supervisor.is_process_alive", return_value=True):
                    with patch("time.sleep"):
                        pid = restart_target(
                            trial_id="sup_test_01",
                            cmd=["dummy"],
                            max_retries=2,
                            cooldown_sec=0.01,
                        )
                        self.assertEqual(pid, 12345)

    def test_restart_target_exhausted_retries_raises_runtime_error(self) -> None:
        with patch("event_log.config.EVENT_LOG_PATH", str(self.log_path)):
            mock_dead = MagicMock()
            mock_dead.pid = 999
            mock_dead.poll.return_value = 1

            with patch("subprocess.Popen", return_value=mock_dead):
                with patch("recovery.supervisor.is_process_alive", return_value=False):
                    with patch("time.sleep") as mock_sleep:
                        with self.assertRaises(RuntimeError) as ctx:
                            restart_target(
                                trial_id="sup_test_fail",
                                cmd=["dummy"],
                                max_retries=3,
                                cooldown_sec=0.05,
                            )
                        self.assertIn("Failed to restart target after 3 attempts", str(ctx.exception))
                        self.assertTrue(mock_sleep.called)

    def test_restart_target_succeeds_on_second_attempt(self) -> None:
        with patch("event_log.config.EVENT_LOG_PATH", str(self.log_path)):
            proc_dead = MagicMock()
            proc_dead.pid = 11111
            proc_dead.poll.return_value = 1

            proc_alive = MagicMock()
            proc_alive.pid = 22222
            proc_alive.poll.return_value = None

            with patch("subprocess.Popen", side_effect=[proc_dead, proc_alive]):
                with patch("recovery.supervisor.is_process_alive", side_effect=[False, True]):
                    with patch("time.sleep"):
                        pid = restart_target(
                            trial_id="sup_test_retry",
                            cmd=["dummy"],
                            max_retries=3,
                            cooldown_sec=0.01,
                        )
                        self.assertEqual(pid, 22222)

    def test_restart_target_real_process_lifecycle(self) -> None:
        with patch("event_log.config.EVENT_LOG_PATH", str(self.log_path)):
            pid = restart_target(
                trial_id="sup_test_real",
                cmd=[sys.executable, "-c", "import time; time.sleep(1)"],
                max_retries=1,
            )
            self.assertIsInstance(pid, int)
            self.assertGreater(pid, 0)
            proc = get_last_process()
            if proc is not None:
                proc.kill()
                proc.wait()


if __name__ == "__main__":
    unittest.main()
