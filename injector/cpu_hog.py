import subprocess
import time
from typing import Any

import config
import event_log


def inject(
    trial_id: str,
    workers: int = config.STRESS_NG_CPU_WORKERS,
    timeout_sec: int = config.STRESS_NG_TIMEOUT_SEC,
) -> subprocess.Popen[Any]:
    cmd: list[str] = [
        "stress-ng",
        "--cpu",
        str(workers),
        "--timeout",
        f"{timeout_sec}s",
    ]
    proc: subprocess.Popen[Any] = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    event_log.log_event(
        trial_id=trial_id,
        fault_type="cpu_hog",
        event="INJECTED",
        details=f"stress-ng spawned with {workers} workers (PID {proc.pid}, timeout {timeout_sec}s)",
    )
    return proc


if __name__ == "__main__":
    import psutil

    print("Testing cpu_hog injector...")
    trial_id: str = "cpu_hog_test"
    event_log.clear_log()

    proc = inject(trial_id=trial_id, workers=2, timeout_sec=5)
    print(f"stress-ng started with PID {proc.pid}")
    time.sleep(1.0)
    cpu_now = psutil.cpu_percent(interval=0.5)
    print(f"Current CPU usage: {cpu_now:.1f}%")

    # Terminate process and children
    try:
        parent = psutil.Process(proc.pid)
        for child in parent.children(recursive=True):
            child.kill()
        parent.kill()
        proc.wait(timeout=1.0)
    except Exception:
        pass

    events = event_log.read_events(trial_id=trial_id)
    for e in events:
        print(f"  [{e['timestamp']}] {e['event']}: {e['details']}")

    assert proc.poll() is not None, "stress-ng process should be terminated"
    print("OK: cpu_hog injector test completed.")
