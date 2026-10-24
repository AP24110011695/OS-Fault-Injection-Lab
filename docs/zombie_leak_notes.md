# Learning Notes: Zombie Processes, Reparenting & the Role of init

## 1. Overview & Context

In the OS Fault Injection Lab, **Phase 14** models a broken parent: a service that keeps forking short-lived children but never calls `wait()` on them. Every child that exits with its status unread becomes a **zombie**, and they pile up under the parent. Recovery kills the parent, reaps the orphans it left behind, and verifies the container really has zero zombies.

---

## 2. How Zombies Appear

A process that terminates does not disappear. The kernel discards its memory and CPU state immediately, but the process-table entry **stays** to preserve the exit status for the parent's next `wait()`/`waitpid()`. That remnant is the zombie (`Z`) state: dead but not reaped.

The lab's leaker makes this concrete with `os.fork()`:

- The child calls `os._exit(0)` immediately — the exit status is written to the process table and nobody ever reads it.
- The parent **never** waits: no `wait`, `waitpid`, or (for Popen) `poll()`. It just forks the next child 50ms later.
- Two implementation details are load-bearing, and both are classic gotchas:
  - **`subprocess` children cannot produce persistent zombies** — Python's `subprocess` machinery reaps finished children on its own, so the leak would never accumulate. Only a raw `os.fork()` leaks.
  - **`SIGCHLD` must stay at its default (`SIG_DFL`)** — a parent that sets `SIGCHLD` to `SIG_IGN` tells the kernel to auto-reap children, and the zombies would vanish instantly. The leaker never touches `SIGCHLD`.

The leak is capped at `ZOMBIE_LEAK_MAX_CHILDREN` (200) with a 50ms spawn interval, so the experiment stresses zombie accounting without ever risking the container's PID table.

---

## 3. Reparenting to PID 1 — and Why init Must Reap

When the leaker parent is finally `SIGKILL`ed, its zombie children are not destroyed — they are **reparented** to PID 1, the container's init. That handoff is the kernel's way of guaranteeing every process has a parent.

But PID 1 in this container is the **Python experiment runner**, and a plain Python process does not reap adopted children — that is not something the interpreter does on its own. This is exactly why real init systems (systemd, sysvinit, Docker's `init: true` tini) exist: **someone must reap children, or zombies accumulate forever**. The lab's recovery therefore calls `reap_zombie_children()` (`os.waitpid(-1, WNOHANG)` in a loop — non-blocking, reaps *any* exited child) and then **verifies** the zombie count is really zero before logging `RECOVERED`. Verification matters because reparenting is asynchronous and "I killed the parent" is not the same claim as "the table is clean".

---

## 4. Detection: Count Only the Leaker's Zombies

The detector counts the leaker's **direct children** (`psutil.Process.children()`, non-recursive) whose status is `STATUS_ZOMBIE` — never a container-wide count. Scoping matters: an unrelated process anywhere in the container could have its own zombie for its own reasons, and counting those would blame the wrong service. Detection fires above `ZOMBIE_THRESHOLD` (20) for `CONSECUTIVE_POLLS_THRESHOLD` (3) consecutive polls.

---

## 5. Why MTTD Includes the Spawn Ramp-Up Plus the Debounce

Zombies appear at the spawn rate, so the count is a **ramp**, not a step:

$$\text{MTTD} \approx \underbrace{\frac{\text{ZOMBIE\_THRESHOLD} + 1}{20/s}}_{\text{ramp} \approx 1.05s} + \underbrace{3 \times T_{\text{poll}}}_{\text{debounce} \approx 1.0-1.5s} \approx 2.1s - 2.5s$$

Observed across 15 trials: MTTD mean 2.324s (min 2.073s, max 2.504s) — matching the theory. One trial's `DETECTED` fired at 42 zombies: the poll quantum lets the count keep climbing between checks, so the reported number is a sample of the ramp, not its beginning. This is the same resource-ramp shape as memory_pressure, disk_full, and fd_exhaustion — the OS never announces "zombies accumulating"; the monitor must watch the count grow.

---

## 6. Observed Numbers

15 trials, 100% recovery success:

| Metric | Mean | Median | Min | Max |
|---|---|---|---|---|
| MTTD (sec) | 2.324 | 2.299 | 2.073 | 2.504 |
| MTTR (sec) | 2.331 | 2.305 | 2.081 | 2.512 |

Recovery overhead (MTTR − MTTD) is ~0.007s: `SIGKILL` the parent, reap it, reap the orphans, verify zero. After every trial the runner verifies both "no leftover leaker parent" and "zero zombies container-wide", and the run ends with a hard assertion of both (observed: 0 and 0).
