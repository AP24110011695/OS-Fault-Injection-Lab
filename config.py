import os
from pathlib import Path

# Monitor settings
MONITOR_POLL_INTERVAL_SEC: float = 0.5
CPU_THRESHOLD_PERCENT: float = 90.0
MEMORY_THRESHOLD_PERCENT: float = 90.0
HEARTBEAT_TIMEOUT_SEC: float = 3.0
CONSECUTIVE_POLLS_THRESHOLD: int = 3

# Recovery supervisor settings
SUPERVISOR_MAX_RETRIES: int = 3
SUPERVISOR_COOLDOWN_SEC: float = 2.0

# Experiment runner settings
DEFAULT_TRIAL_COUNT: int = 15
MAX_TRIAL_DURATION_SEC: float = 30.0
RESULTS_DIR: Path = Path("results")
EVENT_LOG_PATH: Path = RESULTS_DIR / "event_log.jsonl"
RESULTS_CSV_PATH: Path = RESULTS_DIR / "results.csv"

# Fault injector parameters
CGROUP_MEMORY_LIMIT_MB: int = 64
STRESS_NG_CPU_WORKERS: int = os.cpu_count() or 2
STRESS_NG_TIMEOUT_SEC: int = int(MAX_TRIAL_DURATION_SEC) + 30
TARGET_CMD: list[str] = ["python", "-m", "target.heartbeat_app"]
INJECTION_JITTER_MIN_SEC: float = 0.0
INJECTION_JITTER_MAX_SEC: float = MONITOR_POLL_INTERVAL_SEC

