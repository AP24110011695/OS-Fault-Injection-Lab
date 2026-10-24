# Learning Notes: File Descriptors, rlimits & EMFILE

## 1. Overview & Context

In the OS Fault Injection Lab, **Phase 13** models the classic slow-burn service failure: a **file-descriptor leak**. The faulty service lowers its *own* `RLIMIT_NOFILE` to 256 at startup and, when triggered, opens `/dev/null` every 20ms — first filling its descriptor table, then hitting `EMFILE`, and then continuing to run while failing on every attempt. The monitor watches the fd/limit ratio climb, and recovery replaces the leaky instance with a fresh, verified-clean one.

---

## 2. File Descriptors and the Per-Process fd Table

Every Linux process owns a **file descriptor table**: a small array mapping integer fds to open file objects (files, sockets, pipes, `/dev/null`, even directories). The kernel enforces a per-process ceiling, `RLIMIT_NOFILE`:

- It is **per-process, not system-wide**. `resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))` changes the limit for the calling process only — and it is *inherited* by that process's future children, never applied to siblings, the parent, or the system. The lab proves this: the runner, monitor, and target stay untouched while the leaker runs at 256 (observed in the `INJECTED` details: `own RLIMIT_NOFILE soft=256`, read back via `psutil.Process.rlimit`).
- The **soft limit** is the enforced one (raising it beyond the hard limit is impossible; the leaker only lowers both).
- Open fds are visible per process as symlinks in `/proc/<pid>/fd`, which is exactly what `psutil.Process.num_fds()` counts.

When the table is full, the kernel returns `EMFILE` ("too many open files") from `open()`/`socket()`. The leaker treats it the way a real leaking service does: it **keeps running**, still failing on every new connection or file open. This is why fd leaks are insidious — the process looks healthy until it *suddenly* cannot accept connections.

---

## 3. Detection: fd Count vs Its Own Limit

The detector computes the leaker's `num_fds() / RLIMIT_NOFILE(soft)` ratio and fires when it exceeds `FD_THRESHOLD_PERCENT` (90%) for `CONSECUTIVE_POLLS_THRESHOLD` (3) consecutive polls. Two design points matter:

- The denominator is the **process's own limit**, read from the process — not a global constant, and never the system-wide limit. A process whose own limit is 256 is "exhausted" at ~230 fds even though the host has millions free.
- A process with an unlimited soft limit (`RLIM_INFINITY`) has no meaningful ratio and is never flagged.

---

## 4. Why MTTD Includes the Open-Rate Ramp-Up Plus the Debounce

The leak is **rate-limited by design** (one 1-byte-size file per 20ms — a real service leaks on request cadence, not in a tight loop). Detection therefore has three stacked components:

$$\text{MTTD} \approx \underbrace{\frac{231 - \text{fds}_{\text{start}}}{50/s}}_{\text{ramp to } 90\% \approx 4.5s} + \underbrace{3 \times T_{\text{poll}}}_{\text{debounce} \approx 1.0-1.5s} \approx 5.5s - 6.1s$$

The monitor cannot flag the fault before enough descriptors actually exist — the ratio must physically climb past 90% — and then the debounce requires three sustained polls so a transient spike cannot trigger it. This is the same shape as memory_pressure and disk_full: **the OS does not signal "resource filling up"; the monitor must watch it climb**. Observed across 15 trials: MTTD mean 5.966s (min 5.721s, max 6.156s) — matching the theory.

---

## 5. Observed Numbers

15 trials, 100% recovery success:

| Metric | Mean | Median | Min | Max |
|---|---|---|---|---|
| MTTD (sec) | 5.966 | 5.982 | 5.721 | 6.156 |
| MTTR (sec) | 6.076 | 6.089 | 5.833 | 6.267 |

Recovery overhead (MTTR − MTTD) is ~0.11s: `SIGKILL` the leaker, reap it, start a fresh instance, and verify its fd count is low (observed **3 fds** — stdin/stdout/stderr — versus the leak plateau of ~255). The plateau itself sits at 255–256 fds: the kernel refuses every further open with `EMFILE`, and the leaker is still alive at that point (verified explicitly).

---

## 6. Why Recovery Restarts Instead of Freeing

A leaked fd is never returned by the leaking code — that is what "leak" means. The only realistic recovery is to **replace the process**: kill the leaker (the kernel closes all its descriptors at exit), reap it so no zombie remains, start a fresh instance, and *verify* the new instance is clean (low fd count) before logging `RECOVERED`. Verification matters because "it's running" and "it's healthy" are different claims — the same lesson as process_hang's fresh-heartbeat rule.
