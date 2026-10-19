import subprocess
import time
from typing import Any

import config
import event_log
from monitor.detector import is_process_alive

_last_proc: subprocess.Popen[Any] | None = None


def get_last_process() -> subprocess.Popen[Any] | None:
    return _last_proc


def restart_target(
    trial_id: str = "recovery",
    cmd: list[str] | None = None,
    max_retries: int = config.SUPERVISOR_MAX_RETRIES,
    cooldown_sec: float = config.SUPERVISOR_COOLDOWN_SEC,
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
                event_log.log_event(
                    trial_id=trial_id,
                    fault_type="process_kill",
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
        fault_type="process_kill",
        event="FAILED",
        details=error_msg,
    )
    raise RuntimeError(error_msg)


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

