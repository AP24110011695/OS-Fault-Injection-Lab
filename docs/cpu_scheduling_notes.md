# Learning Notes: CPU Scheduling, Load Average vs. CPU Percent

## 1. Overview & Context

In **Phase 8**, the OS Fault Injection Lab introduces system-wide CPU exhaustion using `stress-ng`. Unlike process crashes (which are binary: alive or dead), CPU saturation is a continuous, system-level resource bottleneck. This experiment highlights how the Linux kernel schedules competing workloads and how monitoring metrics reflect CPU pressure.

---

## 2. CPU Percent vs. Load Average

| Metric | Measurement Mechanism | Latency / Responsiveness | Behavior Under Fault |
|---|---|---|---|
| **CPU Percent** | Instantaneous active cycles vs. total cycles (`busy_time / total_time * 100`) over a sampling window | Sub-second (e.g., 0.5s poll interval) | Jumps to 100% immediately when `stress-ng` starts; drops to < 5% within 100ms of termination. |
| **Load Average** | Exponentially damped moving average of processes in run queue (`R`) or uninterruptible sleep (`D`) over 1, 5, and 15 min | Minutes of damping delay | Ramps up slowly over several minutes; remains elevated long after fault recovery. |

### Why Load Average Lags:
The Linux kernel calculates load average using an exponential decay formula:
$$\text{load}_{t} = \text{load}_{t-1} \cdot e^{-\Delta t / \tau} + n \cdot (1 - e^{-\Delta t / \tau})$$
where $\tau = 60\text{s}$ for the 1-minute load average. 

Because of this mathematical inertia:
- When 12 `stress-ng` workers launch on a 12-core system, instantaneous CPU percent hits 100% in milliseconds. However, the 1-minute load average reaches only $\sim 7.6$ after 1 minute and takes 3–5 minutes to reach 12.
- When `stress-ng` is killed, CPU usage drops to 0% immediately, but load average takes 3–5 minutes to decay back near zero.
- **Key takeaway for monitoring**: For rapid automated fault detection (low MTTD), monitoring tools must evaluate short-window CPU utilization rather than smoothed load averages.

---

## 3. Why `psutil.cpu_percent(interval=None)` Requires Priming

`psutil.cpu_percent(interval=None)` compares CPU times from `/proc/stat` between two points in time without blocking:
1. On its **first call** in a Python process, it records the initial CPU counter baseline and returns `0.0`.
2. On **subsequent calls**, it computes the delta since the previous call:
   $$\text{CPU \%} = \frac{\Delta \text{busy ticks}}{\Delta \text{total ticks}} \times 100$$
3. If not primed prior to polling, the first poll would always falsely register `0.0%`, introducing an artificial 1-poll delay before consecutive breach counters begin. Calling `psutil.cpu_percent(interval=None)` once before the polling loop primes the baseline.

---

## 4. CFS Scheduling & Process Isolation

During the CPU hog fault, `stress-ng` dispatches workers equal to `os.cpu_count()`, saturating 100% of available CPU cores. Yet, the target heartbeat application (`heartbeat_app.py`) consistently produces heartbeats every 1.0 second without dropping ticks.

### How the Linux Completely Fair Scheduler (CFS) Enables This:
- **Virtual Runtime (`vruntime`)**: CFS assigns CPU time to tasks based on their accumulated `vruntime` (normalized execution time weighted by nice level).
- **CPU-bound vs. I/O-bound / Sleeping Tasks**:
  - The `stress-ng` workers run tight computational loops without yielding, causing their `vruntime` to advance rapidly.
  - The heartbeat application executes for less than 1ms, then calls `time.sleep(1.0)`, putting its task into `TASK_INTERRUPTIBLE` state. While asleep, it consumes zero CPU and its `vruntime` does not advance.
- **Preemption**: When the heartbeat timer expires, the kernel wakes the heartbeat task. Because its `vruntime` is far lower than the CPU-hogging `stress-ng` workers, CFS immediately preempts one of the workers and grants the CPU to the heartbeat process.
- **Viva Insight**: 100% CPU utilization does not mean the operating system is locked or dead; CFS prioritizes sleeping/interactive tasks when they wake up, ensuring latency-sensitive tasks remain responsive.
