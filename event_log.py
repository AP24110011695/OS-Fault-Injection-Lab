import json
from datetime import datetime
from pathlib import Path
from typing import Any

import config


def log_event(
    trial_id: str,
    fault_type: str,
    event: str,
    details: str = "",
    log_path: Path | str | None = None,
) -> dict[str, str]:
    path: Path = Path(log_path or config.EVENT_LOG_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)

    entry: dict[str, str] = {
        "timestamp": datetime.now().isoformat(),
        "trial_id": trial_id,
        "fault_type": fault_type,
        "event": event,
        "details": details,
    }

    # Append mode with immediate flush guarantees persistence even during crashes
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
        f.flush()

    return entry


def read_events(
    trial_id: str | None = None,
    fault_type: str | None = None,
    log_path: Path | str | None = None,
) -> list[dict[str, Any]]:
    path: Path = Path(log_path or config.EVENT_LOG_PATH)
    if not path.exists():
        return []

    events: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            stripped: str = line.strip()
            if not stripped:
                continue
            item: dict[str, Any] = json.loads(stripped)
            if trial_id is not None and item.get("trial_id") != trial_id:
                continue
            if fault_type is not None and item.get("fault_type") != fault_type:
                continue
            events.append(item)

    return events


def clear_log(log_path: Path | str | None = None) -> None:
    path: Path = Path(log_path or config.EVENT_LOG_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.truncate(0)


if __name__ == "__main__":
    print("Testing event_log module...")
    clear_log()

    # Write sample events across two trials
    log_event("test_001", "process_kill", "STARTED", "Target process started")
    log_event("test_001", "process_kill", "INJECTED", "SIGKILL sent to PID 101")
    log_event("test_001", "process_kill", "DETECTED", "PID 101 no longer exists")
    log_event("test_001", "process_kill", "RECOVERED", "Target restarted with PID 102")
    log_event("test_002", "cpu_hog", "STARTED", "Target process started")
    log_event("test_002", "cpu_hog", "INJECTED", "stress-ng CPU load started")

    all_events: list[dict[str, Any]] = read_events()
    print(f"Total events logged: {len(all_events)}")
    for e in all_events:
        print(f"  [{e['timestamp']}] {e['trial_id']} | {e['fault_type']} | {e['event']} | {e['details']}")

    # Filtered read
    filtered: list[dict[str, Any]] = read_events(trial_id="test_001")
    print(f"\nFiltered events for trial 'test_001': {len(filtered)}")
    assert len(filtered) == 4, f"Expected 4 events for test_001, got {len(filtered)}"

    # Clear confirmation
    clear_log()
    remaining: list[dict[str, Any]] = read_events()
    print(f"\nEvents after clear_log(): {len(remaining)}")
    assert len(remaining) == 0, f"Expected 0 events after clear, got {len(remaining)}"

    print("OK: event_log module verified successfully.")
