# Learning Notes: Unix Signals, Process Lifecycles & Zombie Processes

## 1. Overview & Context

In the OS Fault Injection Lab, **Phase 3, 4, and 5** model the most common production failure mode: an unexpected, uncatchable process crash. The framework injects a hard kill into a running target application, monitors its liveness, detects termination, and automatically supervises its restart.

---

## 2. Unix Signals: `SIGKILL` vs. `SIGTERM`

Signals are asynchronous notifications sent by the Linux kernel to processes to inform them of system events or administrative requests.

| Property | `SIGTERM` (Signal 15) | `SIGKILL` (Signal 9) |
|---|---|---|
| **Catchable?** | Yes — application can install a signal handler via `signal.signal()` | No — uncatchable and unblockable |
| **Intended Behavior** | Graceful shutdown: finish in-flight requests, flush buffers, close sockets | Instant termination: kernel drops execution immediately |
| **Handled By** | User-space process runtime | Linux kernel scheduler directly |
| **Exit Code** | Usually `0` or custom status set by process | `-9` (or `128 + 9 = 137` in shell wrappers) |
| **Lab Usage** | Target's normal shutdown upon receiving termination | Fault injection via `os.kill(pid, signal.SIGKILL)` |

### Why `SIGKILL` is Used for Fault Injection:
In real systems, kernel panics, hardware faults, out-of-memory kills, or unhandled fatal exceptions do not give applications an opportunity to clean up gracefully. Simulating these catastrophic crashes requires `SIGKILL`.

---

## 3. Process Table, PIDs, and Zombie Processes

### What is a PID?
A Process Identifier (PID) is a positive integer assigned by the kernel from `/proc/sys/kernel/pid_max` representing a unique process descriptor (`struct task_struct`).

### The Zombie State (`TASK_DEAD` / `EXIT_ZOMBIE`):
When a process terminates in Linux:
1. The kernel reclaims its virtual memory (page tables), file descriptors, and CPU resources immediately.
2. However, the process's entry in the kernel's process table remains alive to preserve its exit code, termination signal, and resource usage statistics (`rusage`).
3. The process is now in the **Zombie** (`Z`) state.
4. The entry is only purged from the process table when its parent process calls `wait()`, `waitpid()`, or `proc.poll()`. This action is called **reaping**.

### Why `psutil.pid_exists(pid)` is Insufficient:
Because a zombie process's PID remains registered in the kernel's process table and `/proc/<pid>`, `psutil.pid_exists(pid)` returns `True` for zombies.

```python
# Insufficient: returns True even if process execution has halted
if psutil.pid_exists(pid):
    ...

# Correct (used in monitor/detector.py):
p = psutil.Process(pid)
if p.status() == psutil.STATUS_ZOMBIE:
    if proc is not None:
        proc.poll()  # Reap zombie child
    return False     # Functionally dead
```

---

## 4. Process Supervision & Self-Healing

Automated recovery in production systems (e.g., `systemd`, Docker restart policies, Kubernetes kubelet) relies on **supervision**:
1. **Restart Loop**: Re-launching the executable using `subprocess.Popen(config.TARGET_CMD)`.
2. **Exponential Backoff / Cooldown**: If a process crashes due to a corrupt configuration or missing file, restarting it instantly in a tight loop creates a **fork bomb**, exhausting system PIDs and CPU. Implementing `SUPERVISOR_COOLDOWN_SEC` and `SUPERVISOR_MAX_RETRIES` protects system stability.
3. **Liveness Verification**: A supervisor must verify the newly spawned child has actually initialized and remained alive (not immediate crash/zombie) before reporting successful recovery.

---

## 5. Detection Latency & Uniform Pre-Injection Jitter

Because `os.kill()` terminates the target in less than $1\text{ms}$, detection delay is purely an artifact of the monitoring loop's polling interval ($T_{\text{poll}} = 0.5\text{s}$).

- If injection occurs at a fixed offset after monitor launch, the injector and monitor become **phase-locked**, causing artificial, fixed latencies (e.g., $0.45\text{s}$ every trial).
- Adding a uniform random delay in $[0, T_{\text{poll}}]$ prior to injection simulates arbitrary real-world fault arrival.
- Over $N$ trials, the expected detection latency converges cleanly to the theoretical mean of a continuous uniform distribution:
  $$\mathbb{E}[\text{MTTD}] = \frac{T_{\text{poll}}}{2} = \frac{0.5\text{s}}{2} = 0.25\text{s}$$
  with observed minimums near $0\text{s}$ and maximums bounded by $T_{\text{poll}} = 0.5\text{s}$.
