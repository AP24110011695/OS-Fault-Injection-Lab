# Memory — OS Fault Injection Lab

This file tracks the live state of the project. Read it FIRST before doing any work.
Update it at the end of every phase.

---

## Current Phase

**All 16 Phases Complete.**
Seven faults implemented, integrated, and measured (120 trials, 100% success); README rewritten for the seven-fault project with CSV-computed results and an honest Limitations section; 40 unit tests pass; no unused imports; docs consistent. Project is ready for viva demonstration.

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
| 11    | Process hang fault            | Completed   |
| 12    | Disk full fault               | Completed   |
| 13    | FD exhaustion fault           | Completed   |
| 14    | Zombie leak fault             | Completed   |
| 15    | Seven-fault integration       | Completed   |
| 16    | Final docs + cleanup audit    | Completed   |

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

- **Docs Update: Seven-Fault Extension (Phases 11–16 Planned)**
  - Updated `prd.md`: seven faults, four new fault tables (same style), updated success metrics (strategy comparison row), non-goals, learning goals, and line budget (2500 lines excluding tests).
  - Updated `architecture.md`: four new injector modules, new config constants, extended event-log fault types, detector/recovery responsibilities, three new safety rules (tmpfs-only, per-process rlimit, zombie cap), and a seven-fault reference table for the teacher.
  - Updated `design.md`: four new per-fault colors; all-fault charts may use one color per fault; horizontal bars preferred for seven categories.
  - Updated `tasks.md`: added Phases 11–16.
  - Updated `rules.md`: scope-control fault list extended to the seven faults (the old line would have blocked Phases 11–14).
  - No project code was changed.

- **Phase 11: Process Hang Fault**
  - Added `HEARTBEAT_FILE_PATH` to `config.py` (next to the other path constants) and made the smallest possible change to `target/heartbeat_app.py`: append the ISO timestamp to the heartbeat file on every tick (parent dir created once at startup).
  - Implemented `injector/process_hang.py`: `reset_heartbeat_file()` (per-trial reset) and `inject(target_pid, trial_id)` sending uncatchable `SIGSTOP`, logging observed psutil status in the `INJECTED` details. Standalone `__main__` verifies stopped → SIGCONT → running → fresh heartbeat → SIGKILL cleanup.
  - Extended `monitor/detector.py` with `check_heartbeat_staleness()` (stateless, newest-timestamp age vs `HEARTBEAT_TIMEOUT_SEC`; missing/unparseable file counts as stale) and `detect_process_hang()`. No PID liveness check by design — the target is still alive while stopped.
  - Extended `monitor/monitor.py` with the `process_hang` polling branch reading `HEARTBEAT_FILE_PATH`.
  - Extended `recovery/supervisor.py`: `restart_target()` gained `fault_type` and `log_recovery` kwargs (defaults preserve existing behavior); added `wait_for_fresh_heartbeat()` and `recover_process_hang()` supporting both strategies — "resume" (`SIGCONT`) and "restart" (`SIGKILL` + supervisor). `RECOVERED` is logged only after a fresh heartbeat is observed.
  - Extended `experiment/runner.py`: `--strategy resume|restart` CLI, strategy embedded in trial id (`process_hang_resume_001`), heartbeat reset before target launch, recovery branch, and cleanup that `SIGKILL`s process_hang targets directly (a `SIGSTOP`'d process queues `SIGTERM` until continued) with per-trial leftover verification plus a post-experiment assertion of zero stopped processes.
  - Added `process_hang` to `experiment/results.py` color/label/order maps (muted violet `#8B7BA5` per `design.md`).
  - Added 5 heartbeat-staleness unit tests to `tests/test_detector.py` (fresh, stale, exact-timeout boundary, missing file, unparseable lines). Suite: 27 tests, all passing.
  - Ran 15 trials per strategy inside Docker: resume — MTTD mean 3.052s [min 2.491, max 3.385], MTTR mean 3.129s; restart — MTTD mean 3.101s [min 2.478, max 3.485], MTTR mean 3.210s; 100% success both; verified 0 stopped/leftover processes; results.csv holds all 75 rows (15 per original fault + 30 process_hang).
  - Smoke trial `--fault process_kill --trials 1` passed (MTTD 0.033s, MTTR 0.138s, 100%) proving no regression.
  - Authored `docs/process_hang_notes.md` (pulled forward from Phase 16) with observed numbers and the explanation of why MTTD ≥ ~`HEARTBEAT_TIMEOUT_SEC`.

- **Phase 12: Disk Full Fault**
  - Added `DISK_FAULT_SIZE_MB` (16), `DISK_MOUNT_PATH` (`/tmp/fault_disk`), and `DISK_THRESHOLD_PERCENT` (90.0) to `config.py`.
  - Implemented `injector/disk_full.py`: `mount_fault_disk()` mounts a size-capped tmpfs via `mount -t tmpfs -o size=Nm` and ABORTS (logs `FAILED`, raises) on any failure; `is_tmpfs_mount()` verifies via `/proc/mounts` that the path is a tmpfs mountpoint with the exact expected size cap — the writer is spawned only after verification passes. Writer code fills 1MB chunks every 0.05s (realistic ramp-up), handles `ENOSPC` by retrying while staying alive like a leaking service. Standalone `__main__` verifies mount → fill to 100% → recover → full cleanup.
  - Extended `monitor/detector.py` with `check_disk_usage()` (`psutil.disk_usage(mount).percent` vs threshold over N consecutive polls; missing mount never causes false detection) and `detect_disk_full()`.
  - Extended `monitor/monitor.py` with the `disk_full` polling branch.
  - Extended `recovery/resource_recovery.py` with `kill_writer()`, `delete_mount_files()`, `recover_disk_full()` (kill writer → delete files → verify usage below threshold → log `RECOVERED`), and `cleanup_fault_disk()` (kill writer, delete files, umount, rmdir, verify gone from `/proc/mounts`).
  - Extended `experiment/runner.py`: `disk_full` orchestration with abort-on-injection-failure, `cleanup_fault_disk()` in the `finally` block (runs on exceptions and Ctrl+C too) with per-trial leftover verification, and post-experiment assertions of zero leftover mounts. Leak proof: container root filesystem (`psutil.disk_usage("/")`) snapshotted before and compared after the run.
  - Added `disk_full` to `experiment/results.py` color/label/order maps (muted ochre `#B49A5A` per `design.md`).
  - Added 3 disk-usage unit tests to `tests/test_detector.py` (debounce + detection, below-threshold reset, missing path). Suite: 30 tests, all passing.
  - Verified the safety gate explicitly: `is_tmpfs_mount` returns False for a plain directory, a wrong path, and a right path with wrong size cap; True only for the verified 16MB tmpfs.
  - Ran 15 trials inside Docker: 100% success, MTTD mean 1.947s [min 1.767, max 2.166], MTTR mean 1.957s, recovery overhead ~0.010s. Leak proof: 0 leftover mounts; container root filesystem 33,619,210,240 → 33,619,251,200 bytes (delta +40,960 ≈ 0.0001%, unrelated runtime noise — all ~16MB of fault data lived inside the tmpfs).
  - Smoke trial `--fault process_kill --trials 1` passed (MTTD 0.189s, MTTR 0.302s, 100%) proving no regression.
  - Authored `docs/disk_full_notes.md` with observed numbers, the MTTD-includes-fill-time explanation, tmpfs/ENOSPC/df-vs-du concepts, and the leak proof.

- **Phase 13: FD Exhaustion Fault**
  - Added `FD_LIMIT` (256), `FD_THRESHOLD_PERCENT` (90.0), and `FD_CLEAN_MAX_FDS` (20) to `config.py`.
  - Implemented `injector/fd_exhaustion.py`: `start_leaker()` launches the faulty service, whose code lowers ITS OWN `RLIMIT_NOFILE` to `FD_LIMIT` at startup (only that process — verified by reading the limit back via psutil), idles until `SIGUSR1`, then opens `/dev/null` every 20ms keeping the fds in a list until `EMFILE`, and keeps running without printing (nothing in the loop needs a new fd). `inject()` sends `SIGUSR1` and logs the leaker's own soft limit in the `INJECTED` details. Standalone `__main__` verifies: own limit = 256, fd count climbs to 255/256 (EMFILE plateau), leaker still alive, recovery yields a fresh instance with 3 fds.
  - Extended `monitor/detector.py` with `check_fd_ratio()` (the leaker's `num_fds()` divided by its own `RLIMIT_NOFILE` soft limit read from the process; unlimited soft limit cannot produce a ratio; dead process never falsely detects) and `detect_fd_exhaustion()`.
  - Extended `monitor/monitor.py` with the `fd_exhaustion` polling branch.
  - Extended `recovery/supervisor.py` with `recover_fd_exhaustion()`: kills the leaker and reaps it, starts a fresh clean instance via `restart_target()` (standard target command, no leak), verifies its fd count is below `FD_CLEAN_MAX_FDS`, then logs `RECOVERED`; raises `RuntimeError` on verification failure.
  - Extended `experiment/runner.py`: for `fd_exhaustion` Step 1 starts the leaker (it IS the faulty service) so the monitor can watch it before injection; inject branch sends the leak trigger; recovery branch tracks the fresh instance via `get_last_process()`; per-trial leftover-leaker verification in `finally`; post-experiment assertion that no process whose cmdline contains the leaker signature remains.
  - Added `fd_exhaustion` to `experiment/results.py` color/label/order maps (dusty rose `#B07A8C` per `design.md`).
  - Added 4 fd-ratio unit tests to `tests/test_detector.py` (debounce + detection, below-threshold reset, dead process, unlimited limit guard). Suite: 34 tests, all passing.
  - Ran 15 trials inside Docker: 100% success, MTTD mean 5.966s [min 5.721, max 6.156], MTTR mean 6.076s (recovery overhead ~0.11s, fresh instance verified at 3 fds). Verified 0 leftover leaker processes.
  - Smoke trial `--fault process_kill --trials 1` passed (MTTD 0.466s, MTTR 0.573s, 100%) proving no regression.
  - Authored `docs/fd_exhaustion_notes.md` with observed numbers and the MTTD = open-rate ramp-up + debounce explanation.

- **Phase 14: Zombie Leak Fault**
  - Added `ZOMBIE_LEAK_MAX_CHILDREN` (200) and `ZOMBIE_THRESHOLD` (20) to `config.py`.
  - Implemented `injector/zombie_leak.py`: `start_zombie_leaker()` launches the leaker parent, which idles until `SIGUSR1` and then `os.fork()`s children that call `os._exit(0)` immediately — the parent never waits, `SIGCHLD` stays at `SIG_DFL`, and children are deliberately NOT created via `subprocess`/`multiprocessing` (Python would reap them automatically). Spawn rate 50ms, hard cap at `ZOMBIE_LEAK_MAX_CHILDREN`. `inject()` sends `SIGUSR1`. Standalone `__main__` verifies: zombies accumulate above the threshold while the parent stays alive, recovery leaves 0 zombies container-wide.
  - Extended `monitor/detector.py` with `count_zombie_children()` (only the parent's direct children in `STATUS_ZOMBIE`, so unrelated processes cannot cause false alarms), `check_zombie_leak()` (fires strictly above `ZOMBIE_THRESHOLD` over N consecutive polls), and `detect_zombie_leak()`.
  - Extended `monitor/monitor.py` with the `zombie_leak` polling branch.
  - Extended `recovery/resource_recovery.py` with `count_zombies()` (container-wide) and `recover_zombie_leak()`: kills the leaker parent and reaps it, reaps the orphans adopted by PID 1 via the existing `reap_zombie_children()` (Decision: chosen over `init: true` in docker-compose.yml), then verifies zero zombies remain (brief retry for asynchronous reparenting) before logging `RECOVERED`; raises `RuntimeError` on failure.
  - Extended `experiment/runner.py`: for `zombie_leak` Step 1 starts the leaker parent (it IS the faulty service) so the monitor can watch it before injection; inject and recovery branches; per-trial verification in `finally` (no leftover leaker parent AND zero zombies container-wide, `FAILED` event if violated); post-experiment assertion of both via the leaker's cmdline signature (`os.fork`) plus `count_zombies()`.
  - Added `zombie_leak` to `experiment/results.py` color/label/order maps (slate indigo `#7080A0` per `design.md`). All seven faults now have chart entries.
  - Added 3 zombie-count unit tests to `tests/test_detector.py` (debounce + detection, below-threshold reset, at-threshold boundary). Suite: 37 tests, all passing.
  - Ran 15 trials inside Docker: 100% success, MTTD mean 2.324s [min 2.073, max 2.504], MTTR mean 2.331s (recovery overhead ~0.007s). Verified 0 leftover leaker parents and 0 zombie processes. One trial's DETECTED fired at 42 zombies — the poll quantum samples the ramp, consistent with theory (ramp ~1.05s + debounce ~1.0-1.5s).
  - Smoke trial `--fault process_kill --trials 1` passed (MTTD 0.381s, MTTR 0.487s, 100%) proving no regression.
  - Authored `docs/zombie_leak_notes.md` with observed numbers: how zombies appear (exit status kept until the parent waits), the subprocess-reaps-children and SIGCHLD/SIG_IGN gotchas, reparenting to PID 1, why init processes must reap, and the MTTD = spawn-ramp + debounce explanation.

- **Phase 15: Integration — Seven-Fault Suite**
  - Raised the line budget to 3300 excluding tests (prd.md; Decision #53).
  - Rewrote `run_all_experiments`: `--fault all` now runs 8 fault groups — process_kill, memory_pressure, cpu_hog, process_hang [resume], process_hang [restart], disk_full, fd_exhaustion, zombie_leak — 15 trials each (120 total). `write_results_csv` keys on trial id, so re-running updates rows without duplicates (verified: 120 rows, 120 unique ids).
  - Evaluated and rejected the optional dispatch-table refactor (Decision #54); instead consolidated the six per-fault post-run verification blocks into one `assert_no_leftover_resources()` used by both `run_experiment` and `run_all_experiments` (Decision #55) — strictly stronger, every run asserts all resources.
  - Rewrote `experiment/results.py` around 8 chart groups: `group_of()` derives the group from the trial id; process_hang appears as two rows (resume/restart) sharing the fault's violet per design.md; 4 horizontal-bar charts (MTTD, MTTR, recovery time MTTR−MTTTD, success rate) with individual trial dots, direct value labels, value-axis gridlines, data-built titles, and the plain-text ramp-up note under the MTTD chart; scatter chart removed per task; printed comparison summary is a data-built table including the same note (Decision #56).
  - Updated `scripts/safety_check.py`: new `is_tmpfs_mounting_available()` mounts a 1MB tmpfs, verifies it via the injector's `is_tmpfs_mount()`, and umounts + rmdirs in a `finally` so nothing is left behind; failure exits 1.
  - Updated `scripts/demo.py` wording (runs via `run_all_experiments`, which now covers all 8 groups, prints the summary, and makes the charts).
  - Added `tests/test_results.py` (3 tests: `group_of` parsing, re-run dedupe, read/write roundtrip with None MTTR). Suite: 40 tests, all passing.
  - Full run `--fault all --trials 15`: 120/120 trials succeeded (100%); group means — process_kill MTTD 0.236/MTTR 0.344, memory_pressure 0.739/0.746, cpu_hog 1.787/1.915, hang-resume 3.079/3.122, hang-restart 3.183/3.327, disk_full 1.975/1.985, fd_exhaustion 5.933/6.078, zombie_leak 2.270/2.277. Leak proof: 0 leftover processes, stopped processes, zombies, mounts, cgroups; root fs delta +225,280 bytes (~0.0007%, runtime noise).
  - Copied the 4 final charts to `docs/images/` (replacing old ones; retired `mttd_vs_mttr.png` from repo and README — README now links `recovery_time_by_fault.png`).
  - Final line count: **2970** lines of Python excluding tests (under the 3300 budget; the verification consolidation net-saved lines).

- **Phase 16: Final Docs + Cleanup Audit**
  - Rewrote `README.md` for the seven-fault project: teacher table (fault / injected / detected / recovered / OS concept for all 7), results table **computed from `results/results.csv`** (120 trials, 8 groups, 100%; e.g. process_kill MTTD 0.258s, fd_exhaustion 5.968s), the ramp-up sentence pointing recovery-cost comparison at the recovery-time chart, a Safety Guarantees section (container only, tmpfs only, per-process rlimit, capped zombies, per-trial cleanup), quick-start commands, 4 charts from `docs/images/`, an honest **Limitations** section (single container/laptop, 15 trials per group, 100% ≠ real-world robustness, resume-vs-restart within noise, one fault at a time), and viva Q&A extended with alive-vs-healthy, SIGSTOP vs SIGKILL, ENOSPC, EMFILE, and zombies/PID 1.
  - Fixed `docs/process_hang_notes.md` §4 heading: "Why MTTD Is **Roughly 2.0 to 3.5 Seconds**" (was "at Least About HEARTBEAT_TIMEOUT_SEC") + one sentence explaining the range can dip below the 3.0s timeout because staleness is measured from the last heartbeat.
  - Consistency audit: architecture.md folder tree updated (7 notes files, images/, demo.py, tests/, generated results listing); memory.md How-to-Run "45-trial" line → 120-trial and test count → 40. Historical log entries (ticked Phase 9/10 checklists, decision rows) intentionally left verbatim — they are a chronological record, and rewriting them would falsify the project's history.
  - `.gitignore` verified: `results/*.log` covers `results/heartbeat.log`, all generated results ignored, `docs/images/` tracked. No changes needed.
  - Unused-import audit over the whole repo (AST-based one-off): clean. Unit tests: 40 passing. `scripts/demo.py` executed once end-to-end (8 trials, all groups, 100% success, leak-proof assertions passed).
  - Because the demo rewrites the `_001` trial rows, the full 120-trial suite was re-run afterwards to restore the canonical dataset and charts; docs/images refreshed from the final run. Final state: 120 rows / 120 unique ids / 100% success.
  - Final line count: **2970** lines of Python excluding tests (same command as prior phases).

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
| 28 | Extend the project from 3 to 7 faults (process_hang, disk_full, fd_exhaustion, zombie_leak); relax the PRD's "exactly three" constraint and raise the line budget to 2500 lines of Python excluding tests. | Instructor requires more fault types. Each new fault follows the same INJECTED → DETECTED → RECOVERED loop, so the change is additive extension, not redesign. | 11-16 (docs) |
| 29 | process_hang detects via heartbeat staleness, never PID liveness (the target is still alive when stopped); `RECOVERED` only after a fresh heartbeat; two recovery strategies compared by MTTR: "resume" (`SIGCONT`) and "restart" (supervisor). | The lesson of the fault is alive vs healthy; a liveness check cannot see a hang. | 11-16 (docs) |
| 30 | disk_full writes only to a size-capped tmpfs verified via `/proc/mounts`; a failed mount aborts the trial; the tmpfs is always unmounted, including on Ctrl+C. | Guarantees the container's normal filesystem is never written to. | 11-16 (docs) |
| 31 | fd_exhaustion leaker lowers its own `RLIMIT_NOFILE` via `resource.setrlimit` and keeps running through `EMFILE`; detection uses `num_fds()`/limit ratio. | Per-process rlimit isolates the fault; system-wide limits are never touched. | 11-16 (docs) |
| 32 | zombie_leak spawns at most `ZOMBIE_LEAK_MAX_CHILDREN` at a controlled rate; detection counts only the leaker's zombie children. | Protects the container's process table and avoids false alarms from unrelated processes. | 11-16 (docs) |
| 33 | Recovery placement: `supervisor.py` recovers process resume/restart faults (process_kill, process_hang, fd_exhaustion); `resource_recovery.py` recovers resource-exhaustion faults (memory_pressure, cpu_hog, disk_full, zombie_leak). | Keeps the extension additive — existing recovery modules are extended, not duplicated. | 11-16 (docs) |
| 34 | Four new per-fault chart colors: process_hang `#8B7BA5`, disk_full `#B49A5A`, fd_exhaustion `#B07A8C`, zombie_leak `#7080A0`. All-fault comparison charts may use one color per fault; all other charts keep the max-3 rule; seven-category charts prefer horizontal bars. | Seven faults need seven distinguishable muted colors; the relaxation is limited so single-fault charts stay quiet. | 11-16 (docs) |
| 35 | process_hang needs heartbeat timestamps in a file: the target app will append one timestamp per tick to `HEARTBEAT_FILE_PATH` (smallest possible change, Phase 11). | Heartbeats currently go to stdout only; the monitor needs a pollable file. | 11-16 (docs) |
| 36 | `rules.md` scope-control line updated to list the seven faults. | The old line ("do not add fault types beyond process kill, memory pressure, CPU hog") would have blocked Phases 11–14 during `execute phaseN`. | 11-16 (docs) |
| 37 | Recovery strategy is recorded per trial by embedding it in the trial id (`process_hang_resume_001` / `process_hang_restart_001`) and in the summary title (`process_hang [resume]`). | Simplest recording that keeps the CSV schema unchanged: `fault_type` stays `process_hang` (metrics read it from the event field), the trial id distinguishes strategies, and `write_results_csv` keys on trial id so both strategies coexist in one file. | Phase 11 |
| 38 | `restart_target()` extended with `fault_type` and `log_recovery` keyword args (defaults preserve existing behavior); `recover_process_hang` suppresses the supervisor's own `RECOVERED` and logs it after a fresh heartbeat. | process_hang's `RECOVERED` must be emitted only after progress is verified and with `fault_type="process_hang"`; extending the shared supervisor avoids duplicating restart/retry logic. | Phase 11 |
| 39 | Heartbeat file is truncated at trial start (before the target launches), and a missing/unparseable heartbeat counts as stale. | Without the reset, the previous trial's stale timestamps would trigger a false `DETECTED` before `INJECTED`. The monitor starts only after the fresh target has begun writing, so the missing-file case cannot fire pre-injection in the runner flow. | Phase 11 |
| 40 | Cleanup of process_hang targets uses `SIGKILL` directly, with per-trial leftover verification and a post-experiment assertion of zero stopped processes. | A `SIGSTOP`'d process queues `SIGTERM` until continued, so terminate-based cleanup would silently leave it frozen; SIGKILL is the only reliable cleanup. | Phase 11 |
| 41 | `docs/process_hang_notes.md` written in Phase 11 (pulled forward from Phase 16) including the MTTD ≥ ~`HEARTBEAT_TIMEOUT_SEC` explanation with observed numbers. | Detection-by-absence needs the timeout to elapse before staleness is provable; capturing it while the numbers were fresh. Phase 16 need only verify/update the numbers. | Phase 11 |
| 42 | The tmpfs is mounted with `mount -t tmpfs -o size=Nm` and verified via `/proc/mounts` (path + `tmpfs` fstype + exact `size=` option) before the writer spawns; any failure aborts the trial with a `FAILED` event — there is no fallback path to the normal filesystem. | The mount table is the kernel's own truth; verifying all three attributes guarantees the writer can only ever fill the size-capped fault disk. | Phase 12 |
| 43 | The writer handles `ENOSPC` by retrying while staying alive (fd_exhaustion-style), so the disk stays full until recovery kills it; short writes near the full mark produce partial files, which deletion counts honestly. | A leaking service keeps running and failing; a dead writer would make the "kill the writer" recovery step vacuous. | Phase 12 |
| 44 | Recovery (`recover_disk_full`) kills the writer, deletes files, and verifies usage drops below the threshold BEFORE logging `RECOVERED`; umount+rmdir+`/proc/mounts` verification lives in `cleanup_fault_disk()`, called from the runner's `finally` so it runs on every trial including exceptions and Ctrl+C, with the run ending in a hard no-leftover-mounts assertion plus a root-filesystem before/after report. | Separation matches the existing pattern (recovery verifies health, runner's finally owns cleanup); the finally block is the only place guaranteed to run on all failure paths. | Phase 12 |
| 45 | Line-budget watch: 2487/2500 lines of Python excluding tests after Phase 12. Phases 13–14 must write minimal injector/detector/recovery code; Phase 15's chart redesign (horizontal bars for 7 faults) is expected to consolidate `results.py` and reclaim lines. If the final count still exceeds 2500, raise the budget only with a recorded decision here. | The 2500 limit was set before the new-fault phases existed; per-module smallness remains the binding rule. | Phase 12 |
| 46 | Raised the Python line budget from 2500 to 3000 excluding tests (prd.md updated). Phase 13 landed at 2722 lines. | Phase 12 ended 13 lines under the old budget; the user directed the raise with clarity-over-compression. Per-module smallness remains the binding rule. | Phase 13 |
| 47 | The leaker is the faulty service itself, started by the runner in Step 1: it lowers ITS OWN `RLIMIT_NOFILE` at startup and idles; injection is a `SIGUSR1` trigger that starts the leak. | Keeps the monitor-before-injection + random-jitter flow identical to every other fault and makes MTTD honest — the monitor watches the leaker's low-fd baseline before the leak begins. A leaker launched at inject-time would not exist for the monitor to watch, and a leaker leaking from birth would corrupt pre-injection readings. | Phase 13 |
| 48 | Recovery reuses `restart_target()` for the "fresh clean instance" (standard target command, no leak) and verifies it with a new `FD_CLEAN_MAX_FDS` (20) bound instead of a hardcoded number. | Same-service recovery without duplicating supervisor retry logic; the bound is a tunable so no magic number enters the recovery code. | Phase 13 |
| 49 | Leftover-leaker checks: per-trial verification of the trial's leaker PID in the runner `finally`, and the end-of-run assertion sweeps the process table for the leaker's cmdline signature (`RLIMIT_NOFILE` appears only in leaker processes). | Rule: prove nothing leaks after every trial and at the end of the run; the cmdline sweep catches leakers from any source, not just the tracked PID. | Phase 13 |
| 50 | zombie_leak children are created with `os.fork()` + `os._exit(0)`, never via `subprocess`/`multiprocessing`, and the leaker leaves `SIGCHLD` at `SIG_DFL`. | Python's subprocess machinery reaps finished children automatically, and `SIG_IGN` for `SIGCHLD` makes the kernel auto-reap — either would prevent zombies from accumulating, defeating the fault. | Phase 14 |
| 51 | Zombie reaping after recovery reuses the existing `reap_zombie_children()` (`os.waitpid(-1, WNOHANG)` loop) rather than setting `init: true` in docker-compose.yml. | Simpler: no compose/config change, works for every invocation (compose run, manual module runs), and reuses Phase 8's proven mechanism. `RECOVERED` is logged only after `count_zombies()` verifies zero, so the PID-1 reaping question is answered empirically every trial. | Phase 14 |
| 52 | zombie_leak detection counts only the leaker's direct children in `STATUS_ZOMBIE` (`psutil.Process.children()`, non-recursive), firing strictly above `ZOMBIE_THRESHOLD`. | Container-wide counts would blame the leaker for unrelated processes' zombies; scoping to direct children is both the honest measure and avoids false alarms. | Phase 14 |
| 53 | Raised the Python line budget from 3000 to 3300 excluding tests (prd.md updated), per user direction; clarity over compression. | Phases 13-14 landed at 2978/3000; the 7-fault integration and chart rework need headroom. Per-module smallness remains the binding rule. | Phase 15 |
| 54 | The optional dispatch-table refactor was evaluated and rejected. | The inject/detect/recover branches have genuinely heterogeneous signatures (pid vs trial_id args, the disk_full abort special-case, per-fault state threading through run_trial); a uniform table needs lambdas plus a context dict, which reduces clarity for ~25 saved lines. Behavior-identity is instead proven by the 40-test suite and the full 120-trial run (100% success across all 8 groups). | Phase 15 |
| 55 | The per-fault post-run verification blocks in `run_experiment` were consolidated into one `assert_no_leftover_resources()` used by both single-fault runs and `--fault all`. | Every run now asserts ALL resources (processes, stopped processes, zombies, tmpfs mounts, cgroups) instead of only its own fault's — strictly stronger, and it removed duplicated code between run_experiment and run_all_experiments. | Phase 15 |
| 56 | Charts reworked to 8 fault groups (process_hang as two rows — resume and restart — sharing the fault's violet per design.md), scatter chart replaced by a recovery-time (MTTR − MTTD) chart, all titles built from computed data, and the ramp-up/debounce note added under the MTTD chart and in the printed summary. | Task 3/4 requirements; horizontal bars with direct labels keep 8 rows readable; the recovery-time view compares recovery cost without penalizing faults that have a detection ramp-up. | Phase 15 |
| 57 | The README results table is generated from `results/results.csv` at documentation time (aggregates computed with a one-off script, never typed from memory), and the full 120-trial suite was re-run after the demo verification so the published numbers match the canonical dataset. | The demo run rewrites the `_001` trial rows; re-running the suite keeps the CSV, charts, and README mutually consistent and honest. | Phase 16 |
| 58 | Historical entries in memory.md and tasks.md (Phase 9/10 checklists, old decision rows mentioning "45 trials" or the then-current budgets) are preserved verbatim. | They are a chronological record of what was true when written; rewriting them would falsify history. Current-state sections (PRD, architecture, How-to-Run, README) were updated instead. | Phase 16 |

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

# Verify process hang injector inside container:
docker compose run --rm lab python -m injector.process_hang

# Verify disk full injector inside container:
docker compose run --rm lab python -m injector.disk_full

# Verify fd exhaustion injector inside container:
docker compose run --rm lab python -m injector.fd_exhaustion

# Verify zombie leak injector inside container:
docker compose run --rm lab python -m injector.zombie_leak

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

# Run 15-trial experiment for process_hang (resume strategy):
docker compose run --rm lab python -m experiment.runner --fault process_hang --strategy resume --trials 15

# Run 15-trial experiment for process_hang (restart strategy):
docker compose run --rm lab python -m experiment.runner --fault process_hang --strategy restart --trials 15

# Run 15-trial experiment for disk_full:
docker compose run --rm lab python -m experiment.runner --fault disk_full --trials 15

# Run 15-trial experiment for fd_exhaustion:
docker compose run --rm lab python -m experiment.runner --fault fd_exhaustion --trials 15

# Run 15-trial experiment for zombie_leak:
docker compose run --rm lab python -m experiment.runner --fault zombie_leak --trials 15

# Run full 120-trial suite (7 faults, 15 trials each; process_hang both strategies):
docker compose run --rm lab python -m experiment.runner --fault all --trials 15

# Regenerate publication charts directly from existing CSV without re-running:
docker compose run --rm lab python -m experiment.results

# Run interactive demonstration (1 trial per fault type with instant chart generation):
docker compose run --rm lab python scripts/demo.py

# Run unit test suite (40 unit tests via stdlib unittest):
docker compose run --rm lab python -m unittest discover tests -v
```

---

## Next Step

**Project Complete — all 16 phases finished.**
- 7 faults, each with inject → detect → recover, measured over 120 trials at 100% success.
- Runnable via `docker compose run --rm lab python scripts/demo.py` or `python -m experiment.runner --fault all --trials 15`.
- 40 unit tests pass; no unused imports; docs consistent; README ready for viva presentation.

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
| `docs/prd.md` | Modified | 11-16 (docs) | Seven faults: 4 new tables, metrics, non-goals, learning goals, line budget |
| `docs/architecture.md` | Modified | 11-16 (docs) | New injectors, config constants, event types, safety rules, 7-fault reference table |
| `docs/design.md` | Modified | 11-16 (docs) | 4 new fault colors, 7-fault chart rules |
| `docs/tasks.md` | Modified | 11-16 (docs) | Phases 11-16 added (all Planned) |
| `docs/rules.md` | Modified | 11-16 (docs) | Scope-control fault list extended to seven faults |
| `docs/memory.md` | Modified | 11-16 (docs) | This update: status, decisions, next step |
| `config.py` | Modified | Phase 11 | Added `HEARTBEAT_FILE_PATH` |
| `target/heartbeat_app.py` | Modified | Phase 11 | Appends heartbeat timestamps to `HEARTBEAT_FILE_PATH` each tick |
| `injector/process_hang.py` | Created | Phase 11 | SIGSTOP injector with per-trial heartbeat reset |
| `monitor/detector.py` | Modified | Phase 4, 7, 8, 11 | Added heartbeat-staleness check and process_hang detection |
| `monitor/monitor.py` | Modified | Phase 4, 7, 8, 11 | Added process_hang polling branch |
| `recovery/supervisor.py` | Modified | Phase 5, 6, 11 | Added `recover_process_hang` (resume/restart), fresh-heartbeat wait, `fault_type`/`log_recovery` kwargs |
| `experiment/runner.py` | Modified | Phases 6-11 | Added process_hang orchestration, `--strategy` CLI, SIGKILL cleanup + leftover verification |
| `experiment/results.py` | Modified | Phase 6, 7, 9, 11 | Added process_hang color/label/order |
| `tests/test_detector.py` | Modified | Phase 10, 11 | Added 5 heartbeat-staleness tests (suite now 27) |
| `.gitignore` | Modified | Phase 11 | Excludes `results/*.log` (heartbeat file) |
| `docs/process_hang_notes.md` | Created | Phase 11 | Learning notes: process states, alive vs healthy, heartbeat staleness, strategy comparison |
| `docs/architecture.md` | Modified | Phase 11 (docs fix) | Dependency map: heartbeat_app now imports config |
| `config.py` | Modified | Phase 12 | Added `DISK_FAULT_SIZE_MB`, `DISK_MOUNT_PATH`, `DISK_THRESHOLD_PERCENT` |
| `injector/disk_full.py` | Created | Phase 12 | tmpfs mount + `/proc/mounts` verification + ENOSPC writer |
| `monitor/detector.py` | Modified | Phase 4, 7, 8, 11, 12 | Added disk-usage threshold check and disk_full detection |
| `monitor/monitor.py` | Modified | Phase 4, 7, 8, 11, 12 | Added disk_full polling branch |
| `recovery/resource_recovery.py` | Modified | Phase 7, 8, 12 | Added `recover_disk_full` and `cleanup_fault_disk` (umount + verify) |
| `experiment/runner.py` | Modified | Phases 6-12 | Added disk_full orchestration, finally-block umount cleanup, no-leftover-mounts assertion, root-fs leak proof |
| `experiment/results.py` | Modified | Phase 6, 7, 9, 11, 12 | Added disk_full color/label/order |
| `tests/test_detector.py` | Modified | Phase 10, 11, 12 | Added 3 disk-usage tests (suite now 30) |
| `docs/disk_full_notes.md` | Created | Phase 12 | Learning notes: filesystems, mounts, tmpfs, ENOSPC, df vs du, leak proof |
| `config.py` | Modified | Phase 13 | Added `FD_LIMIT`, `FD_THRESHOLD_PERCENT`, `FD_CLEAN_MAX_FDS` |
| `injector/fd_exhaustion.py` | Created | Phase 13 | Leaker service (own RLIMIT_NOFILE, EMFILE loop) + SIGUSR1 leak trigger |
| `monitor/detector.py` | Modified | Phase 4, 7, 8, 11-13 | Added fd-ratio check and fd_exhaustion detection |
| `monitor/monitor.py` | Modified | Phase 4, 7, 8, 11-13 | Added fd_exhaustion polling branch |
| `recovery/supervisor.py` | Modified | Phase 5, 6, 11, 13 | Added `recover_fd_exhaustion` (kill+reap, fresh instance, fd verification) |
| `experiment/runner.py` | Modified | Phases 6-13 | Leaker started as faulty service, fd_exhaustion branches, leftover-leaker verification |
| `experiment/results.py` | Modified | Phase 6, 7, 9, 11-13 | Added fd_exhaustion color/label/order |
| `tests/test_detector.py` | Modified | Phase 10, 11-13 | Added 4 fd-ratio tests (suite now 34) |
| `docs/fd_exhaustion_notes.md` | Created | Phase 13 | Learning notes: fd table, rlimits, EMFILE, ramp+debounce MTTD |
| `docs/prd.md` | Modified | Phase 13 | Line budget raised to 3000 excluding tests |
| `config.py` | Modified | Phase 14 | Added `ZOMBIE_LEAK_MAX_CHILDREN`, `ZOMBIE_THRESHOLD` |
| `injector/zombie_leak.py` | Created | Phase 14 | Leaker parent (os.fork, never waits, SIGUSR1 trigger) |
| `monitor/detector.py` | Modified | Phase 4, 7, 8, 11-14 | Added zombie-children count and zombie_leak detection |
| `monitor/monitor.py` | Modified | Phase 4, 7, 8, 11-14 | Added zombie_leak polling branch |
| `recovery/resource_recovery.py` | Modified | Phase 7, 8, 12, 14 | Added `count_zombies` and `recover_zombie_leak` (kill parent, reap orphans, verify zero) |
| `experiment/runner.py` | Modified | Phases 6-14 | zombie_leak branches, per-trial no-leaker/no-zombie verification, end-of-run assertion |
| `experiment/results.py` | Modified | Phase 6, 7, 9, 11-14 | Added zombie_leak color/label/order (all seven faults now mapped) |
| `tests/test_detector.py` | Modified | Phase 10, 11-14 | Added 3 zombie-count tests (suite now 37) |
| `docs/zombie_leak_notes.md` | Created | Phase 14 | Learning notes: zombies, reparenting, init reaping, spawn-ramp MTTD |
| `docs/architecture.md` | Modified | Phase 13, 14 (docs fix) | Injector table rows updated for the two-phase leaker design |
| `docs/prd.md` | Modified | Phase 15 | Line budget raised to 3300 excluding tests |
| `experiment/results.py` | Modified | Phase 15 | Rewritten: 8 chart groups, 4 horizontal-bar charts, data-built titles, ramp-up note, scatter removed |
| `experiment/runner.py` | Modified | Phases 6-15 | `--fault all` for 8 groups; `assert_no_leftover_resources()` consolidation |
| `scripts/safety_check.py` | Modified | Phase 15 | tmpfs mount capability check (verified + cleaned up) |
| `scripts/demo.py` | Modified | Phase 15 | Wording for 8 fault groups (delegates to run_all_experiments) |
| `tests/test_results.py` | Created | Phase 15 | group_of parsing, re-run dedupe, read/write roundtrip (suite now 40) |
| `docs/design.md` | Modified | Phase 15 | Chart 4 changed from scatter to recovery-time bar |
| `README.md` | Modified | Phase 15 | Chart image link swapped to recovery_time_by_fault.png |
| `docs/images/*.png` | Modified | Phase 15 | 4 final charts copied; mttd_vs_mttr.png removed |
| `docs/process_hang_notes.md` | Modified | Phase 16 | §4 heading fixed to "roughly 2.0 to 3.5 seconds" range framing |
| `docs/architecture.md` | Modified | Phase 16 | Folder tree updated: notes files, images/, demo.py, tests/, generated results |
| `docs/memory.md` | Modified | Phase 16 | How-to-Run counts fixed (120 trials, 40 tests); Phase 16 logged |
| `README.md` | Modified | Phase 10, 16 | Rewritten for seven faults: teacher table, CSV-computed results, Limitations, updated safety + Q&A |


