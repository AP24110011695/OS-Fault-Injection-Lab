# Tasks — OS Fault Injection Lab

---

## Operating Protocol — "execute phaseN"

When the user types `execute phaseN`:

1. Read `memory.md` first to find the true current state.
2. Read `prd.md`, `architecture.md`, `rules.md`, and `tasks.md`. Read `design.md` too if the phase touches charts, output, or docs.
3. Check that all earlier phases are complete. If not, finish them first.
4. Do ALL the work of that phase: write the code, run it, test it, verify the definition of done.
5. If anything breaks, debug and fix it yourself. Do not ask the user. Retry with a different approach until it works. Only stop if it is truly impossible, and explain exactly why.
6. Do not ask clarifying questions. Choose the simplest option that fits the docs and log it in `memory.md` under "Decisions."
7. Before finishing, review your own code and delete anything unnecessary.
8. Update `memory.md` (completed tasks, decisions, issues, next step) and tick the boxes in `tasks.md`.
9. End with a short summary: what was done, how to run it, what the student should learn from this phase.

**Never start coding from guesswork. If unsure, re-read the docs.**

---

## Phase 1: Project Scaffold

**Goal:** Set up the project structure, Docker environment, and a running target application.

**Tasks:**
- [x] Create folder structure matching `architecture.md` (all `__init__.py` files, empty modules).
- [x] Write `requirements.txt` with `psutil` and `matplotlib`.
- [x] Write `Dockerfile` based on `python:3.11-slim`. Install `stress-ng`, copy project, install Python deps.
- [x] Write `docker-compose.yml` that builds and runs the container, mounts `./results` as a volume.
- [x] Write `target/heartbeat_app.py`: a loop that prints a heartbeat every 1 second and does light work.
- [x] Write `scripts/safety_check.py`: check for `/.dockerenv` or cgroup namespace; exit with error if not in Docker.
- [x] Write `config.py` with initial constants (paths, intervals, thresholds).
- [x] Write `.gitignore`.
- [x] Create `results/.gitkeep`.

**Files touched:** `Dockerfile`, `docker-compose.yml`, `requirements.txt`, `config.py`, `target/__init__.py`, `target/heartbeat_app.py`, `scripts/safety_check.py`, `.gitignore`, `results/.gitkeep`, all `__init__.py` files.

**Definition of done:**
- `docker compose up --build` succeeds.
- The container starts and the heartbeat app prints output to the console.
- `safety_check.py` returns success inside the container.
- `safety_check.py` returns failure (with a clear message) outside the container.

**How to verify:**
```bash
docker compose up --build
# Observe heartbeat output in the terminal.
# Ctrl+C to stop.
docker compose run lab python scripts/safety_check.py
# Should print "OK: Running inside Docker"
python scripts/safety_check.py
# Should print "ERROR: Not running inside Docker..." and exit 1
```

**What the student should learn:**
- How Docker containers provide isolation.
- How a Dockerfile layers work (FROM, RUN, COPY, CMD).
- What `docker-compose.yml` does and why volumes are useful.
- How a simple long-running process works in Python.

---

## Phase 2: Shared Event Log + Central Config

**Goal:** Build the event log module that every other component will use, and finalize the central config.

**Tasks:**
- [x] Write `event_log.py` with functions: `log_event()`, `read_events()`, `clear_log()`.
- [x] Use JSONL format (one JSON object per line).
- [x] Event fields: `timestamp`, `trial_id`, `fault_type`, `event`, `details`.
- [x] `log_event()` appends atomically (open in append mode, write one line, flush).
- [x] `read_events()` reads and optionally filters by `trial_id` or `fault_type`.
- [x] `clear_log()` truncates the file.
- [x] Add a `__main__` block to `event_log.py` that demonstrates write + read.
- [x] Finalize `config.py` with all known constants from `architecture.md`.
- [x] Verify inside Docker.

**Files touched:** `event_log.py`, `config.py`.

**Definition of done:**
- `python -m event_log` writes sample events and reads them back, printing to stdout.
- The JSONL file is well-formed (each line parses as valid JSON).
- `read_events(trial_id="test_001")` correctly filters.
- `clear_log()` empties the file.

**How to verify:**
```bash
docker compose run lab python -m event_log
# Should print written events, then filtered events, then confirm clear.
```

**What the student should learn:**
- JSONL format and why it is good for append-only logs (vs. full JSON arrays).
- File I/O in Python: append mode, flushing, reading line by line.
- Why a central config avoids magic numbers scattered through the code.

---

## Phase 3: Process Kill Injector

**Goal:** Implement the injector that kills the target process with `SIGKILL` and logs the event.

**Tasks:**
- [x] Write `injector/process_kill.py` with function `inject(target_pid: int, trial_id: str) -> None`.
- [x] Use `os.kill(target_pid, signal.SIGKILL)`.
- [x] Log an `INJECTED` event via `event_log.log_event()`.
- [x] Handle the case where the PID does not exist (log error, raise).
- [x] Add a `__main__` block for manual testing: start the target, inject, verify it died.

**Files touched:** `injector/__init__.py`, `injector/process_kill.py`.

**Definition of done:**
- Running the injector kills the target process.
- The event log contains an `INJECTED` event with the correct trial ID and PID in details.
- The target process is confirmed dead (PID no longer exists).

**How to verify:**
```bash
docker compose run lab python -m injector.process_kill
# Should start target, kill it, print confirmation, show event log entry.
```

**What the student should learn:**
- How `os.kill()` sends signals to processes.
- The difference between `SIGKILL` (9, unblockable) and `SIGTERM` (15, catchable).
- How to check if a process is alive using `psutil.pid_exists()`.
- What a PID is and how the OS assigns them.

---

## Phase 4: Monitor + Detection for Process Death

**Goal:** Build the monitoring loop and process-death detection logic.

**Tasks:**
- [x] Write `monitor/monitor.py` with a polling loop that reads system metrics using `psutil`.
- [x] Poll at `config.MONITOR_POLL_INTERVAL_SEC` (e.g., 0.5 seconds).
- [x] Track target process liveness via `psutil.pid_exists(pid)`.
- [x] Write `monitor/detector.py` with threshold/condition checks.
- [x] For process kill: detect when target PID is gone.
- [x] On detection, call `event_log.log_event()` with `DETECTED`.
- [x] The monitor must be stoppable (flag or event to break the loop).
- [x] Add a `__main__` block that monitors a given PID and prints readings.

**Files touched:** `monitor/__init__.py`, `monitor/monitor.py`, `monitor/detector.py`.

**Definition of done:**
- Monitor detects when the target process dies.
- `DETECTED` event is logged with correct timing.
- MTTD (manual calculation) is the difference between `INJECTED` and `DETECTED` timestamps.
- Monitor stops cleanly when detection occurs or when signaled.

**How to verify:**
```bash
docker compose run lab python -m monitor.monitor
# In another terminal (or scripted): kill the target process.
# Monitor should detect the death and print DETECTED with timing.
```

**What the student should learn:**
- How `psutil` reads process info from `/proc`.
- What polling is and why the poll interval affects detection latency.
- The trade-off between poll frequency and CPU overhead.
- How to structure a monitoring loop that can be cleanly stopped.

---

## Phase 5: Recovery for Process Kill — First Full Loop

**Goal:** Implement process restart recovery and run the complete inject→detect→recover loop for the first time.

**Tasks:**
- [x] Write `recovery/supervisor.py` with function `restart_target() -> int` (returns new PID).
- [x] Implement retry logic: up to `config.SUPERVISOR_MAX_RETRIES` attempts with `config.SUPERVISOR_COOLDOWN_SEC` between.
- [x] Verify the new process is alive before declaring success.
- [x] Log `RECOVERED` event on success, `FAILED` on exhausted retries.
- [x] Write a simple orchestration script or `__main__` block that runs the full loop: start target → inject → detect → recover.
- [x] Verify the full loop works end-to-end inside Docker.
- [x] Clean up all processes after the loop.

**Files touched:** `recovery/__init__.py`, `recovery/supervisor.py`.

**Definition of done:**
- The full loop runs: target starts, gets killed, monitor detects death, supervisor restarts it.
- Event log contains: `STARTED`, `INJECTED`, `DETECTED`, `RECOVERED` in correct order.
- The restarted target process is alive and producing heartbeats.
- All timing data is present in the event log.

**How to verify:**
```bash
docker compose run lab python -m recovery.supervisor
# Should run the full loop and print each step with timing.
# Event log should have all four events for one trial.
```

**What the student should learn:**
- How process supervisors work (like systemd restart policies).
- Retry patterns: max retries, cooldown, exponential backoff (we use simple cooldown).
- Why verifying recovery is as important as attempting it.
- The complete fault-injection loop and why each step exists.

---

## Phase 6: Experiment Runner + Metrics

**Goal:** Run N trials of the process kill fault, compute MTTD/MTTR, and write results to CSV.

**Tasks:**
- [x] Write `experiment/runner.py` that orchestrates N trials of a given fault type.
- [x] For each trial: start target, stabilize, inject, detect, recover, cleanup, pause.
- [x] Generate trial IDs: `{fault_type}_{zero_padded_number}` (e.g., `process_kill_001`).
- [x] Enforce maximum trial duration (timeout). If exceeded, force-kill everything and log `FAILED`.
- [x] Write `experiment/metrics.py` that reads the event log and computes per-trial MTTD/MTTR, plus aggregates (mean, median, min, max).
- [x] Write `experiment/results.py` that writes a results CSV with columns: `trial_id, fault_type, mttd_sec, mttr_sec, success`.
- [x] CLI interface: `python -m experiment.runner --fault process_kill --trials 15`.
- [x] Print summary table to stdout following `design.md` CLI format.
- [x] Clean up all processes and event log between experiment runs (not between trials).

**Files touched:** `experiment/__init__.py`, `experiment/runner.py`, `experiment/metrics.py`, `experiment/results.py`.

**Definition of done:**
- `python -m experiment.runner --fault process_kill --trials 15` runs 15 trials end-to-end.
- Results CSV is written with correct data for all trials.
- Summary table is printed to stdout with mean/median/min/max MTTD and MTTR.
- No leftover processes after the run.
- Success rate is reported.

**How to verify:**
```bash
docker compose run lab python -m experiment.runner --fault process_kill --trials 15
# Should run all trials, print progress, print summary, write CSV.
cat results/results.csv
# Should have 15 rows of data.
```

**What the student should learn:**
- How to design a repeatable experiment with multiple trials.
- What MTTD and MTTR mean and why they matter in SRE/DevOps.
- Basic statistics: mean vs. median, why min/max matter.
- How to structure a CLI tool with `argparse`.

---

## Phase 7: Memory Pressure Fault

**Goal:** Implement memory pressure injection, detection, and recovery. Observe OOM killer behavior.

**Tasks:**
- [x] Write `injector/memory_pressure.py`: create a cgroup with `memory.max` set to `config.CGROUP_MEMORY_LIMIT_MB`, then launch a memory-hungry child process inside it. The memory hog runs inside the limited cgroup; the target process runs outside it.
- [x] The memory-hungry process: allocate memory in a loop until killed or limit hit.
- [x] Log `INJECTED` event.
- [x] Extend `monitor/detector.py`: read `memory.current` and `memory.max` from the cgroup filesystem, compute `current/max` ratio. Detect when ratio > `config.MEMORY_THRESHOLD_PERCENT` for N consecutive polls. Also read `oom_kill` counter from `memory.events` to detect OOM kills. Do **not** use `psutil.virtual_memory()` for this fault.
- [x] Write `recovery/resource_recovery.py`: kill the memory-hog process (if still alive, i.e. not already OOM-killed), verify it is dead, restart target if it was affected.
- [x] Log `DETECTED` and `RECOVERED` events.
- [x] Document OOM killer behavior: read `memory.events` inside the cgroup, note the `oom_kill` counter and which process was killed.
- [x] Write learning notes about OOM killer in `docs/` or comments.
- [x] Run experiment with `--fault memory_pressure --trials 15`.
- [x] Clean up cgroup directories after every trial.

**Files touched:** `injector/memory_pressure.py`, `monitor/detector.py`, `monitor/monitor.py`, `recovery/resource_recovery.py`, `experiment/runner.py`, `experiment/results.py`, `docs/oom_killer_notes.md`.

**Definition of done:**
- Memory pressure fault runs end-to-end: inject → detect → recover.
- cgroup is created and cleaned up correctly.
- OOM killer behavior is observed and documented via `memory.events`.
- 15 trials run successfully with MTTD/MTTR data.
- Results CSV includes memory_pressure rows.

**How to verify:**
```bash
docker compose run lab python -m experiment.runner --fault memory_pressure --trials 15
# Should run all trials, handle OOM situations, print summary.
```

**What the student should learn:**
- How Linux cgroups v2 enforce memory limits.
- How the OOM killer selects victims and why.
- How to read cgroup files: `memory.current`, `memory.max`, `memory.events` (oom_kill counter).
- Why `psutil.virtual_memory()` cannot see cgroup limits and why cgroup-level metrics are needed.
- Why memory pressure is harder to detect reliably than a process death.

---

## Phase 8: CPU Hog Fault

**Goal:** Implement CPU saturation injection, detection, and recovery.

**Tasks:**
- [x] Write `injector/cpu_hog.py`: launch `stress-ng --cpu N --timeout T` as a subprocess.
- [x] Log `INJECTED` event.
- [x] Extend `monitor/detector.py`: detect CPU > `config.CPU_THRESHOLD_PERCENT` for N consecutive polls.
- [x] Extend `recovery/resource_recovery.py`: kill `stress-ng` process, verify CPU returns to normal.
- [x] Log `DETECTED` and `RECOVERED` events.
- [x] Run experiment with `--fault cpu_hog --trials 15`.
- [x] Handle edge case: `stress-ng` may have already exited by timeout before recovery.

**Files touched:** `config.py`, `injector/cpu_hog.py`, `monitor/detector.py`, `monitor/monitor.py`, `recovery/resource_recovery.py`, `experiment/runner.py`, `docs/cpu_scheduling_notes.md`, `docs/oom_killer_notes.md`.

**Definition of done:**
- CPU hog fault runs end-to-end: inject → detect → recover.
- `stress-ng` is properly cleaned up after each trial.
- 15 trials run successfully with MTTD/MTTR data.
- Results CSV includes cpu_hog rows.

**How to verify:**
```bash
docker compose run lab python -m experiment.runner --fault cpu_hog --trials 15
# Should run all trials, detect CPU saturation, recover, print summary.
```

**What the student should learn:**
- How `stress-ng` works: spawning CPU worker threads.
- How `psutil.cpu_percent()` measures utilization (per-interval sampling).
- What load average means vs. CPU percentage.
- How CFS (Completely Fair Scheduler) distributes time under contention.
- Why CPU detection may need sustained threshold breaches (debouncing).

---

## Phase 9: Results and Charts

**Goal:** Generate publication-quality charts following `design.md`, and a comparison summary.

**Tasks:**
- [x] Run all three faults (if not already): process_kill, memory_pressure, cpu_hog with 15 trials each.
- [x] Implement chart generation in `experiment/results.py` following `design.md` exactly.
- [x] Chart 1: MTTD by fault type (bar + individual dots).
- [x] Chart 2: MTTR by fault type (bar + individual dots).
- [x] Chart 3: Success rate by fault type (horizontal bar with direct labels).
- [x] Apply `apply_chart_style()` from `design.md` before generating charts.
- [x] Titles must state findings, not chart types.
- [x] Save charts to `results/` as PNG at 150 DPI.
- [x] Print a comparison summary to stdout: which fault is fastest to detect, which is hardest to recover from, and why.

**Files touched:** `experiment/results.py`, `experiment/runner.py`.

**Definition of done:**
- Three (or four) PNG chart files exist in `results/`.
- Charts follow every rule in `design.md`: palette, typography, no spines, direct labels, etc.
- Comparison summary printed to stdout is clear and insightful.

**How to verify:**
```bash
docker compose run lab python -m experiment.runner --fault all --trials 15
# Then check results/ for PNG files.
# Open PNGs and visually inspect against design.md rules.
```

**What the student should learn:**
- How to use matplotlib for clean, professional data visualization.
- Why chart design matters: titles that tell a story, clear axes, honest representation.
- How to compare metrics across experiment conditions.
- How to present technical results to a non-technical audience.

---

## Phase 10: Safety, Tests, README, Final Cleanup

**Goal:** Harden the project, add tests, write documentation, and prepare for demonstration.

**Tasks:**
- [x] Finalize `scripts/safety_check.py`: verify Docker, cgroups availability, stress-ng installed, psutil importable.
- [x] Write tests in `tests/` for core logic:
  - [x] `test_event_log.py`: write, read, filter, clear.
  - [x] `test_metrics.py`: MTTD/MTTR calculation with known data.
  - [x] `test_detector.py`: threshold logic with mock data.
  - [x] `test_supervisor.py`: retry/cooldown logic.
- [x] Write `README.md` following `design.md` tone: what, why, how to run, what you'll see, project structure, sample output.
- [x] Write learning notes in `docs/` summarizing key OS concepts demonstrated by each fault.
- [x] Write a demo script (`scripts/demo.py`) that runs all 3 faults and generates charts in one command.
- [x] Full end-to-end run: all 3 faults, 15 trials each, charts generated, no errors.
- [x] Final code review: delete any dead code, unused imports, or unnecessary files.
- [x] Verify `.gitignore` is correct.
- [x] Update all docs to reflect final state.

**Files touched:** `scripts/safety_check.py`, `tests/`, `README.md`, `docs/`, `scripts/demo.py`.

**Definition of done:**
- All tests pass inside Docker.
- README is complete and accurate.
- Demo script runs all experiments and produces charts.
- Full end-to-end run succeeds with no errors.
- No dead code, no unused files, no magic numbers.
- A student can clone the repo, run one command, and see results.

**How to verify:**
```bash
docker compose run lab python -m unittest discover tests -v
# All tests pass.
docker compose run lab python scripts/demo.py
# Full demo runs, charts appear in results/.
docker compose up --build
# Everything works from a clean build.
```

**What the student should learn:**
- Why testing matters and what to test (logic, not glue).
- How to write a README that helps someone else use your project.
- How to do a final code review and clean up.
- How to present a complete project: from problem statement to results.
- Confidence to explain every component in a viva.

---

## Phase 11: Process Hang Fault

**Goal:** Implement process hang injection (`SIGSTOP`), heartbeat-staleness detection, and two compared recovery strategies (resume vs restart).

**Tasks:**
- [x] Add `HEARTBEAT_FILE_PATH` to `config.py` and make the smallest possible change to `target/heartbeat_app.py`: append the current timestamp to the heartbeat file on each tick. Reset the file at trial start so staleness is measured only against the current run.
- [x] Write `injector/process_hang.py`: send `SIGSTOP` to the target, log `INJECTED`.
- [x] Extend `monitor/detector.py`: detect heartbeat staleness — no fresh timestamp within `config.HEARTBEAT_TIMEOUT_SEC`. Do NOT use a PID liveness check: the target is still alive while stopped, and that is the lesson.
- [x] Implement both recovery strategies in `recovery/supervisor.py`: "resume" (send `SIGCONT`, verify heartbeats resume) and "restart" (`SIGKILL` + `restart_target()`).
- [x] Log `RECOVERED` only after a fresh heartbeat is observed (both strategies).
- [x] Choose the simplest way to record the strategy per trial (e.g., embed it in the trial id) so MTTR can be compared per strategy; record the decision in `memory.md`.
- [x] Update `experiment/runner.py` to orchestrate `process_hang` trials, with a strategy choice in the CLI (simplest option consistent with `--fault`, e.g. `--strategy resume|restart`).
- [x] Add unit tests for the heartbeat-staleness detector (fresh heartbeat → no detection; stale heartbeat after N polls → detection).
- [x] Run the experiment: 15 trials per strategy.
- [x] Run the full unit test suite and a quick smoke trial of at least one existing fault (e.g., `--fault process_kill --trials 1`) to prove nothing broke.

**Files touched:** `config.py`, `target/heartbeat_app.py`, `injector/process_hang.py`, `monitor/detector.py`, `monitor/monitor.py`, `recovery/supervisor.py`, `experiment/runner.py`, `tests/`.

**Definition of done:**
- process_hang runs end-to-end: inject → detect → recover, with `RECOVERED` logged only after a fresh heartbeat.
- Both recovery strategies work and MTTR is comparable per strategy in the results.
- Detection does not rely on PID liveness.
- All unit tests pass; the existing-fault smoke trial succeeds.
- Results CSV includes process_hang rows for both strategies.

**How to verify:**
```bash
docker compose run lab python -m injector.process_hang
# Target freezes (alive but no heartbeats), detector fires on staleness.
docker compose run lab python -m experiment.runner --fault process_hang --strategy resume --trials 15
docker compose run lab python -m experiment.runner --fault process_hang --strategy restart --trials 15
docker compose run lab python -m unittest discover tests -v
```

**What the student should learn:**
- Process states: running, sleeping, stopped, zombie — and how `SIGSTOP`/`SIGCONT` move a process between them.
- "Alive" (PID exists) vs "healthy" (making progress): why liveness checks miss hangs.
- How heartbeat/health-check timeouts trade detection speed against false positives.
- Why recovery must be verified (a fresh heartbeat) before declaring success.
- How to compare two recovery strategies with data instead of intuition.

---

## Phase 12: Disk Full Fault

**Goal:** Implement disk-full injection on a size-capped tmpfs, ENOSPC detection, and verified cleanup — with hard safety guarantees.

**Tasks:**
- [x] Add `DISK_FAULT_SIZE_MB`, `DISK_MOUNT_PATH`, and `DISK_THRESHOLD_PERCENT` to `config.py`.
- [x] Write `injector/disk_full.py`: mount a tmpfs of `DISK_FAULT_SIZE_MB` at `DISK_MOUNT_PATH` inside the container.
- [x] SAFETY (mandatory): before writing anything, verify via `/proc/mounts` that `DISK_MOUNT_PATH` is really the size-capped tmpfs mountpoint. If the mount fails, ABORT the trial. NEVER fall back to writing on the container's normal filesystem.
- [x] Start a writer process that fills the tmpfs until the OS returns `ENOSPC`; log `INJECTED`.
- [x] Extend `monitor/detector.py`: detect `psutil.disk_usage(DISK_MOUNT_PATH).percent` above `DISK_THRESHOLD_PERCENT` for N consecutive polls.
- [x] Write recovery in `recovery/resource_recovery.py`: kill the writer, delete its files, verify usage drops below the threshold, then unmount the tmpfs in cleanup.
- [x] Always unmount and remove the directory after every trial — including on Ctrl+C (graceful SIGINT path).
- [x] Log `DETECTED` and `RECOVERED` events.
- [x] Run the experiment: `--fault disk_full --trials 15`.
- [x] Run the full unit test suite and a quick smoke trial of at least one existing fault to prove nothing broke.

**Files touched:** `config.py`, `injector/disk_full.py`, `monitor/detector.py`, `monitor/monitor.py`, `recovery/resource_recovery.py`, `experiment/runner.py`, `tests/`.

**Definition of done:**
- disk_full runs end-to-end: inject → detect → recover.
- The tmpfs safety check is proven: a failed mount aborts the trial and nothing is ever written outside the tmpfs.
- After every trial (and after Ctrl+C) the tmpfs is unmounted and the mount directory removed; no leftover mounts.
- 15 trials run with MTTD/MTTR data; results CSV includes disk_full rows.
- All unit tests pass; the existing-fault smoke trial succeeds.

**How to verify:**
```bash
docker compose run lab python -m injector.disk_full
# Writer fills the tmpfs, ENOSPC occurs, cleanup unmounts.
docker compose run lab python -m experiment.runner --fault disk_full --trials 15
mount | grep fault_disk   # inside the container: should show nothing after the run
docker compose run lab python -m unittest discover tests -v
```

**What the student should learn:**
- What filesystems and mount points are, and how mounting works in Linux.
- What tmpfs is (RAM-backed filesystem) and why it makes disk-fault injection safe and disposable.
- What `ENOSPC` is and how the OS reports "no space left on device".
- `df` vs `du`: filesystem usage vs directory usage, and why they can disagree.
- Why verifying preconditions (mountpoint checks) before destructive operations matters.

---

## Phase 13: FD Exhaustion Fault

**Goal:** Implement file-descriptor exhaustion in a single isolated process, ratio-based detection, and clean-instance recovery.

**Tasks:**
- [x] Add `FD_LIMIT` and `FD_THRESHOLD_PERCENT` to `config.py`.
- [x] Write `injector/fd_exhaustion.py`: start a leaker process (the faulty service) that lowers ITS OWN limit with `resource.setrlimit(resource.RLIMIT_NOFILE, FD_LIMIT)` and keeps opening files until it hits `EMFILE` (handle `EMFILE` and keep running). The limit applies only to that process, never to the system.
- [x] Log `INJECTED`.
- [x] Extend `monitor/detector.py`: detect the leaker's `psutil.Process.num_fds()` divided by its `RLIMIT_NOFILE` limit above `FD_THRESHOLD_PERCENT` for N consecutive polls.
- [x] Write recovery in `recovery/supervisor.py`: kill the leaking process, start a fresh clean instance, verify its fd count is low, then log `RECOVERED`.
- [x] Run the experiment: `--fault fd_exhaustion --trials 15`.
- [x] Run the full unit test suite and a quick smoke trial of at least one existing fault to prove nothing broke.

**Files touched:** `config.py`, `injector/fd_exhaustion.py`, `monitor/detector.py`, `monitor/monitor.py`, `recovery/supervisor.py`, `experiment/runner.py`, `tests/`.

**Definition of done:**
- fd_exhaustion runs end-to-end: inject → detect → recover.
- The rlimit change is proven to be per-process: other processes and the system are unaffected.
- The leaker keeps running at the limit (EMFILE handled) until recovery kills it.
- Recovery starts a fresh instance and verifies a low fd count before `RECOVERED`.
- 15 trials run with MTTD/MTTR data; results CSV includes fd_exhaustion rows.
- All unit tests pass; the existing-fault smoke trial succeeds.

**How to verify:**
```bash
docker compose run lab python -m injector.fd_exhaustion
# Leaker hits EMFILE and stays alive; detector fires on the fd ratio.
docker compose run lab python -m experiment.runner --fault fd_exhaustion --trials 15
docker compose run lab python -m unittest discover tests -v
```

**What the student should learn:**
- What a file descriptor is and how each process owns its own fd table.
- What `ulimit`/`RLIMIT_NOFILE` control and that rlimits are per-process (inherited, not system-wide).
- How to inspect open fds via `psutil` and `/proc/<pid>/fd`.
- What `EMFILE` means and why leaking services fail slowly, then suddenly.
- Why recovery must verify the new instance is clean (low fd count), not just running.

---

## Phase 14: Zombie Leak Fault

**Goal:** Implement zombie accumulation via an unreaping parent, count-only-this-parent detection, and verified zombie-free recovery including the PID 1 reaping check.

**Tasks:**
- [x] Add `ZOMBIE_LEAK_MAX_CHILDREN` and `ZOMBIE_THRESHOLD` to `config.py`.
- [x] Write `injector/zombie_leak.py`: a parent process spawns short-lived children that exit immediately; the parent NEVER reaps them (never calls `wait`). Cap the total at `ZOMBIE_LEAK_MAX_CHILDREN` and spawn at a controlled rate so the PID table is never at risk.
- [x] Log `INJECTED`.
- [x] Extend `monitor/detector.py`: count zombie children of the leaker parent (`psutil` status `STATUS_ZOMBIE`) and detect when the count is above `ZOMBIE_THRESHOLD` for N consecutive polls. Count only the leaker's children so other processes cannot cause false alarms.
- [x] Write recovery in `recovery/resource_recovery.py`: kill the parent.
- [x] IMPORTANT: orphaned zombies get adopted by PID 1, and in this container PID 1 is the Python runner, which may not reap them. After recovery, VERIFY the zombies are really gone. Reuse the existing `reap_zombie_children()` or set `init: true` in `docker-compose.yml` — whichever is simpler — and record the decision in `memory.md`.
- [x] Log `DETECTED` and `RECOVERED` events.
- [x] Run the experiment: `--fault zombie_leak --trials 15`.
- [x] Run the full unit test suite and a quick smoke trial of at least one existing fault to prove nothing broke.

**Files touched:** `config.py`, `injector/zombie_leak.py`, `monitor/detector.py`, `monitor/monitor.py`, `recovery/resource_recovery.py`, `docker-compose.yml` (only if the `init: true` option is chosen), `experiment/runner.py`, `tests/`.

**Definition of done:**
- zombie_leak runs end-to-end: inject → detect → recover.
- After recovery, zero zombies remain for the leaker (verified, not assumed).
- The PID 1 reaping question is answered and the decision recorded in `memory.md`.
- The child cap and spawn rate keep the container safe (at most `ZOMBIE_LEAK_MAX_CHILDREN` children total).
- 15 trials run with MTTD/MTTR data; results CSV includes zombie_leak rows.
- All unit tests pass; the existing-fault smoke trial succeeds.

**How to verify:**
```bash
docker compose run lab python -m injector.zombie_leak
# Zombies accumulate under the parent, detector fires, recovery leaves zero zombies.
docker compose run lab python -m experiment.runner --fault zombie_leak --trials 15
docker compose run lab python -m unittest discover tests -v
```

**What the student should learn:**
- What a zombie process is (terminated but not reaped) and how it differs from an orphan.
- How reparenting to PID 1 works when a parent dies.
- Why init processes must reap children, and what accumulates when they do not.
- How to count zombies precisely (only the leaker's children) to avoid false alarms.
- Why the PID table is a finite kernel resource worth protecting (hence the cap).

---

## Phase 15: Integration — Seven-Fault Suite

**Goal:** Wire all seven faults into the runner, results, charts, safety check, demo, and tests.

**Tasks:**
- [x] Extend `experiment/runner.py`: `--fault all` runs all seven faults (15 trials each; process_hang runs both strategies).
- [x] Extend `experiment/results.py`: charts for 7 faults following the updated `design.md` (per-fault colors, horizontal-bar layouts for seven categories, direct labels).
- [x] Update `scripts/safety_check.py` if needed for the new faults (e.g., tmpfs mount capability check).
- [x] Update `scripts/demo.py`: runs all 7 faults (1 trial each, plus both process_hang strategies) and generates charts in one command.
- [x] Extend the unit tests for the new detectors: heartbeat staleness, disk usage ratio, fd ratio, zombie count.
- [x] Verify `results/results.csv` still accumulates rows across runs and keeps all faults (existing behavior, keyed on trial_id).
- [x] Full run: `--fault all --trials 15` — 105 trials, charts generated, no errors.
- [x] Cleanup verification after the full run: no leftover processes, no cgroups, no mounts, no zombies.

**Files touched:** `experiment/runner.py`, `experiment/results.py`, `scripts/safety_check.py`, `scripts/demo.py`, `tests/`.

**Definition of done:**
- `--fault all` runs all seven faults end-to-end in one command.
- Charts show all seven faults with correct per-fault colors and readable labels.
- All unit tests pass.
- results.csv contains rows for all seven faults.
- Zero leftover resources after the full run.

**How to verify:**
```bash
docker compose run lab python -m experiment.runner --fault all --trials 15
docker compose run lab python -m experiment.results
docker compose run lab python scripts/demo.py
docker compose run lab python -m unittest discover tests -v
```

**What the student should learn:**
- How to scale an experiment framework without duplicating code (extension points vs copies).
- How chart design changes with more categories (horizontal bars, direct labels, per-fault colors).
- End-to-end verification discipline: one command, all faults, clean state after.

---

## Phase 16: Final Docs + Cleanup Audit

**Goal:** Update all final documentation for seven faults and run a last cleanliness audit.

**Tasks:**
- [x] Update `README.md`: seven faults, new charts, updated viva Q&A.
- [x] Write `docs/process_hang_notes.md` (how injected, how detected, how recovered, what OS concept, observed numbers).
- [x] Write `docs/disk_full_notes.md` (same structure).
- [x] Write `docs/fd_exhaustion_notes.md` (same structure).
- [x] Write `docs/zombie_leak_notes.md` (same structure).
- [x] Final cleanup audit: unused-import check across the codebase.
- [x] Final cleanup audit: leftover-resources check after a full run — no processes, no cgroups, no mounts, no zombies.
- [x] Update all docs to reflect the final state (architecture.md, memory.md).

**Files touched:** `README.md`, `docs/process_hang_notes.md`, `docs/disk_full_notes.md`, `docs/fd_exhaustion_notes.md`, `docs/zombie_leak_notes.md`, `docs/architecture.md`, `docs/memory.md`.

**Definition of done:**
- README reflects the seven-fault project with current charts and Q&A.
- The four learning-notes files exist with observed numbers from real runs.
- Unused-import check passes; no dead code.
- After a full run: zero leftover processes, cgroups, mounts, zombies.
- A student can clone the repo, run one command, and see all seven faults.

**How to verify:**
```bash
docker compose run lab python -m experiment.runner --fault all --trials 15
# Then verify: no leftover processes (ps), cgroups (ls /sys/fs/cgroup), mounts (mount), zombies.
docker compose run lab python -m unittest discover tests -v
```

**What the student should learn:**
- How to document a project for someone who has never seen it.
- How to write learning notes from observed data (MTTD/MTTR numbers, ENOSPC/EMFILE observations).
- How to audit a codebase for cleanliness (dead code, leftover resources).
- Confidence to explain all seven faults in a viva.
