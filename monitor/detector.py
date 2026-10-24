import subprocess
from datetime import datetime
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


def check_heartbeat_staleness(path: Path, now: datetime | None = None) -> tuple[bool, str]:
    """Staleness check for process_hang. The PID is deliberately NOT consulted:
    a SIGSTOP'd target is still alive, which is exactly why liveness checks miss hangs."""
    current: datetime = now if now is not None else datetime.now()

    try:
        lines: list[str] = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return True, "No heartbeat file"

    # Newest timestamp wins; skip unparseable lines
    for line in reversed(lines):
        try:
            last: datetime = datetime.fromisoformat(line.strip())
        except ValueError:
            continue
        age: float = (current - last).total_seconds()
        if age > config.HEARTBEAT_TIMEOUT_SEC:
            return True, f"Heartbeat stale: last seen {age:.1f}s ago (timeout {config.HEARTBEAT_TIMEOUT_SEC:.1f}s)"
        return False, ""

    return True, "No heartbeat timestamps available"


def detect_process_hang(heartbeat_path: Path, trial_id: str) -> bool:
    stale, details = check_heartbeat_staleness(heartbeat_path)
    if stale:
        event_log.log_event(
            trial_id=trial_id,
            fault_type="process_hang",
            event="DETECTED",
            details=details,
        )
        return True
    return False


def check_disk_usage(
    mount_path: Path,
    consecutive_breaches: int,
) -> tuple[bool, int, str]:
    try:
        percent: float = psutil.disk_usage(str(mount_path)).percent
    except (OSError, psutil.Error):
        # Missing/unreadable mount must not cause false detection
        return False, 0, ""

    if percent >= config.DISK_THRESHOLD_PERCENT:
        consecutive_breaches += 1
        if consecutive_breaches >= config.CONSECUTIVE_POLLS_THRESHOLD:
            return True, consecutive_breaches, f"Disk usage exceeded: {percent:.1f}% for {consecutive_breaches} consecutive polls"
    else:
        consecutive_breaches = 0
    return False, consecutive_breaches, ""


def detect_disk_full(
    mount_path: Path,
    trial_id: str,
    consecutive_breaches: int,
) -> tuple[bool, int]:
    detected, breaches, details = check_disk_usage(mount_path, consecutive_breaches)
    if detected:
        event_log.log_event(
            trial_id=trial_id,
            fault_type="disk_full",
            event="DETECTED",
            details=details,
        )
        return True, breaches
    return False, breaches


def check_fd_ratio(pid: int, consecutive_breaches: int) -> tuple[bool, int, str]:
    """Ratio of the leaker's open fds to ITS OWN RLIMIT_NOFILE soft limit.
    The limit is read from the process, never from the system."""
    try:
        proc: psutil.Process = psutil.Process(pid)
        num_fds: int = proc.num_fds()
        soft_limit: int = proc.rlimit(psutil.RLIMIT_NOFILE)[0]
    except psutil.Error:
        return False, 0, ""

    if soft_limit <= 0:  # unlimited or unset limit cannot produce a meaningful ratio
        return False, 0, ""

    ratio: float = num_fds / soft_limit * 100.0
    if ratio >= config.FD_THRESHOLD_PERCENT:
        consecutive_breaches += 1
        if consecutive_breaches >= config.CONSECUTIVE_POLLS_THRESHOLD:
            return True, consecutive_breaches, f"FD usage exceeded: {num_fds}/{soft_limit} ({ratio:.1f}%) for {consecutive_breaches} consecutive polls"
    else:
        consecutive_breaches = 0
    return False, consecutive_breaches, ""


def detect_fd_exhaustion(
    pid: int,
    trial_id: str,
    consecutive_breaches: int,
) -> tuple[bool, int]:
    detected, breaches, details = check_fd_ratio(pid, consecutive_breaches)
    if detected:
        event_log.log_event(
            trial_id=trial_id,
            fault_type="fd_exhaustion",
            event="DETECTED",
            details=details,
        )
        return True, breaches
    return False, breaches


def count_zombie_children(parent_pid: int) -> int:
    """Number of the given parent's direct children in STATUS_ZOMBIE. Only that
    parent's children are counted so unrelated processes cannot cause false alarms."""
    try:
        children: list[psutil.Process] = psutil.Process(parent_pid).children()
    except psutil.Error:
        return 0

    zombies: int = 0
    for child in children:
        try:
            if child.status() == psutil.STATUS_ZOMBIE:
                zombies += 1
        except psutil.Error:
            continue
    return zombies


def check_zombie_leak(parent_pid: int, consecutive_breaches: int) -> tuple[bool, int, str]:
    zombies: int = count_zombie_children(parent_pid)
    if zombies > config.ZOMBIE_THRESHOLD:
        consecutive_breaches += 1
        if consecutive_breaches >= config.CONSECUTIVE_POLLS_THRESHOLD:
            return True, consecutive_breaches, f"Zombie children detected: {zombies} zombies above {config.ZOMBIE_THRESHOLD} for {consecutive_breaches} consecutive polls"
    else:
        consecutive_breaches = 0
    return False, consecutive_breaches, ""


def detect_zombie_leak(
    parent_pid: int,
    trial_id: str,
    consecutive_breaches: int,
) -> tuple[bool, int]:
    detected, breaches, details = check_zombie_leak(parent_pid, consecutive_breaches)
    if detected:
        event_log.log_event(
            trial_id=trial_id,
            fault_type="zombie_leak",
            event="DETECTED",
            details=details,
        )
        return True, breaches
    return False, breaches

