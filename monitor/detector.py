import subprocess
from pathlib import Path
from typing import Any

import psutil

import config
import event_log


def is_process_alive(pid: int, proc: subprocess.Popen[Any] | None = None) -> bool:
    # If the process is a direct child, poll() checks termination and reaps zombies
    if proc is not None and proc.poll() is not None:
        return False

    if not psutil.pid_exists(pid):
        return False

    try:
        p: psutil.Process = psutil.Process(pid)
        # Treat zombie processes as dead since their execution has already halted
        if p.status() == psutil.STATUS_ZOMBIE:
            if proc is not None:
                proc.poll()
            return False
        return p.is_running()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def detect_process_death(
    pid: int,
    trial_id: str,
    proc: subprocess.Popen[Any] | None = None,
) -> bool:
    if not is_process_alive(pid, proc=proc):
        event_log.log_event(
            trial_id=trial_id,
            fault_type="process_kill",
            event="DETECTED",
            details=f"Target process PID {pid} is dead or zombie",
        )
        return True
    return False


def check_cgroup_memory_pressure(
    cgroup_path: Path,
    consecutive_breaches: int,
) -> tuple[bool, int, str]:
    if not cgroup_path.exists():
        return False, 0, ""

    # Check for OOM kill in memory.events
    events_file: Path = cgroup_path / "memory.events"
    if events_file.exists():
        try:
            content: str = events_file.read_text(encoding="utf-8")
            for line in content.splitlines():
                parts = line.split()
                if len(parts) >= 2 and parts[0] == "oom_kill":
                    kills: int = int(parts[1])
                    if kills > 0:
                        return True, consecutive_breaches, f"OOM kill triggered ({kills} kill(s) observed in memory.events)"
        except (OSError, ValueError):
            pass

    # Check memory.current / memory.max ratio (independent of VM-wide memory)
    cur_file: Path = cgroup_path / "memory.current"
    max_file: Path = cgroup_path / "memory.max"
    if cur_file.exists() and max_file.exists():
        try:
            cur: int = int(cur_file.read_text(encoding="utf-8").strip())
            max_b: int = int(max_file.read_text(encoding="utf-8").strip())
            if max_b > 0:
                ratio: float = (cur / max_b) * 100.0
                if ratio >= config.MEMORY_THRESHOLD_PERCENT:
                    consecutive_breaches += 1
                    if consecutive_breaches >= config.CONSECUTIVE_POLLS_THRESHOLD:
                        return True, consecutive_breaches, f"Memory threshold exceeded: {ratio:.1f}% for {consecutive_breaches} consecutive polls"
                else:
                    consecutive_breaches = 0
        except (OSError, ValueError):
            pass

    return False, consecutive_breaches, ""


def detect_memory_pressure(
    cgroup_path: Path,
    trial_id: str,
    consecutive_breaches: int,
) -> tuple[bool, int]:
    detected, breaches, details = check_cgroup_memory_pressure(cgroup_path, consecutive_breaches)
    if detected:
        event_log.log_event(
            trial_id=trial_id,
            fault_type="memory_pressure",
            event="DETECTED",
            details=details,
        )
        return True, breaches
    return False, breaches


def check_cpu_pressure(
    cpu_percent: float,
    consecutive_breaches: int,
) -> tuple[bool, int, str]:
    if cpu_percent >= config.CPU_THRESHOLD_PERCENT:
        consecutive_breaches += 1
        if consecutive_breaches >= config.CONSECUTIVE_POLLS_THRESHOLD:
            return True, consecutive_breaches, f"CPU threshold exceeded: {cpu_percent:.1f}% for {consecutive_breaches} consecutive polls"
    else:
        consecutive_breaches = 0
    return False, consecutive_breaches, ""


def detect_cpu_hog(
    cpu_percent: float,
    trial_id: str,
    consecutive_breaches: int,
) -> tuple[bool, int]:
    detected, breaches, details = check_cpu_pressure(cpu_percent, consecutive_breaches)
    if detected:
        event_log.log_event(
            trial_id=trial_id,
            fault_type="cpu_hog",
            event="DETECTED",
            details=details,
        )
        return True, breaches
    return False, breaches

