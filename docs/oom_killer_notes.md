# Learning Notes: Linux Cgroups v2 & OOM Killer Behavior

## 1. Overview & Context

In the OS Fault Injection Lab, **Phase 7** tests system resiliency under constrained memory conditions. Rather than exhausting the entire host or container memory (which could crash the system or container engine), we use **Linux cgroups v2** (control groups) to apply localized, deterministic resource constraints to a fault-generating process while leaving the target application intact.

---

## 2. Cgroups v2 Architecture & Memory Limits

In cgroups v2:
- **Hierarchical tree**: Every process belongs to a single cgroup in `/sys/fs/cgroup`.
- **Controllers**: Controllers (`memory`, `cpu`) are enabled on children by writing to `cgroup.subtree_control`.
- **"No Internal Processes" Rule**: A cgroup cannot host processes and distribute controllers to child cgroups simultaneously. Root processes (like PID 1) must be moved into a leaf cgroup (e.g., `/sys/fs/cgroup/init`) before child cgroups can activate the memory controller.
- **Per-trial Cgroup**: For each trial, we create `/sys/fs/cgroup/fault_{trial_id}`:
  - `memory.max`: Set to hard limit (`64MB` in bytes).
  - `memory.swap.max`: Set to `0`. Without this, anonymous pages would swap to disk rather than triggering an out-of-memory condition.

---

## 3. The `memory.events` Interface

Inside each cgroup directory, the kernel maintains an interface file called `memory.events`. It exposes flat key-value counters:

```
low 0
high 0
max 38
oom 1
oom_kill 1
oom_group_kill 0
```

### Counter Meanings:
- **`max`**: The count of memory allocation requests that breached `memory.max`. When positive, processes inside the cgroup were forced into memory reclamation or stalled.
- **`oom`**: The number of times the cgroup entered an out-of-memory state because memory reclamation failed to free enough pages.
- **`oom_kill`**: The number of processes terminated by the Linux OOM killer within this cgroup.
- **`oom_group_kill`**: Increments if `memory.oom.group` is enabled, where an entire group of processes is terminated together.

> [!NOTE]
> Unlike `memory.current` (which resets back toward zero once a killed process's pages are reclaimed), the `oom_kill` counter in `memory.events` is **monotonic and persistent** for the lifetime of that cgroup. This guarantees that short-lived OOM events are never missed by a polling monitor.

---

## 4. OOM Victim Selection & Isolation

### Why the Memory Hog was Killed:
1. The memory-hog process was spawned and its PID was written to `/sys/fs/cgroup/fault_{trial_id}/cgroup.procs`.
2. The memory hog rapidly allocated resident `bytearray` objects in 8MB chunks.
3. Once allocation breached the 64MB `memory.max` cap, the kernel could not satisfy the allocation or swap anonymous pages.
4. The kernel invoked the cgroup OOM killer. Since the OOM event originated within `fault_{trial_id}`, victim selection was confined to processes belonging to that cgroup.
5. The memory hog was the sole process (and largest consumer) in that cgroup. The kernel dispatched an uncatchable `SIGKILL` (signal 9, exit code -9 / 137), terminating it instantly.

### Why the Target App Survived:
- The target heartbeat application (`heartbeat_app.py`) ran outside `fault_{trial_id}` in the parent cgroup.
- Cgroups v2 strictly isolates memory limits: a child cgroup's limit does not restrict sibling or parent processes.
- The target process continued ticking every 1.0 second without dropped heartbeats or degraded responsiveness.

---

## 5. Why `psutil.virtual_memory()` and `dmesg` are Insufficient

1. **`psutil.virtual_memory()`**:
   - Reads global host metrics from `/proc/meminfo`.
   - Completely unaware of cgroup-level boundaries. If a container or cgroup has a 64MB limit on a 16GB host, `psutil.virtual_memory()` will report 16GB capacity, making cgroup memory pressure undetectable.
2. **`dmesg`**:
   - Requires kernel ring-buffer privileges (`CAP_SYSLOG`), which standard containers lack.
   - Contains global kernel logs mixed with unrelated system events.
   - Parsing text logs from `dmesg` is brittle and non-deterministic compared to the structured integer counters in `memory.events`.

Using `memory.current / memory.max` ratio and `memory.events` provides deterministic, zero-dependency, container-native fault detection.

---

## 6. Why Memory MTTD Includes Ramp-Up Time

Unlike `process_kill` (where `os.kill` terminates the target in < 1ms), `memory_pressure` models progressive resource exhaustion. The memory hog allocates 8MB bytearrays every 50ms, requiring $\sim 0.40\text{s}$ to reach the 64MB limit and trigger the cgroup OOM killer. Consequently, the observed MTTD ($\sim 0.795\text{s}$) combines the process's physical memory ramp-up time ($\sim 0.40\text{s}$) with the monitor's polling detection delay ($\sim 0.25\text{s}-0.40\text{s}$). This accurately mimics production memory leaks, which develop incrementally before breaching critical thresholds.

