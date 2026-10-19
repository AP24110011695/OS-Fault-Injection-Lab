# Product Requirements Document — OS Fault Injection Lab

## Problem Statement

Operating systems must tolerate faults: processes crash, memory runs out, CPUs saturate.
Students learn these concepts from textbooks but rarely experience them firsthand.
This project creates a safe, repeatable environment where faults are **deliberately injected**
into a Linux system, the system's response is **monitored and measured**, and **automatic recovery**
is attempted — all inside a disposable Docker container so nothing on the host is ever at risk.

The builder is a B.Tech CSE student who must understand and explain every component in a viva.
Clarity and simplicity are requirements, not nice-to-haves.

---

## Goals

1. Build a fault-injection framework that runs entirely inside Docker on Linux.
2. Implement exactly three fault types: process kill, memory pressure, CPU hog.
3. For each fault, implement detection and automatic recovery.
4. Measure **MTTD** (mean time to detect) and **MTTR** (mean time to recover) across multiple trials.
5. Produce clean charts and a summary comparing fault types.
6. Keep the codebase small enough that a student can read every line and explain it.

## Non-Goals

- No Kubernetes, Chaos Mesh, eBPF, CRIU, ML/RL, custom kernels, or Grafana.
- No web dashboard or interactive GUI.
- No fault types beyond the three listed.
- No libraries beyond the documented stack (psutil, stress-ng, matplotlib, standard library).
- No host-level changes; everything runs inside the container.

---

## The Three Faults

### 1. Process Kill

| Aspect        | Detail |
|---------------|--------|
| What breaks   | A running target process is killed with `SIGKILL` (`os.kill(pid, 9)`). |
| Why it matters | Simulates an unexpected crash — the most common real-world failure mode. |
| Detection     | Monitor checks if the target PID is alive (via `psutil.pid_exists` or heartbeat absence). |
| Recovery      | Supervisor restarts the target process, with retries and cooldown. |
| Learning goal | Signals, PID lifecycle, process supervision, zombie/orphan awareness. |

### 2. Memory Pressure

| Aspect        | Detail |
|---------------|--------|
| What breaks   | A memory-hungry workload is launched inside a cgroup with a hard memory limit, forcing pressure and possible OOM kills. The memory hog runs inside the limited cgroup; the target process runs outside it so that only the hog is OOM-killed directly. |
| Why it matters | Memory exhaustion is a leading cause of degraded or crashed services. |
| Detection     | Monitor reads `memory.current` and `memory.max` from the cgroup filesystem and computes `current/max` as a ratio. If this ratio exceeds `MEMORY_THRESHOLD_PERCENT` for N consecutive polls, fault is detected. `psutil.virtual_memory()` is **not** used for this fault because it reads the whole-VM memory, which is unaware of the cgroup limit. OOM kills are observed by reading the `oom_kill` counter from the cgroup's `memory.events` file. |
| Recovery      | Kill the memory-hog process (if still alive); if the hog was OOM-killed, verify it is dead. Restart the target if it was affected. Document OOM killer behavior observed via `memory.events`. |
| Learning goal | Virtual memory, cgroups v2 memory limits, OOM killer, `memory.current`/`memory.max`/`memory.events`, `/proc/meminfo`. |

### 3. CPU Hog

| Aspect        | Detail |
|---------------|--------|
| What breaks   | `stress-ng --cpu` saturates all available CPU, starving the target process. |
| Why it matters | CPU starvation causes latency spikes and service unresponsiveness. |
| Detection     | Monitor reads CPU usage via `psutil.cpu_percent()` and checks against a threshold (e.g., >90% sustained). |
| Recovery      | Kill the `stress-ng` process; optionally apply CPU cgroup throttling. |
| Learning goal | CPU scheduling, nice/priority, cgroups CPU controller, load average vs. utilization. |

---

## Success Metrics

| Metric            | Definition | Target |
|-------------------|-----------|--------|
| MTTD              | `timestamp(DETECTED) - timestamp(INJECTED)` | Reported per trial and as a mean per fault type. |
| MTTR              | `timestamp(RECOVERED) - timestamp(INJECTED)` | Reported per trial and as a mean per fault type. |
| Success rate      | `trials where RECOVERED / total trials` | ≥ 90% for process kill and CPU hog; memory pressure may be lower due to OOM unpredictability — document why. |
| Trial count       | Number of trials per fault type | 10–20 per fault type. |
| Reproducibility   | Same command produces consistent results across runs | Variance in MTTD/MTTR should be explainable. |

---

## User Flow

The user experience is a single command:

```
docker compose up --build
```

Or, for a specific fault:

```
docker compose run lab python -m experiment.runner --fault process_kill --trials 15
```

**What happens:**
1. Docker builds the container with all dependencies.
2. The experiment runner starts.
3. For each trial: target starts → fault injected → monitor detects → recovery acts → metrics logged.
4. After all trials: results CSV is written, charts are generated, summary is printed to the terminal.
5. Container cleans up after itself.

**What the user sees at the end:**
- A results CSV file with per-trial data.
- Matplotlib charts: MTTD distribution, MTTR distribution, success rate bar chart.
- A text summary in the terminal.

---

## Learning Goals per Fault

### Process Kill
- How Unix signals work (`SIGKILL` vs `SIGTERM`).
- What a PID is and how the OS tracks processes.
- What happens to child processes when a parent dies.
- How process supervisors (like systemd) detect and restart crashed services.
- How to read `/proc/<pid>/status`.

### Memory Pressure
- How Linux virtual memory works (pages, swap, overcommit).
- What cgroups are and how `memory.max` enforces limits.
- How the OOM killer selects victims (`oom_score_adj`).
- How to read cgroup files: `memory.current`, `memory.max`, `memory.events` (oom_kill counter).
- Why `psutil.virtual_memory()` cannot see cgroup limits and why cgroup-level metrics are needed instead.

### CPU Hog
- How the Linux scheduler allocates CPU time (CFS basics).
- What load average means vs. CPU percentage.
- How cgroups `cpu.max` throttles processes.
- How `stress-ng` works internally (spawning worker threads).
- Why a single 100%-CPU process does not necessarily freeze the system.

---

## Constraints

- All code is Python. No C, C++, Bash scripts for core logic (shell only for setup/convenience).
- All experiments run inside Docker. Nothing modifies the host.
- The codebase must be small: aim for under 1500 lines of Python total.
- Every module must be independently runnable and testable.
- The shared event log is the only communication mechanism between components.
