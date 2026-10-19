# Memory — OS Fault Injection Lab

This file tracks the live state of the project. Read it FIRST before doing any work.
Update it at the end of every phase.

---

## Current Phase

**All Phases Complete (Phases 1–10 Finished)**. Project is fully hardened, tested, documented, and ready for viva demonstration.

---

## Phase Status

| Phase | Name                          | Status      |
|-------|-------------------------------|-------------|
| 1     | Project scaffold              | Completed   |
| 2     | Event log + config            | Completed   |
| 3     | Process kill injector         | Completed   |
| 4     | Monitor + detection           | Completed   |
| 5     | Recovery + first full loop    | Completed   |
| 6     | Experiment runner + metrics   | Completed   |
| 7     | Memory pressure fault         | Completed   |
| 8     | CPU hog fault                 | Completed   |
| 9     | Results and charts            | Completed   |
| 10    | Safety, tests, README, final  | Completed   |

---

## Completed Tasks

- **Phase 1: Project Scaffold**
  - Created directory scaffold (`injector/`, `monitor/`, `recovery/`, `experiment/`, `target/`, `scripts/`, `results/`) with `__init__.py` files.
  - Created `requirements.txt` (`psutil>=5.9.0`, `matplotlib>=3.7.0`).
  - Created `Dockerfile` (based on `python:3.11-slim`, with `stress-ng` and `procps`).
  - Created `docker-compose.yml` (privileged mode, mounting `./results`).
  - Implemented `target/heartbeat_app.py` (prints heartbeat every 1s, handles SIGTERM gracefully).
  - Implemented `scripts/safety_check.py` (exits 0 with `OK: Running inside Docker` in container, exits 1 outside).
  - Implemented `config.py` with typed constants.
  - Created `.gitignore` and `results/.gitkeep`.
  - Verified Docker container build and heartbeat execution; verified safety check behavior inside and outside container.

- **Phase 2: Shared Event Log + Central Config**
  - Implemented `event_log.py` with `log_event()`, `read_events()`, `clear_log()`.
  - Used JSONL format with fields: `timestamp`, `trial_id`, `fault_type`, `event`, `details`.
  - Added atomic append with explicit flush on write.
  - Added filtering by `trial_id` and `fault_type`.
  - Finalized `config.py` with polling threshold, duration timeout, and typed path constants.
  - Verified module end-to-end inside Docker container via `docker compose run --rm lab python -m event_log`.

- **Phase 3: Process Kill Injector**
  - Implemented `injector/process_kill.py` with function `inject(target_pid, trial_id)`.
  - Implemented uncatchable kill using `os.kill(target_pid, signal.SIGKILL)`.
  - Implemented atomic logging of `INJECTED` and `FAILED` events via `event_log.log_event()`.
  - Implemented robust error handling for missing/already-terminated processes (`ProcessLookupError`).
  - Added manual test block spawning dummy target, killing it, and verifying PID termination and event logging.
  - Verified inside Docker container via `docker compose run --rm lab python -m injector.process_kill`.

- **Phase 4: Monitor + Detection for Process Death**
  - Implemented `monitor/detector.py` with `is_process_alive()` and `detect_process_death()`.
  - Handled Linux zombie process state (`STATUS_ZOMBIE` treated as dead; reaps owned child with `proc.poll()`).
  - Implemented `monitor/monitor.py` polling loop measuring system CPU, memory, and target liveness at `config.MONITOR_POLL_INTERVAL_SEC`.
  - Logged `DETECTED` event on death with accurate timestamp.
  - Verified end-to-end inside Docker via `docker compose run --rm lab python -m monitor.monitor` (calculated MTTD ~0.008s).
  - Verified zombie detection explicitly with direct test.

- **Phase 5: Recovery for Process Kill — First Full Loop**
  - Implemented `recovery/supervisor.py` with `restart_target() -> int` supporting configurable retries and cooldown.
  - Verified that restarted process is healthy and active using `is_process_alive()` (not a zombie) before writing `RECOVERED` event.
  - Implemented full loop orchestration (`run_full_loop()`) connecting: target launch -> inject -> detect -> recover -> verify -> cleanup.
  - Verified end-to-end inside Docker via `docker compose run --rm lab python -m recovery.supervisor`.
  - Confirmed event sequence (`STARTED`, `INJECTED`, `DETECTED`, `RECOVERED`) and timing metrics (MTTD: 0.006s, MTTR: 0.124s).

- **Phase 6: Experiment Runner + Metrics**
  - Implemented `experiment/metrics.py` for per-trial MTTD/MTTR calculation and summary aggregates (mean, median, min, max, success rate).
  - Implemented `experiment/results.py` writing CSV results to `results/results.csv` and printing terminal tables adhering to `design.md`.
  - Implemented `experiment/runner.py` running N trials with background monitoring before injection, process tree cleanup, and timeout protection.
  - Refactored `recovery/supervisor.py` to reuse `runner.run_trial()` without code duplication.
  - Resolved phase-lock measurement bug by introducing uniform random pre-injection jitter in `[0, MONITOR_POLL_INTERVAL_SEC]` (`random.uniform`).
  - Verified 15 trials of `process_kill` inside Docker via `docker compose run --rm lab python -m experiment.runner --fault process_kill --trials 15` (100% success rate, MTTD mean 0.261s [min 0.046s, max 0.480s], MTTR mean 0.367s [min 0.152s, max 0.586s]).

- **Phase 7: Memory Pressure Fault**
  - Implemented `injector/memory_pressure.py`: delegates cgroups v2 memory controller by moving root procs to `init/`, creates per-trial cgroup `/sys/fs/cgroup/fault_{trial_id}`, sets hard cap `memory.max` (64MB) and disables swap (`memory.swap.max = 0`). Spawns memory-allocating hog process inside limited cgroup while victim target runs outside it.
  - Extended `monitor/detector.py`: implemented `check_cgroup_memory_pressure()` and `detect_memory_pressure()` reading `memory.current / memory.max` ratio and `oom_kill` counter from `memory.events`. Neither `psutil.virtual_memory()` nor `dmesg` is used.
  - Updated `monitor/monitor.py`: added cgroup-aware monitoring in `monitor_process()` polling loop.
  - Implemented `recovery/resource_recovery.py`: terminates hog if alive, inspects `memory.events`, verifies target health (restarting via supervisor if affected), removes cgroup directory with process kill and retried `rmdir()`, and logs `RECOVERED`.
  - Updated `experiment/runner.py` and `experiment/results.py`: integrated memory pressure fault execution with background monitoring, random pre-injection jitter, cgroup cleanup verification, and non-destructive CSV updating.
  - Documented observations in `docs/oom_killer_notes.md`: explains cgroups v2 memory control, `memory.events` counters, victim selection, and why the target remained intact.
  - Verified 15 trials of `memory_pressure` inside Docker via `docker compose run --rm lab python -m experiment.runner --fault memory_pressure --trials 15` (100% success rate, MTTD mean 0.795s [min 0.589s, max 1.040s], MTTR mean 0.801s [min 0.597s, max 1.046s], verified 0 leftover cgroups).

- **Phase 8: CPU Hog Fault**
  - Added `STRESS_NG_TIMEOUT_SEC` to `config.py` ensuring `stress-ng` never self-terminates before recovery intervenes.
  - Implemented `injector/cpu_hog.py`: spawns `stress-ng --cpu N --timeout T` with `N = os.cpu_count()`, saturating all available cores and logging `INJECTED`.
  - Primed `psutil.cpu_percent(interval=None)` before the polling loop in `monitor/monitor.py` to establish a non-zero time baseline and eliminate initial `0.0%` false readings.
  - Extended `monitor/detector.py` with `check_cpu_pressure` and `detect_cpu_hog` detecting sustained CPU >= 90.0% for `CONSECUTIVE_POLLS_THRESHOLD` (3) polls.
  - Extended `recovery/resource_recovery.py` with `kill_stress_ng`, `reap_zombie_children`, and `recover_cpu`: kills `stress-ng` and worker children recursively, reaps adopted zombie processes via `os.waitpid(-1, os.WNOHANG)`, verifies CPU drops below 90% before logging `RECOVERED`.
  - Updated `experiment/runner.py`: added `cpu_hog` trial orchestration, background monitoring with uniform random jitter, and post-experiment verification of 0 lingering `stress-ng` processes.
  - Documented observations in `docs/cpu_scheduling_notes.md` (load average exponential damping vs. instantaneous CPU percent, CFS virtual runtime preemption) and appended ramp-up latency explanation to `docs/oom_killer_notes.md`.
  - Verified 15 trials of `cpu_hog` inside Docker via `docker compose run --rm lab python -m experiment.runner --fault cpu_hog --trials 15` (100% success rate, MTTD mean 1.769s [min 1.527s, max 1.986s], MTTR mean 1.896s [min 1.648s, max 2.132s], verified 0 leftover stress-ng processes).

- **Phase 9: Results and Charts**
  - Updated `experiment/results.py`: implemented `apply_chart_style()` following `design.md` exactly (`#FAFAF8` background, `#2D2D2D` dark grey text, horizontal-only `#E0E0E0` gridlines, no top/right spines, 150 DPI).
  - Implemented dynamic, finding-driven chart titles constructed from computed data.
  - Generated `results/mttd_by_fault.png` (bar chart with individual trial dots; mean labels positioned above maximum scatter point to eliminate overlap).
  - Generated `results/mttr_by_fault.png` (bar chart with individual trial dots and headroom).
  - Generated `results/success_rate.png` (horizontal bar chart with direct percentage labels).
  - Generated `results/mttd_vs_mttr.png` (scatter plot with reference line $y=x$, illustrating ~0.08s constant recovery action overhead across all faults).
  - Implemented `print_comparison_summary()` printing factual, documented explanations for latency differences across faults.
  - Added standalone `python -m experiment.results` entry point to regenerate charts and reprint comparison summary from CSV on demand.
  - Updated `experiment/runner.py`: added `--fault all` choice to run complete 45-trial suite (15 trials per fault) sequentially in a single command.
  - Visually inspected all 4 PNG charts and confirmed design system compliance, legibility, and absence of label collisions.

- **Phase 10: Safety, Tests, README, Final Cleanup**
  - Finalized `scripts/safety_check.py`: checks container isolation (`/.dockerenv`), cgroups v2 (`cgroup.controllers`), `stress-ng` binary, and `psutil` import. Rejects host execution with exit code 1.
  - Implemented unit test suite in `tests/` using standard library `unittest` (22 tests passing in 0.15s, 0 failures, 0 warnings):
    - `tests/test_event_log.py`: tests atomic append, schema validation, multi-filter queries, file truncation.
    - `tests/test_metrics.py`: tests MTTD/MTTR formulas, edge cases (missing DETECTED/RECOVERED), summary statistics.
    - `tests/test_detector.py`: tests 3-poll CPU debouncing, cgroup ratio debouncing, `memory.events` OOM detection, zombie filtering.
    - `tests/test_supervisor.py`: tests process launch, retry cooldown delays, retry exhaustion exception, and liveness verification.
  - Created `scripts/demo.py`: interactive single-command demonstration executing 1 trial per fault type with instant chart generation.
  - Authored comprehensive, publication-grade `README.md` adhering to `design.md` styling and containing architecture, quickstart, sample results, and viva examination Q&A.
  - Authored `docs/process_kill_notes.md` completing the conceptual learning notes triad alongside `oom_killer_notes.md` and `cpu_scheduling_notes.md`.
  - Executed full 45-trial suite (`--fault all --trials 15`) with 100% recovery success rate across all 45 trials, verifying zero leftover cgroups and zero leftover stress-ng processes.
  - Audited codebase and eliminated all unused imports and dead code.

---

## Decisions

Decisions made during development, with rationale. Add entries here as work progresses.

| # | Decision | Rationale | Phase |
|---|----------|-----------|-------|
| 1 | Detect memory pressure via cgroup `memory.current/memory.max` ratio, not `psutil.virtual_memory()`. Observe OOM kills via `memory.events` oom_kill counter, not `dmesg`. | `psutil.virtual_memory()` reads whole-VM memory and cannot see cgroup limits. `dmesg` may require elevated privileges and is less reliable than the cgroup's own `memory.events` file. | Pre-1 |
| 2 | Memory hog runs inside the limited cgroup; target process runs outside it. | Keeps the OOM kill target clear: only the hog is killed by the OOM killer, and recovery simply verifies the hog is dead and restarts the target if affected. | Pre-1 |
| 3 | Removed `injector/base.py`. | Unnecessary abstraction. Each injector is a simple module with an `inject()` function; no base class or interface needed. | Pre-1 |
| 4 | Removed `scripts/setup.sh`. | The Dockerfile handles all setup. A separate shell script is redundant. | Pre-1 |
| 5 | Phase 10: use `python -m unittest discover tests` instead of `pytest`; demo script is `scripts/demo.py` not `demo.sh`. | `unittest` is stdlib — no extra dependency. Python demo script is consistent with the all-Python rule. | Pre-1 |
| 6 | `STRESS_NG_CPU_WORKERS` defaults to `os.cpu_count()`. | Using all available CPUs ensures the hog actually saturates the system, making detection realistic. | Pre-1 |
| 7 | Set `ENV PYTHONUNBUFFERED=1` in Dockerfile. | Prevents Python from buffering stdout/stderr so logs appear in real time in `docker compose up`. | Phase 1 |
| 8 | Mount `.:/app` in `docker-compose.yml`. | Enables live code sync between host and container during development without rebuilding image on every source change. | Phase 2 |
| 9 | Treat zombie processes (`STATUS_ZOMBIE`) as dead, and reap child with `Popen.poll()`. | `psutil.pid_exists(pid)` returns `True` for zombies because their kernel task struct remains until the parent reaps them. In fault detection, a zombie is functionally dead. | Phase 4 |
| 10 | Start monitor in a background thread before injecting fault. | Ensures the monitor is actively running when the fault occurs, but a fixed start-to-injection offset caused phase-locking where injection always occurred at the same point in the 0.5s poll cycle. Corrected by Decision #12. | Phase 6 |
| 11 | Move single-trial execution to `experiment.runner.run_trial()`, and delegate `recovery.supervisor.run_full_loop()` to it. | Eliminates duplication of the core execution loop across supervisor and experiment runner. | Phase 6 |
| 12 | Randomize pre-injection delay uniformly in `[INJECTION_JITTER_MIN_SEC, INJECTION_JITTER_MAX_SEC]` (0.0 to 0.5s). | A fixed pre-injection delay caused injection to lock onto the same phase of the 0.5s poll cycle every trial (~0.45s MTTD). Randomizing uniformly breaks phase lock and simulates arbitrary real-world fault arrival, yielding expected MTTD mean ~0.25s (half the poll interval) with min ~0s and max ~0.5s. | Phase 6 (Fix) |
| 13 | Migrate root cgroup processes to `/sys/fs/cgroup/init` before writing `+memory +cpu` to `cgroup.subtree_control`. | Satisfies the cgroups v2 "no internal processes" constraint; child cgroups cannot enable controllers if the root cgroup contains processes. | Phase 7 |
| 14 | Set `memory.swap.max = 0` for per-trial cgroups. | Without disabling swap, the Linux kernel pages out anonymous memory to swap instead of triggering an out-of-memory kill on limit breach. Setting swap cap to 0 forces deterministic OOM killer invocation. | Phase 7 |
| 15 | Rely on `memory.events` monotonic `oom_kill` counter alongside `memory.current / memory.max` ratio. | Once an OOM kill terminates a process, `memory.current` immediately drops toward zero as pages are freed. The `memory.events` `oom_kill` counter is monotonic and persistent for the cgroup lifetime, ensuring no OOM event is missed. | Phase 7 |
| 16 | Preserve existing CSV results across multiple `--fault` runs by keying on `trial_id`. | Enables running separate experiment runs for different fault types while consolidating results into a single `results.csv`. | Phase 7 |
| 17 | Set `STRESS_NG_TIMEOUT_SEC` in `config.py` to `int(MAX_TRIAL_DURATION_SEC) + 30` (60s). | Guarantees that `stress-ng` cannot exit on its own mid-trial before detection and recovery occur. | Phase 8 |
| 18 | Prime `psutil.cpu_percent(interval=None)` before the monitor loop starts. | `psutil.cpu_percent(interval=None)` returns `0.0` on its first invocation in a process because it has no prior timestamp baseline. Priming it once before monitoring starts ensures the first poll interval reading is genuine. | Phase 8 |
| 19 | Reap adopted worker children using `os.waitpid(-1, os.WNOHANG)`. | In container environments, when the `stress-ng` supervisor process is killed, worker children are reparented to PID 1. When killed with SIGKILL, they become zombies until PID 1 reaps them. Non-blocking `waitpid` cleans them up completely. | Phase 8 |
| 20 | Verify CPU drops below `CPU_THRESHOLD_PERCENT` before logging `RECOVERED`. | Verifies that termination was effective and system resources returned to normal operating levels. | Phase 8 |
| 21 | Position mean value text labels above `max(points)` rather than `bar_height`. | When jittered trial dots exceed the mean bar height, placing labels directly above the bar causes visual collision with scatter points. Placing at `max(points) + 0.06` with `ylim(0, max_point * 1.22)` provides clean headroom and legibility. | Phase 9 |
| 22 | Add `DejaVu Sans` and `DejaVu Serif` font fallbacks in `apply_chart_style()`. | Debian slim containers lack proprietary fonts (Helvetica Neue, Arial). Explicitly listing DejaVu suppresses noisy warnings while maintaining typography per `design.md`. | Phase 9 |
| 23 | Support `--fault all` in `experiment/runner.py` and standalone chart regeneration via `python -m experiment.results`. | Allows regenerating charts and summaries on demand from existing data without re-running experiments, and running all 45 trials sequentially in one command. | Phase 9 |
| 24 | Finalize `scripts/safety_check.py` to assert Docker, cgroups v2, stress-ng in PATH, and psutil import. | Guarantees full pre-flight verification of all kernel and runtime dependencies before fault injection begins, immediately protecting the host OS if run outside Docker. | Phase 10 |
| 25 | Standard library `unittest` test suite across 4 test modules with 22 test cases and zero external dependencies. | Honors zero-extra-framework constraint while thoroughly verifying core logic (atomic event logging, MTTD/MTTR formulas, debouncing/cgroup threshold detection, and supervisor retries/cooldown). | Phase 10 |
| 26 | Add project root dynamically to `sys.path` in `scripts/demo.py`. | Ensures `python scripts/demo.py` is directly executable whether run from repo root, subdirectories, or via `docker compose run`. | Phase 10 |
| 27 | Author dedicated learning notes `docs/process_kill_notes.md` completing conceptual triad. | Provides comprehensive student viva study reference covering signals, zombie reaping, supervisor backoff, and uniform jitter. | Phase 10 |

---

## Assumptions

- The host machine has Docker and docker-compose installed.
- The container will run on Linux (Docker on Windows/Mac uses a Linux VM, which is fine).
- cgroups v2 is available inside the container (modern Docker default).
- The project will be developed and tested on a single machine.
- `stress-ng` is available in Debian/Ubuntu package repositories.

---

## Known Issues

_None._

---

## How to Run

```bash
# Build and run the container (runs heartbeat app):
docker compose up --build

# Run safety check inside container:
docker compose run --rm lab python scripts/safety_check.py

# Run safety check on host (fails by design):
python scripts/safety_check.py

# Verify event log module inside container:
docker compose run --rm lab python -m event_log

# Verify process kill injector inside container:
docker compose run --rm lab python -m injector.process_kill

# Verify memory pressure injector inside container:
docker compose run --rm lab python -m injector.memory_pressure

# Verify CPU hog injector inside container:
docker compose run --rm lab python -m injector.cpu_hog

# Verify monitor and process death detector inside container:
docker compose run --rm lab python -m monitor.monitor

# Verify process kill supervisor and first full loop inside container:
docker compose run --rm lab python -m recovery.supervisor

# Verify resource recovery standalone inside container:
docker compose run --rm lab python -m recovery.resource_recovery

# Run 15-trial experiment for process_kill:
docker compose run --rm lab python -m experiment.runner --fault process_kill --trials 15

# Run 15-trial experiment for memory_pressure:
docker compose run --rm lab python -m experiment.runner --fault memory_pressure --trials 15

# Run 15-trial experiment for cpu_hog:
docker compose run --rm lab python -m experiment.runner --fault cpu_hog --trials 15

# Run full 45-trial suite (all faults, 15 trials each) and generate all charts:
docker compose run --rm lab python -m experiment.runner --fault all --trials 15

# Regenerate publication charts directly from existing CSV without re-running:
docker compose run --rm lab python -m experiment.results

# Run interactive demonstration (1 trial per fault type with instant chart generation):
docker compose run --rm lab python scripts/demo.py

# Run unit test suite (22 unit tests via stdlib unittest):
docker compose run --rm lab python -m unittest discover tests -v
```

---

## Next Step

**Project Complete!** All 10 phases finished, tested, documented, and hardened.
- Everything is runnable inside Docker via `docker compose run --rm lab python scripts/demo.py` or `python -m experiment.runner --fault all --trials 15`.
- All tests pass via `docker compose run --rm lab python -m unittest discover tests -v`.
- Clean repository, zero dead code, zero unused imports.
- Ready for viva presentation and student demonstration.

---

## Files Created / Modified Log

| File | Created/Modified | Phase | Notes |
|------|-----------------|-------|-------|
| `docs/prd.md` | Created / Modified | 0 (docs) | Product requirements |
| `docs/architecture.md` | Created / Modified | 0 (docs) | System architecture |
| `docs/rules.md` | Created | 0 (docs) | Coding standards |
| `docs/design.md` | Created | 0 (docs) | Visual design system |
| `docs/tasks.md` | Created / Modified | 0 (docs), Phases 1-10 | 10-phase task breakdown (all complete) |
| `docs/memory.md` | Created / Modified | 0 (docs), Phases 1-10 | Project state tracker (all complete) |
| `requirements.txt` | Created | Phase 1 | Python packages (`psutil`, `matplotlib`) |
| `Dockerfile` | Created | Phase 1 | Linux + Python 3.11 + stress-ng + procps |
| `docker-compose.yml` | Created / Modified | Phase 1, Phase 2 | Mounted `.:/app` for live code sync |
| `config.py` | Created / Modified | Phase 1, Phase 2, Phase 6, Phase 8 | Added `STRESS_NG_TIMEOUT_SEC` |
| `.gitignore` | Created | Phase 1 | Artifacts and cache exclusions |
| `results/.gitkeep` | Created | Phase 1 | Gitkeep for results directory |
| `target/__init__.py` | Created | Phase 1 | Package init |
| `target/heartbeat_app.py` | Created | Phase 1 | Dummy target with heartbeat & SIGTERM handler |
| `injector/__init__.py` | Created | Phase 1 | Package init |
| `monitor/__init__.py` | Created | Phase 1 | Package init |
| `recovery/__init__.py` | Created | Phase 1 | Package init |
| `experiment/__init__.py` | Created | Phase 1 | Package init |
| `scripts/safety_check.py` | Created / Modified | Phase 1, Phase 10 | Container isolation, cgroups v2, stress-ng, psutil validation |
| `event_log.py` | Created | Phase 2 | Shared JSONL event logger and reader |
| `injector/process_kill.py` | Created | Phase 3 | Process kill injector using os.kill(pid, SIGKILL) |
| `monitor/detector.py` | Created / Modified | Phase 4, Phase 7, Phase 8 | Added CPU pressure threshold detection |
| `monitor/monitor.py` | Created / Modified | Phase 4, Phase 7, Phase 8 | Primed CPU polling and added cpu_hog monitoring |
| `recovery/supervisor.py` | Created / Modified | Phase 5, Phase 6 | Supervisor restart recovery; delegates loop to runner |
| `experiment/metrics.py` | Created / Modified | Phase 6, Phase 10 | Per-trial metrics calculation, aggregates, optional events injection |
| `experiment/results.py` | Created / Modified | Phase 6, Phase 7, Phase 9 | Implemented matplotlib chart generators and summary printing |
| `experiment/runner.py` | Created / Modified | Phases 6-10 | Integrated multi-fault runner, random jitter, cleaned unused imports |
| `injector/memory_pressure.py` | Created / Modified | Phase 7, Phase 10 | Cgroup memory limit injector; cleaned unused imports |
| `recovery/resource_recovery.py` | Created / Modified | Phase 7, Phase 8 | Added stress-ng recursive termination, zombie reaping, and CPU recovery |
| `docs/oom_killer_notes.md` | Created / Modified | Phase 7, Phase 8 | Learning notes: cgroups v2 memory limits, OOM killer victim selection |
| `injector/cpu_hog.py` | Created | Phase 8 | CPU saturation injector using stress-ng |
| `docs/cpu_scheduling_notes.md` | Created | Phase 8 | Learning notes: CPU scheduling, load avg vs percent, and CFS |
| `results/mttd_by_fault.png` | Created | Phase 9 | Publication chart: MTTD by fault with individual trial points |
| `results/mttr_by_fault.png` | Created | Phase 9 | Publication chart: MTTR by fault with individual trial points |
| `results/success_rate.png` | Created | Phase 9 | Publication chart: horizontal bar recovery success rate |
| `results/mttd_vs_mttr.png` | Created | Phase 9 | Publication chart: scatter plot with y=x reference line |
| `tests/__init__.py` | Created | Phase 10 | Package init for unit tests |
| `tests/test_event_log.py` | Created | Phase 10 | Unit tests for event logging, reading, filtering, clearing |
| `tests/test_metrics.py` | Created | Phase 10 | Unit tests for MTTD/MTTR formulas and statistical aggregates |
| `tests/test_detector.py` | Created | Phase 10 | Unit tests for CPU debounce, cgroups v2 ratio, and OOM detection |
| `tests/test_supervisor.py` | Created | Phase 10 | Unit tests for supervisor restart, cooldown, and retry exhaustion |
| `scripts/demo.py` | Created | Phase 10 | Interactive single-command demonstration runner |
| `docs/process_kill_notes.md` | Created | Phase 10 | Learning notes: Unix signals, PIDs, zombie processes, supervision |
| `docs/images/*.png` | Created | Phase 10 | Final publication chart PNGs for README embeds |
| `README.md` | Created / Modified | Phase 10 | Comprehensive, publication-grade project documentation with embedded charts |


