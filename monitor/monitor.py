import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import psutil

import config
import event_log
from injector.process_kill import inject
from monitor.detector import (
    detect_cpu_hog,
    detect_memory_pressure,
    detect_process_death,
    is_process_alive,
)


def poll_system_metrics() -> dict[str, float]:
    return {
        "cpu_percent": psutil.cpu_percent(interval=None),
        "memory_percent": psutil.virtual_memory().percent,
    }


def monitor_process(
    pid: int,
    trial_id: str,
    proc: subprocess.Popen[Any] | None = None,
    cgroup_path: Path | None = None,
    fault_type: str = "process_kill",
    poll_interval_sec: float = config.MONITOR_POLL_INTERVAL_SEC,
    stop_event: threading.Event | None = None,
    max_duration_sec: float = config.MAX_TRIAL_DURATION_SEC,
    verbose: bool = True,
) -> bool:
    # Prime psutil.cpu_percent so the first interval reading within the loop is not 0.0
    psutil.cpu_percent(interval=None)

    start_time: float = time.time()
    tick: int = 0
    consecutive_breaches: int = 0

    while True:
        if stop_event is not None and stop_event.is_set():
            return False

        elapsed: float = time.time() - start_time
        if elapsed > max_duration_sec:
            print(f"[monitor] Timeout reached ({max_duration_sec}s) without detecting fault.")
            return False

        metrics = poll_system_metrics()
        alive: bool = is_process_alive(pid, proc=proc)

        if verbose:
            status_str: str = "alive" if alive else "dead"
            print(
                f"[monitor] +{elapsed:4.1f}s | PID {pid} is {status_str} | "
                f"CPU: {metrics['cpu_percent']:4.1f}% | Mem: {metrics['memory_percent']:4.1f}%"
            )

        if fault_type == "process_kill":
            if not alive:
                detect_process_death(pid, trial_id, proc=proc)
                return True
        elif fault_type == "memory_pressure":
            if cgroup_path is not None and cgroup_path.exists():
                detected, consecutive_breaches = detect_memory_pressure(
                    cgroup_path=cgroup_path,
                    trial_id=trial_id,
                    consecutive_breaches=consecutive_breaches,
                )
                if detected:
                    return True
        elif fault_type == "cpu_hog":
            detected, consecutive_breaches = detect_cpu_hog(
                cpu_percent=metrics["cpu_percent"],
                trial_id=trial_id,
                consecutive_breaches=consecutive_breaches,
            )
            if detected:
                return True

        tick += 1
        if stop_event is not None:
            if stop_event.wait(poll_interval_sec):
                return False
        else:
            time.sleep(poll_interval_sec)


if __name__ == "__main__":
    trial_id: str = "monitor_test_001"
    event_log.clear_log()

    if len(sys.argv) > 1:
        target_pid = int(sys.argv[1])
        print(f"Monitoring external PID {target_pid}...")
        detected = monitor_process(target_pid, trial_id)
        print(f"Monitoring ended. Detection status: {detected}")
    else:
        print("Starting target process for monitoring demonstration...")
        proc = subprocess.Popen(config.TARGET_CMD)
        event_log.log_event(
            trial_id=trial_id,
            fault_type="process_kill",
            event="STARTED",
            details=f"Target process started with PID {proc.pid}",
        )

        def delayed_kill() -> None:
            time.sleep(2.0)
            print(f"\n[injector] Injecting SIGKILL into PID {proc.pid}...")
            inject(proc.pid, trial_id)

        # Inject fault asynchronously while monitor polls
        injector_thread = threading.Thread(target=delayed_kill, daemon=True)
        injector_thread.start()

        detected = monitor_process(proc.pid, trial_id, proc=proc)
        injector_thread.join()

        # Clean up child process
        if proc.poll() is None:
            proc.kill()
            proc.wait()

        print("\n--- Event Log Verification ---")
        events = event_log.read_events(trial_id=trial_id)
        for e in events:
            print(f"  [{e['timestamp']}] {e['event']}: {e['details']}")

        injected = next((e for e in events if e["event"] == "INJECTED"), None)
        detected_event = next((e for e in events if e["event"] == "DETECTED"), None)

        assert injected is not None, "Missing INJECTED event in log"
        assert detected_event is not None, "Missing DETECTED event in log"

        t_injected = datetime.fromisoformat(injected["timestamp"])
        t_detected = datetime.fromisoformat(detected_event["timestamp"])
        mttd = (t_detected - t_injected).total_seconds()

        print(f"\nMTTD (Time to Detect): {mttd:.3f} seconds")
        assert mttd >= 0.0, "MTTD must be non-negative"
        print("OK: Monitor and detector verified successfully.")
