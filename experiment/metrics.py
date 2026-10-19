import statistics
from datetime import datetime
from typing import Any

import event_log


def calculate_trial_metrics(
    trial_id: str,
    events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if events is None:
        events = event_log.read_events(trial_id=trial_id)
    fault_type: str = events[0]["fault_type"] if events else "unknown"

    injected = next((e for e in events if e["event"] == "INJECTED"), None)
    detected = next((e for e in events if e["event"] == "DETECTED"), None)
    recovered = next((e for e in events if e["event"] == "RECOVERED"), None)

    mttd_sec: float | None = None
    mttr_sec: float | None = None
    success: bool = False

    if injected is not None:
        t_injected = datetime.fromisoformat(injected["timestamp"])

        if detected is not None:
            t_detected = datetime.fromisoformat(detected["timestamp"])
            mttd_sec = max(0.0, (t_detected - t_injected).total_seconds())

        if recovered is not None:
            t_recovered = datetime.fromisoformat(recovered["timestamp"])
            mttr_sec = max(0.0, (t_recovered - t_injected).total_seconds())
            success = True

    return {
        "trial_id": trial_id,
        "fault_type": fault_type,
        "mttd_sec": mttd_sec,
        "mttr_sec": mttr_sec,
        "success": success,
    }


def compute_aggregates(trial_metrics: list[dict[str, Any]]) -> dict[str, Any]:
    if not trial_metrics:
        return {
            "count": 0,
            "success_count": 0,
            "success_rate": 0.0,
            "mttd_mean": 0.0,
            "mttd_median": 0.0,
            "mttd_min": 0.0,
            "mttd_max": 0.0,
            "mttr_mean": 0.0,
            "mttr_median": 0.0,
            "mttr_min": 0.0,
            "mttr_max": 0.0,
        }

    total: int = len(trial_metrics)
    successes: int = sum(1 for m in trial_metrics if m["success"])
    success_rate: float = (successes / total) * 100.0

    mttd_values = [m["mttd_sec"] for m in trial_metrics if m["mttd_sec"] is not None]
    mttr_values = [m["mttr_sec"] for m in trial_metrics if m["mttr_sec"] is not None]

    return {
        "count": total,
        "success_count": successes,
        "success_rate": success_rate,
        "mttd_mean": statistics.mean(mttd_values) if mttd_values else 0.0,
        "mttd_median": statistics.median(mttd_values) if mttd_values else 0.0,
        "mttd_min": min(mttd_values) if mttd_values else 0.0,
        "mttd_max": max(mttd_values) if mttd_values else 0.0,
        "mttr_mean": statistics.mean(mttr_values) if mttr_values else 0.0,
        "mttr_median": statistics.median(mttr_values) if mttr_values else 0.0,
        "mttr_min": min(mttr_values) if mttr_values else 0.0,
        "mttr_max": max(mttr_values) if mttr_values else 0.0,
    }
