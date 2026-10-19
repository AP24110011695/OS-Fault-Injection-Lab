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
