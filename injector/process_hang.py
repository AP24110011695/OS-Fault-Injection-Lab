import os
import signal
import subprocess
import time
from pathlib import Path

import psutil

import config
import event_log


def reset_heartbeat_file() -> None:
    """Truncate the heartbeat file so staleness is measured against the current run only."""
    path: Path = Path(config.HEARTBEAT_FILE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")


def inject(target_pid: int, trial_id: str) -> None:
    if not psutil.pid_exists(target_pid):
        error_msg: str = f"Cannot stop PID {target_pid}: process does not exist"
        event_log.log_event(
            trial_id=trial_id,
            fault_type="process_hang",
            event="FAILED",
            details=error_msg,
        )
        raise ProcessLookupError(error_msg)

    try:
        # SIGSTOP cannot be caught or ignored; the process stays alive but frozen
        os.kill(target_pid, signal.SIGSTOP)
    except ProcessLookupError as exc:
        error_msg = f"Cannot stop PID {target_pid}: process exited before signal"
        event_log.log_event(
            trial_id=trial_id,
            fault_type="process_hang",
            event="FAILED",
            details=error_msg,
        )
        raise ProcessLookupError(error_msg) from exc

    status: str = psutil.Process(target_pid).status()
    event_log.log_event(
        trial_id=trial_id,
        fault_type="process_hang",
        event="INJECTED",
        details=f"Sent SIGSTOP to PID {target_pid} (status: {status})",
    )


if __name__ == "__main__":
    print("Testing process_hang injector...")
    trial_id: str = "manual_hang_test"
    event_log.clear_log()
    reset_heartbeat_file()

    proc = subprocess.Popen(config.TARGET_CMD)
    print(f"Target process launched with PID {proc.pid}")
    time.sleep(1.5)
    assert psutil.pid_exists(proc.pid), f"PID {proc.pid} should be running"

    print(f"Injecting SIGSTOP into PID {proc.pid}...")
    inject(proc.pid, trial_id)
    time.sleep(0.2)
    status: str = psutil.Process(proc.pid).status()
    print(f"Target status after SIGSTOP: {status}")
    assert status == psutil.STATUS_STOPPED, f"Target should be stopped, got {status}"

    print("Resuming with SIGCONT...")
    os.kill(proc.pid, signal.SIGCONT)
    time.sleep(1.2)
    status = psutil.Process(proc.pid).status()
    print(f"Target status after SIGCONT: {status}")
    assert status != psutil.STATUS_STOPPED, "Target should be running again after SIGCONT"

    # A fresh heartbeat must have been written after the resume
    age_lines: list[str] = Path(config.HEARTBEAT_FILE_PATH).read_text(encoding="utf-8").splitlines()
    assert age_lines, "Heartbeat file should contain timestamps"

    # Cleanup: a stopped target ignores SIGTERM, so always SIGKILL
    try:
        proc.kill()
        proc.wait(timeout=1.0)
    except Exception:
        pass
    assert not psutil.pid_exists(proc.pid), "Target should be dead after SIGKILL"

    print("\nEvents recorded for trial:")
    for entry in event_log.read_events(trial_id=trial_id):
        print(f"  [{entry['timestamp']}] {entry['event']}: {entry['details']}")

    injected_events = [e for e in event_log.read_events(trial_id=trial_id) if e["event"] == "INJECTED"]
    assert len(injected_events) == 1, "Expected exactly one INJECTED event"

    print("\nOK: Process hang injector verified successfully.")
