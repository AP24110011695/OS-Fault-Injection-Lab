# Architecture — OS Fault Injection Lab

## Folder Structure

```
OS Fault Injection Lab/
├── docs/                    # All documentation (you are here)
│   ├── images/              # Publication charts embedded in the README
│   ├── prd.md
│   ├── architecture.md
│   ├── rules.md
│   ├── design.md
│   ├── tasks.md
│   ├── memory.md
│   ├── process_kill_notes.md
│   ├── oom_killer_notes.md
│   ├── cpu_scheduling_notes.md
│   ├── process_hang_notes.md
│   ├── disk_full_notes.md
│   ├── fd_exhaustion_notes.md
│   └── zombie_leak_notes.md
├── injector/                # Fault injection modules
│   ├── __init__.py
│   ├── process_kill.py      # Kill target with SIGKILL
│   ├── memory_pressure.py   # Launch memory hog inside cgroup
│   ├── cpu_hog.py           # Launch stress-ng CPU load
│   ├── process_hang.py      # Freeze target with SIGSTOP
│   ├── disk_full.py         # Mount size-capped tmpfs, fill it to ENOSPC
│   ├── fd_exhaustion.py     # Lower own RLIMIT_NOFILE, leak fds to EMFILE
│   └── zombie_leak.py       # Parent that never reaps its exiting children
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
│   ├── safety_check.py      # Pre-run checks: Docker? cgroups? stress-ng? tmpfs mount?
│   └── demo.py              # One-command demo: 1 trial per fault group + charts
├── tests/                   # Unit tests (stdlib unittest, no external framework)
│   ├── test_event_log.py
│   ├── test_metrics.py
│   ├── test_detector.py
│   ├── test_supervisor.py
│   └── test_results.py
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── results/                 # Generated outputs (gitignored except .gitkeep):
│   └── .gitkeep             #   event_log.jsonl, results.csv, *.png, heartbeat.log
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

# Process hang (Phase 11)
HEARTBEAT_FILE_PATH = "results/heartbeat.log"  # target appends heartbeat timestamps here

# Disk full (Phase 12)
DISK_FAULT_SIZE_MB = 16               # size-capped tmpfs
DISK_MOUNT_PATH = "/tmp/fault_disk"   # tmpfs mountpoint inside the container
DISK_THRESHOLD_PERCENT = 90.0

# FD exhaustion (Phase 13)
FD_LIMIT = 256                        # leaker's own RLIMIT_NOFILE
FD_THRESHOLD_PERCENT = 90.0
FD_CLEAN_MAX_FDS = 20                 # fresh-instance verification bound

# Zombie leak (Phase 14)
ZOMBIE_LEAK_MAX_CHILDREN = 200        # hard cap on spawned children
ZOMBIE_THRESHOLD = 20
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
| `fault_type`| string | `process_kill`, `memory_pressure`, `cpu_hog`, `process_hang`, `disk_full`, `fd_exhaustion`, `zombie_leak` |
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
| `process_hang.py`    | Sends `SIGSTOP` to the target. Logs `INJECTED`. |
| `disk_full.py`       | Mounts a size-capped tmpfs at `DISK_MOUNT_PATH`, verifies it via `/proc/mounts`, then starts a writer that fills it to `ENOSPC`. Aborts the trial if the mount cannot be verified. Logs `INJECTED`. |
| `fd_exhaustion.py`   | Provides the faulty service: it lowers its own `RLIMIT_NOFILE` to `FD_LIMIT` at startup and, on `SIGUSR1`, opens `/dev/null` until `EMFILE` and keeps running. Logs `INJECTED`. |
| `zombie_leak.py`     | Provides the leaker parent which, on `SIGUSR1`, `os.fork()`s up to `ZOMBIE_LEAK_MAX_CHILDREN` short-lived children it never reaps. Logs `INJECTED`. |

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
- **Process hang**: target PID is alive but its heartbeat file has no fresh timestamp within `HEARTBEAT_TIMEOUT_SEC` → `DETECTED`. A liveness check would never fire here — the PID still exists; that is the point of the fault.
- **Disk full**: `psutil.disk_usage(DISK_MOUNT_PATH).percent` > `DISK_THRESHOLD_PERCENT` for N consecutive polls → `DETECTED`.
- **FD exhaustion**: leaker's `Process.num_fds()` / `RLIMIT_NOFILE` ratio > `FD_THRESHOLD_PERCENT` for N consecutive polls → `DETECTED`.
- **Zombie leak**: count of the leaker's own children in `STATUS_ZOMBIE` > `ZOMBIE_THRESHOLD` for N consecutive polls → `DETECTED`. Only the leaker's children are counted.

On detection, `log_event(... "DETECTED" ...)` is called.

### `recovery/` — Self-Healing

`supervisor.py` — recovers faults where a process must be resumed or (re)started:
- Restarts the target process (process_kill).
- Retries up to `SUPERVISOR_MAX_RETRIES` with `SUPERVISOR_COOLDOWN_SEC` between attempts.
- Verifies the new process is alive before logging `RECOVERED`.
- Applies the two process_hang strategies: "resume" (`SIGCONT`) and "restart" (`restart_target()`); `RECOVERED` is logged only after a fresh heartbeat is observed.
- Recovers fd_exhaustion: kills the leaker, starts a fresh clean instance, verifies its fd count is low.

`resource_recovery.py` — recovers resource-exhaustion faults:
- Kills `stress-ng` or memory-hog processes by PID or name.
- Verifies resource levels return to normal.
- Logs `RECOVERED`.
- Recovers disk_full: kills the writer, deletes its files, verifies usage drops below the threshold, unmounts the tmpfs in cleanup.
- Recovers zombie_leak: kills the unreaping parent, reaps orphaned zombies, verifies zero zombies remain.

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
- **tmpfs mounts (disk_full):** the size-capped tmpfs is mounted inside the container at `DISK_MOUNT_PATH`; privileged mode makes this possible. Nothing is ever mounted or written on the host.
- **PID 1 (zombie_leak):** with `docker compose run`, the Python runner is PID 1. Python does not automatically reap children adopted by PID 1, so zombie_leak recovery either reaps them explicitly (reusing `reap_zombie_children()`) or the compose file sets `init: true` so Docker's init reaps them. The choice is made in Phase 14 and recorded in `memory.md`.

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

6. **tmpfs-only disk fault.**
   - The disk_full fault writes only to the size-capped tmpfs mounted at `DISK_MOUNT_PATH`.
   - Before any write, the injector verifies via `/proc/mounts` that the path is really that tmpfs
     mountpoint. If the mount fails, the trial aborts — the writer never runs against the
     container's normal filesystem.
   - The tmpfs is unmounted and the mount directory removed after every trial, including on Ctrl+C.

7. **Per-process rlimit only.**
   - The fd_exhaustion leaker lowers `RLIMIT_NOFILE` only for its own process via
     `resource.setrlimit`. System-wide limits are never touched.

8. **Zombie cap.**
   - The zombie_leak parent spawns at most `ZOMBIE_LEAK_MAX_CHILDREN` children, at a controlled
     rate, so the container's process table is never at risk.

---

## File-Level Dependency Map

```
config.py ──────────────── used by everything
event_log.py ──────────── used by injector, monitor, recovery, experiment
target/heartbeat_app.py ── imports: config (writes heartbeat timestamps to HEARTBEAT_FILE_PATH)
injector/* ────────────── imports: config, event_log, os, signal, subprocess
monitor/* ─────────────── imports: config, event_log, psutil
recovery/* ────────────── imports: config, event_log, psutil, subprocess
experiment/runner.py ──── imports: config, event_log, injector, monitor, recovery, target
experiment/metrics.py ─── imports: config, event_log
experiment/results.py ─── imports: config, metrics, matplotlib
scripts/safety_check.py ─ imports: os, sys (standalone)
```

No circular dependencies. The dependency graph is a DAG rooted at `experiment/runner.py`.

---

## Fault Reference — All Seven Faults

How each fault is injected, detected, and recovered. Written for the teacher/reviewer.

| Fault | Injected by | Detected by | Recovered by |
|-------|-------------|-------------|--------------|
| `process_kill` | `os.kill(pid, SIGKILL)` on the target (`injector/process_kill.py`) | Target PID gone or zombie (`monitor/detector.py`) | Supervisor restart with retries + cooldown (`recovery/supervisor.py`) |
| `memory_pressure` | Memory hog inside a cgroup with hard `memory.max` limit, swap off (`injector/memory_pressure.py`) | cgroup `memory.current/memory.max` ratio over N polls, or `oom_kill` counter in `memory.events` | Kill hog, verify target health, remove cgroup (`recovery/resource_recovery.py`) |
| `cpu_hog` | `stress-ng --cpu N --timeout T` (`injector/cpu_hog.py`) | `psutil.cpu_percent()` ≥ threshold for N polls | Kill the stress-ng process tree, verify CPU drops below threshold (`recovery/resource_recovery.py`) |
| `process_hang` | `SIGSTOP` to the target (`injector/process_hang.py`) | Heartbeat staleness: no fresh heartbeat within `HEARTBEAT_TIMEOUT_SEC` (PID still alive) | Strategy "resume" (`SIGCONT`) or "restart" (supervisor); `RECOVERED` only after a fresh heartbeat (`recovery/supervisor.py`) |
| `disk_full` | Size-capped tmpfs mounted at `DISK_MOUNT_PATH`, writer fills it to `ENOSPC` (`injector/disk_full.py`) | `psutil.disk_usage(mount).percent` ≥ `DISK_THRESHOLD_PERCENT` for N polls | Kill writer, delete its files, verify usage drops, unmount tmpfs in cleanup (`recovery/resource_recovery.py`) |
| `fd_exhaustion` | Leaker lowers its own `RLIMIT_NOFILE` to `FD_LIMIT`, opens files until `EMFILE` (`injector/fd_exhaustion.py`) | `num_fds()` / `RLIMIT_NOFILE` ratio ≥ `FD_THRESHOLD_PERCENT` for N polls | Kill leaker, start a fresh clean instance, verify low fd count (`recovery/supervisor.py`) |
| `zombie_leak` | Parent spawns capped short-lived children it never reaps (`injector/zombie_leak.py`) | Leaker's own zombie children > `ZOMBIE_THRESHOLD` for N polls | Kill parent, reap orphaned zombies, verify zero zombies remain (`recovery/resource_recovery.py`) |
