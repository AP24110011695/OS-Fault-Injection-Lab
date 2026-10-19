# Rules — OS Fault Injection Lab

These rules govern every coding session. The AI assistant and the student must both follow them.

---

## Operating Protocol — "execute phaseN"

When the user types `execute phaseN` (e.g., `execute phase3`):

1. **Read `memory.md` first** to find the true current state of the project.
2. **Read `prd.md`, `architecture.md`, `rules.md`, and `tasks.md`.**
   Read `design.md` too if the phase touches charts, CLI output, or documentation.
3. **Check that all earlier phases are complete.** If not, finish them first.
4. **Do ALL the work of that phase:** write the code, run it, test it, verify the definition of done.
5. **If anything breaks, debug and fix it yourself.** Do not ask the user.
   Retry with a different approach until it works.
   Only stop if it is truly impossible, and explain exactly why.
6. **Do not ask clarifying questions.** Choose the simplest option that fits the docs
   and log the decision in `memory.md` under "Decisions."
7. **Before finishing, review your own code and delete anything unnecessary.**
8. **Update `memory.md`** (completed tasks, decisions, issues, next step)
   **and tick the boxes in `tasks.md`.**
9. **End with a short summary:** what was done, how to run it,
   what the student should learn from this phase.

**Never start coding from guesswork. If unsure, re-read the docs.**

---

## Doc-First Rule

- **Read the relevant docs before writing any code.** Never assume project details.
- If a doc contradicts your assumption, the doc wins.
- If the docs are silent on a point, choose the simplest option, implement it, and record
  the decision in `memory.md`.

---

## Code Minimalism (CRITICAL)

- **NEVER write unnecessary code.**
  - No dead code.
  - No unused functions or imports.
  - No speculative features ("we might need this later").
  - No needless abstractions, wrapper classes, or indirection layers.
  - No padding or filler.
  - No redundant comments that restate what the code does.
- **Every line must have a purpose.** If you cannot explain why a line exists, delete it.
- **Prefer the simplest solution that works.** If something can be done in fewer clear lines, do that.
- **Do not over-engineer.** A flat function is better than a class hierarchy. A dict is better than a
  custom object if the dict is clear enough. A loop is better than a framework.

---

## Scope Control

- **Do not add libraries, files, or features outside the documented scope.**
  - Allowed libraries: `psutil`, `matplotlib`, `stress-ng` (system tool), Python standard library.
  - If you believe a new library is truly necessary, you must:
    1. Write the justification in `memory.md` under "Decisions."
    2. Get explicit approval from the user before adding it.
- **Do not add fault types** beyond: process kill, memory pressure, CPU hog.
- **Do not add infrastructure** (Kubernetes, Grafana, web servers, databases, etc.).

---

## Python Style

- **Type hints on all function signatures.** Not on local variables unless clarity demands it.
- **Small functions.** Each function does one thing. If a function exceeds ~30 lines, consider splitting.
- **Clear names.** `start_target_process()`, not `stp()`. `monitor_poll_interval_sec`, not `MPI`.
- **Standard library first.** Use `subprocess`, `os`, `signal`, `json`, `csv`, `datetime`, `time`,
  `pathlib` before reaching for anything external.
- **Comments explain WHY, not WHAT.**
  - Bad: `# increment counter` / `counter += 1`
  - Good: `# Poll more frequently during the first second to minimize detection latency`
- **No docstrings on trivial functions.** A function named `kill_process(pid: int)` does not need
  a docstring that says "Kills a process given its PID."
- **Docstrings on non-obvious functions** using plain text, not reStructuredText or NumPy style.
  Keep them short.

---

## Configuration

- **All tunables live in `config.py`.** One file, flat variables, no nested dicts or classes.
- **No magic numbers in code.** Every threshold, timeout, path, and default value must be
  defined in `config.py` and imported where needed.
- **Environment variable overrides are acceptable** for values that change between runs
  (e.g., trial count), but the default must still be in `config.py`.

---

## Safety

- **Every fault and recovery action must be safe, reversible, and cleaned up.**
- Never run fault injection outside Docker. The safety check must run before any injection.
- Kill child processes after every trial. Verify they are dead.
- Remove cgroup directories after every trial.
- Set timeouts on everything that could hang (subprocesses, polling loops).
- Handle `SIGINT` (Ctrl+C) gracefully: clean up, then exit.

---

## Modularity and Testing

- **Each module must be runnable and testable on its own.**
  - `python -m event_log` should demonstrate writing and reading events.
  - `python -m target.heartbeat_app` should run the heartbeat.
  - `python -m monitor.monitor` should print live system metrics.
  - Individual injectors should be runnable for manual testing.
- **Tests go in a `tests/` directory** and use `unittest` or plain `assert` statements.
  No pytest dependency unless justified.
- **Test core logic, not glue code.** Prioritize testing:
  - Event log read/write.
  - MTTD/MTTR calculation.
  - Threshold detection logic.
  - Supervisor retry logic.

---

## Error Handling

- **Only add error handling where failures realistically happen:**
  - Subprocess launch failures.
  - File I/O (event log, results CSV).
  - Process-not-found errors when killing PIDs.
  - cgroup filesystem operations.
- **Do not add defensive try/except everywhere.** Let unexpected errors surface naturally
  so they can be debugged.
- **Log errors clearly** with the context needed to debug them (PID, path, return code).

---

## Decisions and Ambiguity

- When a decision is ambiguous, **pick the simplest option consistent with the docs**.
- **Record every decision** in `memory.md` under the "Decisions" section, with a one-line rationale.
- If you later discover a decision was wrong, update `memory.md` and fix the code.

---

## Version Control Hygiene

- `.gitignore` must exclude: `results/*.jsonl`, `results/*.csv`, `results/*.png`, `__pycache__/`,
  `*.pyc`, `.env`.
- `results/.gitkeep` stays tracked so the directory exists in a fresh clone.
- Commit messages (if the student uses git): imperative mood, reference the phase number.
  Example: `phase3: implement process kill injector`.

---

## Quick Reference Checklist

Before finishing any phase, verify:

- [ ] All code compiles and runs without errors.
- [ ] No unused imports, functions, variables, or files.
- [ ] No magic numbers — all constants in `config.py`.
- [ ] Type hints on all function signatures.
- [ ] Safety check passes (running inside Docker).
- [ ] Cleanup runs after every trial.
- [ ] Event log entries are written correctly.
- [ ] `memory.md` is updated with completed tasks, decisions, and next step.
- [ ] `tasks.md` checkboxes are ticked for completed items.
