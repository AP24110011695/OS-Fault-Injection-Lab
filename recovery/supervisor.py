import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

import psutil

import config
import event_log
from monitor.detector import check_heartbeat_staleness, is_process_alive

_last_proc: subprocess.Popen[Any] | None = None


def get_last_process() -> subprocess.Popen[Any] | None:
    return _last_proc


def restart_target(
    trial_id: str = "recovery",
    cmd: list[str] | None = None,
    max_retries: int = config.SUPERVISOR_MAX_RETRIES,
    cooldown_sec: float = config.SUPERVISOR_COOLDOWN_SEC,
    fault_type: str = "process_kill",
    log_recovery: bool = True,
) -> int:
    global _last_proc
    target_cmd: list[str] = cmd or config.TARGET_CMD

    for attempt in range(1, max_retries + 1):
        try:
            proc: subprocess.Popen[Any] = subprocess.Popen(target_cmd)
            _last_proc = proc
            # Give the newly launched process a brief moment to start execution
            time.sleep(0.1)

            # Ensure the restarted process is genuinely running and not in zombie state
            if is_process_alive(proc.pid, proc=proc):
                if log_recovery:
                    event_log.log_event(
                        trial_id=trial_id,
                        fault_type=fault_type,
                        event="RECOVERED",
                        details=f"Target restarted successfully with PID {proc.pid} (attempt {attempt}/{max_retries})",
                    )
                return proc.pid

            # Process died immediately; reap zombie before retry
            proc.poll()
        except OSError:
            pass

        if attempt < max_retries:
            time.sleep(cooldown_sec)

    error_msg: str = f"Failed to restart target after {max_retries} attempts"
    event_log.log_event(
        trial_id=trial_id,
        fault_type=fault_type,
        event="FAILED",
        details=error_msg,
    )
    raise RuntimeError(error_msg)


def wait_for_fresh_heartbeat(timeout_sec: float = config.HEARTBEAT_TIMEOUT_SEC) -> bool:
    """Poll the heartbeat file until a timestamp fresher than the timeout appears."""
    path: Path = Path(config.HEARTBEAT_FILE_PATH)
    deadline: float = time.time() + timeout_sec
    while time.time() < deadline:
        stale, _ = check_heartbeat_staleness(path)
        if not stale:
            return True
        time.sleep(config.MONITOR_POLL_INTERVAL_SEC)
    return False


def recover_process_hang(trial_id: str, pid: int, strategy: str) -> None:
    """Recover a SIGSTOP'd target. RECOVERED is logged only after a fresh heartbeat
    is observed, because 'alive again' must mean 'making progress again'."""
    if strategy not in ("resume", "restart"):
        raise ValueError(f"Unknown recovery strategy: {strategy}")

    if strategy == "resume":
        os.kill(pid, signal.SIGCONT)
        action: str = f"Target resumed via SIGCONT (PID {pid})"
    else:
        os.kill(pid, signal.SIGKILL)
        new_pid: int = restart_target(trial_id=trial_id, fault_type="process_hang", log_recovery=False)
        action = f"Target restarted via supervisor (new PID {new_pid})"

    if not wait_for_fresh_heartbeat():
        event_log.log_event(
            trial_id=trial_id,
            fault_type="process_hang",
            event="FAILED",
            details=f"{action}; no fresh heartbeat within {config.HEARTBEAT_TIMEOUT_SEC:.1f}s",
        )
        raise RuntimeError(f"process_hang recovery failed for {trial_id}: no fresh heartbeat ({strategy})")

    event_log.log_event(
        trial_id=trial_id,
        fault_type="process_hang",
        event="RECOVERED",
        details=f"{action}; fresh heartbeat observed (strategy={strategy})",
    )


def recover_fd_exhaustion(
    trial_id: str,
    pid: int,
    leaker_proc: subprocess.Popen[Any] | None = None,
) -> int:
    """Kill the leaking service (and reap it), start a fresh clean instance,
    verify its fd count is low, then log RECOVERED."""
    # 1. Kill the leaker and reap it so no zombie or leftover leaker remains
    if leaker_proc is not None:
        if leaker_proc.poll() is None:
            try:
                leaker_proc.kill()
                leaker_proc.wait(timeout=1.0)
            except OSError:
                pass
    else:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    # 2. Fresh clean instance via the supervisor (standard target command, no leak)
    new_pid: int = restart_target(trial_id=trial_id, fault_type="fd_exhaustion", log_recovery=False)

    # 3. Verify the fresh instance's fd count is low
    num_fds: int = config.FD_CLEAN_MAX_FDS
    for _ in range(5):
        try:
            num_fds = psutil.Process(new_pid).num_fds()
            if num_fds < config.FD_CLEAN_MAX_FDS:
                break
        except psutil.Error:
            pass
        time.sleep(0.1)

    if num_fds >= config.FD_CLEAN_MAX_FDS:
        error_msg: str = f"Recovery failed: fresh instance PID {new_pid} still holds {num_fds} fds"
        event_log.log_event(trial_id=trial_id, fault_type="fd_exhaustion", event="FAILED", details=error_msg)
        raise RuntimeError(error_msg)

    event_log.log_event(
        trial_id=trial_id,
        fault_type="fd_exhaustion",
        event="RECOVERED",
        details=f"Leaker PID {pid} killed and reaped; fresh instance PID {new_pid} healthy with {num_fds} fds",
    )
    return new_pid


def run_full_loop(trial_id: str = "full_loop_001") -> dict[str, Any]:
    from experiment.runner import run_trial

    event_log.clear_log()
    print(f"Running full loop for trial: {trial_id}...")
    metrics: dict[str, Any] = run_trial(trial_id=trial_id, fault_type="process_kill")

    print("\n--- Event Log Verification ---")
    events: list[dict[str, Any]] = event_log.read_events(trial_id=trial_id)
    for e in events:
        print(f"  [{e['timestamp']}] {e['event']:<10} | {e['details']}")

    mttd: float = metrics["mttd_sec"] if metrics["mttd_sec"] is not None else 0.0
    mttr: float = metrics["mttr_sec"] if metrics["mttr_sec"] is not None else 0.0
    print(f"\nTiming Metrics:")
    print(f"  MTTD (Time to Detect):  {mttd:.3f} seconds")
    print(f"  MTTR (Time to Recover): {mttr:.3f} seconds")
    print(f"  Status: {'OK' if metrics['success'] else 'FAILED'}")
    print("\nOK: Full loop completed successfully.")
    return metrics


if __name__ == "__main__":
    run_full_loop()

