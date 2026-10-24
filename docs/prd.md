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
2. Implement seven fault types: process kill, memory pressure, CPU hog, process hang, disk full, fd exhaustion, zombie leak.
3. For each fault, implement detection and automatic recovery.
4. Measure **MTTD** (mean time to detect) and **MTTR** (mean time to recover) across multiple trials.
5. Produce clean charts and a summary comparing fault types.
6. Keep the codebase small enough that a student can read every line and explain it.

## Non-Goals

- No network faults (latency, packet loss, partitioning), kernel/driver faults, Kubernetes, Chaos Mesh, eBPF, CRIU, ML/RL, custom kernels, or Grafana.
- No web dashboard or interactive GUI.
- No fault types beyond the seven listed.
- No libraries beyond the documented stack (psutil, stress-ng, matplotlib, standard library).
- No host-level changes; everything runs inside the container.

---

## The Seven Faults

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

### 4. Process Hang

| Aspect        | Detail |
|---------------|--------|
| What breaks   | The target process is frozen with `SIGSTOP`: it stays alive but stops executing and stops producing heartbeats. |
| Why it matters | Real services hang (deadlocks, blocked I/O) while still passing liveness checks — "alive" is not the same as "healthy". |
| Detection     | Heartbeat staleness: the monitor checks the target's heartbeat file and detects when no fresh timestamp has been written within `HEARTBEAT_TIMEOUT_SEC`. A PID liveness check is deliberately **not** used — the PID is still alive, and that is the lesson of this fault. |
| Recovery      | Two strategies are implemented and compared: **resume** (`SIGCONT`, verify heartbeats resume) and **restart** (`SIGKILL` + supervisor restart). `RECOVERED` is logged only after a fresh heartbeat is observed. MTTR is compared per strategy. |
| Learning goal | Process states (running vs stopped), alive vs healthy, `SIGSTOP`/`SIGCONT`, heartbeat-based health checks. |

### 5. Disk Full

| Aspect        | Detail |
|---------------|--------|
| What breaks   | A small size-capped tmpfs (`DISK_FAULT_SIZE_MB`) is mounted inside the container and a writer process fills it until the OS returns `ENOSPC`. Before writing anything, the injector verifies via `/proc/mounts` that the path is really the tmpfs mountpoint; if the mount fails, the trial aborts. The container's normal filesystem is never written to. |
| Why it matters | Full disks are one of the most common production failures; log growth and temp files are classic culprits. |
| Detection     | `psutil.disk_usage(mount_path).percent` above `DISK_THRESHOLD_PERCENT` for N consecutive polls. |
| Recovery      | Kill the writer, delete its files, verify usage drops below the threshold, then unmount the tmpfs in cleanup. |
| Learning goal | Filesystems and mounts, tmpfs, `ENOSPC`, `df` vs `du`. |

### 6. FD Exhaustion

| Aspect        | Detail |
|---------------|--------|
| What breaks   | A leaker process (the faulty service) lowers **its own** limit with `resource.setrlimit(RLIMIT_NOFILE, FD_LIMIT)` and keeps opening files until it hits `EMFILE` (it handles the error and keeps running). The limit applies only to that process, never to the system. |
| Why it matters | File-descriptor leaks are a classic slow-burn failure: the service works fine until it suddenly cannot open files or accept connections. |
| Detection     | The leaker's open file count (`psutil.Process.num_fds()`) divided by its `RLIMIT_NOFILE` limit, above `FD_THRESHOLD_PERCENT` for N consecutive polls. |
| Recovery      | Kill the leaking process, start a fresh clean instance, verify its fd count is low, then log `RECOVERED`. |
| Learning goal | File descriptor table, `ulimit`/`RLIMIT_NOFILE`, `/proc/<pid>/fd`, `EMFILE`. |

### 7. Zombie Leak

| Aspect        | Detail |
|---------------|--------|
| What breaks   | A parent process spawns short-lived children that exit immediately and **never reaps them** (it never calls `wait`), so zombie processes pile up. The total is capped at `ZOMBIE_LEAK_MAX_CHILDREN` and children spawn at a controlled rate so the PID table is never at risk. |
| Why it matters | Zombie accumulation signals a broken parent; in real systems it exhausts the process table and breaks process management. |
| Detection     | Number of zombie children of the leaker parent (`psutil` status `STATUS_ZOMBIE`) above `ZOMBIE_THRESHOLD` for N consecutive polls. Only the leaker's children are counted so other processes cannot cause false alarms. |
| Recovery      | Kill the parent. Orphaned zombies are adopted by PID 1 — in this container the Python runner, which may not reap them — so recovery verifies the zombies are really gone before logging `RECOVERED`. |
| Learning goal | Zombies vs orphans, reparenting to PID 1, why init processes reap children. |

---

## Success Metrics

| Metric            | Definition | Target |
|-------------------|-----------|--------|
| MTTD              | `timestamp(DETECTED) - timestamp(INJECTED)` | Reported per trial and as a mean per fault type. |
| MTTR              | `timestamp(RECOVERED) - timestamp(INJECTED)` | Reported per trial and as a mean per fault type. |
| Success rate      | `trials where RECOVERED / total trials` | ≥ 90% per fault type; memory pressure may be lower due to OOM unpredictability — document why. |
| Strategy comparison | MTTR of the "resume" vs "restart" recovery strategies for process hang | Reported as a mean per strategy; document which recovers faster and why. |
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

### Process Hang
- What process states exist (running, sleeping, stopped, zombie) and how `SIGSTOP`/`SIGCONT` move a process between them.
- Why "the process is alive" and "the process is healthy" are different questions, and why liveness checks miss hangs.
- How heartbeat-based health checks work and how the timeout trades detection speed against false positives.
- Why recovery must be verified (a fresh heartbeat) before declaring success.

### Disk Full
- What filesystems and mount points are, and how mounting works in Linux.
- What tmpfs is (RAM-backed filesystem) and why it makes disk-fault injection safe and disposable.
- What `ENOSPC` is and how the OS reports "no space left on device".
- What `df` and `du` measure and why they can disagree.

### FD Exhaustion
- What a file descriptor is and how each process owns an fd table.
- What `ulimit`/`RLIMIT_NOFILE` control and that rlimits are per-process and inherited, not system-wide.
- How to inspect open fds via `psutil` and `/proc/<pid>/fd`.
- What `EMFILE` means and why leaking services fail slowly, then suddenly.

### Zombie Leak
- What a zombie process is (terminated but not reaped) and how it differs from an orphan.
- How reparenting to PID 1 works when a parent dies.
- Why init processes must reap children, and what accumulates when they do not.
- How to count zombies precisely (only the target parent's children) to avoid false alarms.

---

## Constraints

- All code is Python. No C, C++, Bash scripts for core logic (shell only for setup/convenience).
- All experiments run inside Docker. Nothing modifies the host.
- The codebase must stay small: under 3300 lines of Python excluding tests; each new fault module must stay small.
- Every module must be independently runnable and testable.
- The shared event log is the only communication mechanism between components.
