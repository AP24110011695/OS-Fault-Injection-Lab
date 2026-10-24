# Learning Notes: Process States, SIGSTOP/SIGCONT & Heartbeat-Based Health Checks

## 1. Overview & Context

In the OS Fault Injection Lab, **Phase 11** models the second most common production failure mode: a service that is **alive but not healthy**. The target is frozen in place with `SIGSTOP` — it keeps its PID, memory, and file descriptors, but stops executing and stops producing heartbeats. The monitor must notice the *absence of progress*, not the absence of a process.

---

## 2. Process States: Running vs Sleeping vs Stopped

| State | `psutil` name | Meaning |
|---|---|---|
| Running | `STATUS_RUNNING` | Currently executing on a CPU |
| Sleeping | `STATUS_SLEEPING` | Waiting for an event (timer, I/O); wakes when it arrives |
| Stopped | `STATUS_STOPPED` | Frozen by `SIGSTOP`; will not run again until `SIGCONT` |
| Zombie | `STATUS_ZOMBIE` | Terminated but not yet reaped by its parent |

`SIGSTOP` (signal 19 on x86 Linux) is to stopping what `SIGKILL` is to termination: it **cannot be caught, blocked, or ignored**. The kernel simply removes the process from the run queue. `SIGCONT` (signal 18) resumes it exactly where it froze — mid-sleep, mid-computation — with no knowledge anything happened.

Observed in the lab: after `SIGCONT`, the target's next heartbeat line appeared within ~1s and its tick counter continued uninterrupted.

---

## 3. Alive vs Healthy: Why Liveness Checks Miss Hangs

Every check used by the earlier faults fails here:

- `psutil.pid_exists(pid)` → `True` (the PID is still registered).
- `psutil.Process(pid).status()` → `stopped` or `sleeping` — never `dead`.
- The process still holds its memory, sockets, and file descriptors.

A hung service passes all of these. **Health means making progress**, so the lab gives the target a way to prove progress: `target/heartbeat_app.py` appends an ISO timestamp to `results/heartbeat.log` (`config.HEARTBEAT_FILE_PATH`) on every tick. The monitor's process_hang branch then checks **heartbeat staleness** — the age of the newest timestamp — and never consults the PID. That is the lesson of the fault: liveness and healthiness are different questions requiring different probes.

---

## 4. Why MTTD Is Roughly 2.0 to 3.5 Seconds

Staleness detection is **detection by absence**, and absence needs time to prove itself. The monitor may not fire the moment a heartbeat is late — a single slow tick or scheduler delay is not a hang. It waits until the newest heartbeat is older than `HEARTBEAT_TIMEOUT_SEC` (3.0s) before declaring the fault.

At injection time the newest heartbeat is 0–1s old (the target ticks every 1s), so staleness is reached roughly `HEARTBEAT_TIMEOUT_SEC − age + one poll quantum` after `SIGSTOP`:

$$\text{MTTD} \approx (3.0\text{s} - \text{age}_{\text{at inject}}) + \text{poll quantum} \approx 2.0\text{s} - 3.5\text{s}$$

Observed across 30 trials: MTTD mean 3.05s (resume) and 3.10s (restart), min 2.478s, max 3.485s — matching the theory. Note the range can dip below the 3.0s timeout because staleness is measured from the **last heartbeat**, which may predate the injection by up to a second. This is a fundamental trade-off, not an inefficiency: a smaller timeout detects faster but raises false-positive risk; a larger timeout is safer but slower. Process kill, by contrast, is detected on the very next poll (mean 0.26s) because death is unambiguous.

---

## 5. Recovery Strategies: Resume vs Restart

Two strategies were implemented and compared under identical conditions (same 15-trial count, same jitter, same detector; only the recovery action differs):

| Strategy | Action | Verification before `RECOVERED` | MTTD mean | MTTR mean | Recovery overhead (MTTR−MTTD) |
|---|---|---|---|---|---|
| **resume** | `SIGCONT` (PID 38 keeps running) | A fresh heartbeat is observed | 3.052s | 3.129s | 0.077s |
| **restart** | `SIGKILL` + supervisor restart (new PID) | A fresh heartbeat is observed | 3.101s | 3.210s | 0.109s |

100% recovery success in both runs (15 trials each).

Interpretation:

- Both strategies are dominated by detection time, not by the recovery action. Resuming costs ~0.08s of recovery overhead; restarting only ~0.03s more, because `TARGET_CMD` starts in ~0.1s.
- `RECOVERED` is logged **only after a fresh heartbeat is seen** — for both strategies. "Recovered" must mean *making progress again*, not merely *existing again*.
- The real-world difference is invisible in MTTR but critical in cause: `SIGCONT` resumes the process with whatever state caused the hang. If the hang was a deadlock or corrupted state, the process may hang again immediately. Restart guarantees a clean slate — the same trade-off production operators face between unblocking a wedged service (e.g., `kill -CONT`, flushing a stuck worker) and restarting it (`systemctl restart`).

---

## 6. Cleanup Rule: A Stopped Target Ignores `SIGTERM`

Signals sent to a `SIGSTOP`'d process are **queued, not handled**, until it is continued. A `SIGTERM`-based cleanup would silently fail to stop the frozen target — it would sit in the process table, stopped, until something continued it. The lab's per-trial cleanup therefore `SIGKILL`s process_hang targets directly and verifies after every trial that no stopped or leftover target remains; the experiment run additionally asserts zero stopped processes system-wide.
