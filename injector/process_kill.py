import os
import signal
import subprocess
import time

import psutil

import config
import event_log


def inject(target_pid: int, trial_id: str) -> None:
    if not psutil.pid_exists(target_pid):
        error_msg: str = f"Cannot kill PID {target_pid}: process does not exist"
        event_log.log_event(
            trial_id=trial_id,
            fault_type="process_kill",
            event="FAILED",
            details=error_msg,
        )
        raise ProcessLookupError(error_msg)

    try:
        # SIGKILL (signal 9) cannot be caught or ignored; forces immediate process termination
        os.kill(target_pid, signal.SIGKILL)
    except ProcessLookupError as exc:
        error_msg = f"Cannot kill PID {target_pid}: process exited before signal"
        event_log.log_event(
            trial_id=trial_id,
            fault_type="process_kill",
            event="FAILED",
            details=error_msg,
        )
        raise ProcessLookupError(error_msg) from exc

    event_log.log_event(
        trial_id=trial_id,
        fault_type="process_kill",
        event="INJECTED",
        details=f"Sent SIGKILL to PID {target_pid}",
    )


if __name__ == "__main__":
    print("Testing process_kill injector...")
    trial_id: str = "manual_test_kill"
    event_log.clear_log()

    # Launch dummy target process
    proc = subprocess.Popen(config.TARGET_CMD)
    print(f"Target process launched with PID {proc.pid}")
    event_log.log_event(
        trial_id=trial_id,
        fault_type="process_kill",
        event="STARTED",
        details=f"Target process started with PID {proc.pid}",
    )

    # Let process stabilize and produce heartbeats
    time.sleep(1.5)
    assert psutil.pid_exists(proc.pid), f"PID {proc.pid} should be running"

    print(f"Injecting SIGKILL into PID {proc.pid}...")
    inject(proc.pid, trial_id)

    # Allow kernel to reap process table entry
    try:
        proc.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        pass

    is_alive: bool = psutil.pid_exists(proc.pid)
    print(f"Target process alive status: {is_alive}")
    assert not is_alive, f"Target PID {proc.pid} should be dead after SIGKILL"

    # Display event log entries for this trial
    logged = event_log.read_events(trial_id=trial_id)
    print(f"\nEvents recorded for {trial_id}:")
    for entry in logged:
        print(f"  [{entry['timestamp']}] {entry['event']}: {entry['details']}")

    # Verify INJECTED event presence
    injected_events = [e for e in logged if e["event"] == "INJECTED"]
    assert len(injected_events) == 1, "Expected exactly one INJECTED event"

    print("\nOK: Process kill injector verified successfully.")
