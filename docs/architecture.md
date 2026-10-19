# Architecture — OS Fault Injection Lab

## Folder Structure

```
OS Fault Injection Lab/
├── docs/                    # All documentation (you are here)
│   ├── prd.md
│   ├── architecture.md
│   ├── rules.md
│   ├── design.md
│   ├── tasks.md
│   └── memory.md
├── injector/                # Fault injection modules
│   ├── __init__.py
│   ├── process_kill.py      # Kill target with SIGKILL
│   ├── memory_pressure.py   # Launch memory hog inside cgroup
│   └── cpu_hog.py           # Launch stress-ng CPU load
├── monitor/                 # System health monitoring + detection
│   ├── __init__.py
│   ├── monitor.py           # Polling loop: reads psutil, checks thresholds
│   └── detector.py          # Threshold logic, anomaly detection
├── recovery/                # Self-healing actions
│   ├── __init__.py
│   ├── supervisor.py        # Restart crashed processes (retry + cooldown)
│   └── resource_recovery.py # Kill hogs, release resources
├── experiment/              # Trial orchestration + metrics
│   ├── __init__.py
│   ├── runner.py            # Run N trials, coordinate inject→detect→recover
│   ├── metrics.py           # MTTD/MTTR calculation from event log
│   └── results.py           # Write results CSV, generate charts
├── target/                  # The app that gets broken
│   ├── __init__.py
│   └── heartbeat_app.py     # Simple loop: prints heartbeat, does light work
├── config.py                # Central configuration (all constants in one place)
├── event_log.py             # Shared event log: write/read CSV or JSONL
├── scripts/
│   └── safety_check.py      # Pre-run checks: are we in Docker? cgroups available?
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── results/                 # Output directory (gitignored except .gitkeep)
│   └── .gitkeep
└── README.md
```

---

## Module Responsibilities

### `config.py` — Central Configuration

Single source of truth for all tunables. No magic numbers anywhere else.

```python
# Examples of what lives here:
MONITOR_POLL_INTERVAL_SEC = 0.5
CPU_THRESHOLD_PERCENT = 90.0
MEMORY_THRESHOLD_PERCENT = 90.0
HEARTBEAT_TIMEOUT_SEC = 3.0
SUPERVISOR_MAX_RETRIES = 3
SUPERVISOR_COOLDOWN_SEC = 2.0
DEFAULT_TRIAL_COUNT = 15
EVENT_LOG_PATH = "results/event_log.jsonl"
RESULTS_CSV_PATH = "results/results.csv"
CGROUP_MEMORY_LIMIT_MB = 64
STRESS_NG_CPU_WORKERS = os.cpu_count()  # default: all available CPUs
TARGET_CMD = ["python", "-m", "target.heartbeat_app"]
```

### `event_log.py` — Shared Event Log

The **only** communication channel between components. Every component writes events
to and reads events from one JSONL file.

**Event format (one JSON object per line):**

```json
{
  "timestamp": "2026-10-19T23:40:12.345678",
  "trial_id": "process_kill_007",
  "fault_type": "process_kill",
  "event": "INJECTED",
  "details": "Sent SIGKILL to PID 1234"
}
```

| Field       | Type   | Values |
|-------------|--------|--------|
| `timestamp` | ISO 8601 string | `datetime.now().isoformat()` |
| `trial_id`  | string | `{fault_type}_{zero-padded number}`, e.g. `memory_pressure_003` |
| `fault_type`| string | `process_kill`, `memory_pressure`, `cpu_hog` |
| `event`     | string | `INJECTED`, `DETECTED`, `RECOVERED`, `FAILED`, `STARTED`, `CLEANUP` |
| `details`   | string | Human-readable description of what happened |

**API (functions in `event_log.py`):**
- `log_event(trial_id, fault_type, event, details)` — append one line to the log.
- `read_events(trial_id=None, fault_type=None)` — read and filter events, return list of dicts.
- `clear_log()` — wipe the log (used between experiment runs, not between trials).

### `target/heartbeat_app.py` — The Victim

A simple Python process that:
1. Prints a heartbeat message every 1 second.
2. Optionally writes heartbeat timestamps to a file or stdout.
3. Does light busywork (e.g., appends to a list) so it consumes real memory.
4. Exits cleanly on `SIGTERM`, dies immediately on `SIGKILL`.

This is the process that gets killed, starved, or OOM-killed depending on the fault type.

### `injector/` — Fault Injection

Each injector module exposes one function: `inject(target_pid, trial_id) -> None`.

| Module               | What it does |
|----------------------|-------------|
| `process_kill.py`    | Calls `os.kill(target_pid, signal.SIGKILL)`. Logs `INJECTED`. |
| `memory_pressure.py` | Starts a memory-hungry child process inside a cgroup with a hard memory limit. Logs `INJECTED`. |
| `cpu_hog.py`         | Starts `stress-ng --cpu N` as a subprocess. Logs `INJECTED`. |

### `monitor/` — Monitoring + Detection

`monitor.py` runs a polling loop at `MONITOR_POLL_INTERVAL_SEC`:
- Reads CPU via `psutil.cpu_percent(interval=None)` (non-blocking).
- For memory pressure: reads `memory.current` and `memory.max` from the cgroup filesystem and computes the ratio. Does **not** use `psutil.virtual_memory()` for this fault (it sees the whole VM, not the cgroup limit). Also reads the `oom_kill` counter from `memory.events` to detect OOM kills.
- Checks target process liveness via `psutil.pid_exists(pid)` + heartbeat staleness.
- Passes readings to `detector.py`.

`detector.py` applies threshold checks:
- **Process kill**: target PID gone OR heartbeat not updated within timeout → `DETECTED`.
- **Memory pressure**: cgroup `memory.current / memory.max` ratio > threshold for N consecutive polls, OR `oom_kill` counter incremented → `DETECTED`.
- **CPU hog**: CPU percent > threshold for N consecutive polls → `DETECTED`.

On detection, `log_event(... "DETECTED" ...)` is called.

### `recovery/` — Self-Healing

`supervisor.py`:
- Restarts the target process.
- Retries up to `SUPERVISOR_MAX_RETRIES` with `SUPERVISOR_COOLDOWN_SEC` between attempts.
- Verifies the new process is alive before logging `RECOVERED`.

`resource_recovery.py`:
- Kills `stress-ng` or memory-hog processes by PID or name.
- Verifies resource levels return to normal.
- Logs `RECOVERED`.

### `experiment/runner.py` — Trial Orchestration

For each trial:
1. Log `STARTED`.
2. Start target process.
3. Wait for target to stabilize (e.g., 2 seconds).
4. Call the appropriate injector.
5. Start (or signal) the monitor to begin detection.
6. Wait for `DETECTED` event.
7. Trigger the appropriate recovery action.
8. Wait for `RECOVERED` event.
9. Log `CLEANUP`, kill any leftover processes, reset state.
10. Brief pause before next trial.

After all trials: call `metrics.py` to compute MTTD/MTTR, call `results.py` to write CSV and charts.

### `experiment/metrics.py` — MTTD/MTTR Calculation

- Reads the event log.
- Groups events by `trial_id`.
- For each trial: `MTTD = DETECTED.timestamp - INJECTED.timestamp`.
- For each trial: `MTTR = RECOVERED.timestamp - INJECTED.timestamp`.
- Computes mean, median, min, max for each fault type.
- Returns structured data for `results.py`.

### `experiment/results.py` — Output

- Writes a results CSV with columns: `trial_id, fault_type, mttd_sec, mttr_sec, success`.
- Generates matplotlib charts following `design.md`.
- Prints a text summary table to stdout.

---

## Data Flow — The Core Loop

```
┌─────────────────────────────────────────────────────────────────────┐
│                        EXPERIMENT RUNNER                            │
│                                                                     │
│   ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐     │
│   │  START    │───>│  INJECT  │───>│  DETECT  │───>│  RECOVER │     │
│   │  target   │    │  fault   │    │  fault   │    │  system  │     │
│   └──────────┘    └────┬─────┘    └────┬─────┘    └────┬─────┘     │
│                        │               │               │            │
│                        v               v               v            │
│               ┌────────────────────────────────────────────┐        │
│               │         SHARED EVENT LOG (JSONL)           │        │
│               │                                            │        │
│               │  STARTED → INJECTED → DETECTED → RECOVERED │       │
│               └────────────────────────────────────────────┘        │
│                                                                     │
│   After all trials:                                                 │
│   ┌──────────┐    ┌──────────┐    ┌──────────┐                     │
│   │  METRICS │───>│  RESULTS │───>│  CHARTS  │                     │
│   │  calc    │    │  CSV     │    │  PNG     │                      │
│   └──────────┘    └──────────┘    └──────────┘                     │
└─────────────────────────────────────────────────────────────────────┘
```

**Sequence for one trial (process kill example):**

```
Time   Component           Action                         Event Logged
─────  ──────────────────  ─────────────────────────────  ─────────────
t0     runner              Start heartbeat_app             STARTED
t1     runner              Wait for stabilization          —
t2     injector            os.kill(pid, SIGKILL)           INJECTED
t3     monitor             psutil.pid_exists → False       DETECTED
t4     recovery            subprocess.Popen(target_cmd)    RECOVERED
t5     runner              Cleanup, pause                  CLEANUP
       metrics             MTTD = t3 - t2                  —
       metrics             MTTR = t4 - t2                  —
```

---

## Docker and cgroups

### Docker

- **Purpose:** Isolation. All faults happen inside the container. The host is never affected.
- **Base image:** `python:3.11-slim` (small, has everything we need).
- **Installed inside:** `psutil`, `stress-ng`, `matplotlib`.
- **Volumes:** `./results` is mounted so output files persist after the container stops.
- **Privileges:** The container needs `--privileged` or `SYS_ADMIN` capability to manipulate cgroups inside the container. This is documented and justified.

### cgroups (v2)

- Used for the **memory pressure** fault: create a cgroup with `memory.max` set to a low value (e.g., 64 MB), then run the memory-hog process inside it.
- Used for the **CPU hog** fault: optionally set `cpu.max` to throttle recovery.
- Managed via writing to `/sys/fs/cgroup/` paths inside the container.
- Cleaned up after every trial (remove the cgroup directory).

---

## Safety Constraints

1. **Container-only execution.**
   - `scripts/safety_check.py` verifies we are running inside Docker before any fault is injected
     (checks `/.dockerenv` or cgroup namespace).
   - If the check fails, the program exits immediately with a clear error message.

2. **Resource caps.**
   - Memory cgroups are always set with a hard limit.
   - CPU stress is always launched with a time limit (`--timeout`).
   - The experiment runner enforces a maximum trial duration; if a trial exceeds it, everything is killed.

3. **Cleanup after every trial.**
   - All child processes are killed (using `psutil.Process.children(recursive=True)`).
   - cgroup directories are removed.
   - Temp files are deleted.
   - The runner verifies cleanup succeeded before starting the next trial.

4. **No host modification.**
   - No bind mounts to sensitive host paths.
   - No network-based faults.
   - No kernel module loading.

5. **Graceful shutdown.**
   - `SIGINT` (Ctrl+C) during an experiment triggers cleanup of all child processes and cgroups
     before exiting.

---

## File-Level Dependency Map

```
config.py ──────────────── used by everything
event_log.py ──────────── used by injector, monitor, recovery, experiment
target/heartbeat_app.py ── standalone (no imports from project)
injector/* ────────────── imports: config, event_log, os, signal, subprocess
monitor/* ─────────────── imports: config, event_log, psutil
recovery/* ────────────── imports: config, event_log, psutil, subprocess
experiment/runner.py ──── imports: config, event_log, injector, monitor, recovery, target
experiment/metrics.py ─── imports: config, event_log
experiment/results.py ─── imports: config, metrics, matplotlib
scripts/safety_check.py ─ imports: os, sys (standalone)
```

No circular dependencies. The dependency graph is a DAG rooted at `experiment/runner.py`.
