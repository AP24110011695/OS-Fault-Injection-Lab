import subprocess
import time
from pathlib import Path
from typing import Any

import config
import event_log

# 1MB per chunk with a short sleep gives the fault a realistic ramp-up to ENOSPC
WRITER_CODE: str = (
    "import sys, time\n"
    "path = sys.argv[1]\n"
    "n = 0\n"
    "while True:\n"
    "    try:\n"
    "        with open(f'{path}/block_{n:05d}', 'wb') as f:\n"
    "            f.write(b'x' * (1024 * 1024))\n"
    "    except OSError:\n"
    "        pass  # ENOSPC: keep running and retrying like a leaking service would\n"
    "    n += 1\n"
    "    time.sleep(0.05)\n"
)


def is_tmpfs_mount(path: Path, expected_size_mb: int | None = None) -> bool:
    """True only if /proc/mounts lists path as a tmpfs mountpoint, optionally with
    the expected size cap. This is the safety gate: the writer never starts,
    and cleanup is only reported complete, when this check passes."""
    try:
        with open("/proc/mounts", encoding="utf-8") as f:
            for line in f:
                parts: list[str] = line.split()
                if len(parts) >= 4 and parts[1] == str(path) and parts[2] == "tmpfs":
                    if expected_size_mb is None:
                        return True
                    return f"size={expected_size_mb * 1024}k" in parts[3].split(",")
    except OSError:
        return False
    return False


def mount_fault_disk(trial_id: str, size_mb: int = config.DISK_FAULT_SIZE_MB) -> Path:
    """Mount a size-capped tmpfs at DISK_MOUNT_PATH. ABORTs on any failure —
    the trial must never fall back to the container's normal filesystem."""
    mount_path: Path = Path(config.DISK_MOUNT_PATH)

    if is_tmpfs_mount(mount_path):
        error_msg: str = f"Abort: a tmpfs is already mounted at {mount_path} (leftover from a previous trial?)"
        event_log.log_event(trial_id=trial_id, fault_type="disk_full", event="FAILED", details=error_msg)
        raise RuntimeError(error_msg)

    mount_path.mkdir(parents=True, exist_ok=True)
    try:
        result: subprocess.CompletedProcess[str] = subprocess.run(
            ["mount", "-t", "tmpfs", "-o", f"size={size_mb}m", "tmpfs", str(mount_path)],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except OSError as exc:
        error_msg = f"Abort: mount command failed for {mount_path}: {exc}"
        event_log.log_event(trial_id=trial_id, fault_type="disk_full", event="FAILED", details=error_msg)
        raise RuntimeError(error_msg) from exc

    # Verify via /proc/mounts: right path, right fstype, right size — or abort
    if result.returncode != 0 or not is_tmpfs_mount(mount_path, expected_size_mb=size_mb):
        error_msg = f"Abort: tmpfs verification failed for {mount_path} (rc={result.returncode}): {result.stderr.strip()}"
        event_log.log_event(trial_id=trial_id, fault_type="disk_full", event="FAILED", details=error_msg)
        raise RuntimeError(error_msg)

    return mount_path


def inject(trial_id: str, size_mb: int = config.DISK_FAULT_SIZE_MB) -> subprocess.Popen[Any]:
    mount_path: Path = mount_fault_disk(trial_id, size_mb)

    proc: subprocess.Popen[Any] = subprocess.Popen(["python", "-c", WRITER_CODE, str(mount_path)])
    event_log.log_event(
        trial_id=trial_id,
        fault_type="disk_full",
        event="INJECTED",
        details=f"Writer PID {proc.pid} filling verified tmpfs {mount_path} (size cap {size_mb}MB)",
    )
    return proc


if __name__ == "__main__":
    import psutil

    from recovery.resource_recovery import cleanup_fault_disk, recover_disk_full

    print("Testing disk_full injector...")
    trial_id: str = "manual_disk_test"
    event_log.clear_log()

    mount_path: Path = Path(config.DISK_MOUNT_PATH)
    writer = inject(trial_id)
    print(f"Writer PID: {writer.pid}, mount: {mount_path}")
    assert is_tmpfs_mount(mount_path, config.DISK_FAULT_SIZE_MB), "tmpfs should be mounted and verified"

    for _ in range(30):
        time.sleep(0.1)
        percent: float = psutil.disk_usage(str(mount_path)).percent
        print(f"  tmpfs usage: {percent:.1f}%")
        if percent >= 99.0:
            break

    rec = recover_disk_full(trial_id=trial_id, mount_path=mount_path, writer_proc=writer)
    print(f"Recovery status: {rec}")
    clean = cleanup_fault_disk(mount_path=mount_path, writer_proc=writer)
    print(f"Cleanup status: {clean}")
    assert clean, "Mount should be fully cleaned up"
    assert not is_tmpfs_mount(mount_path), "Mountpoint must be gone from /proc/mounts"

    events = event_log.read_events(trial_id=trial_id)
    for e in events:
        print(f"  [{e['timestamp']}] {e['event']}: {e['details']}")

    print("OK: disk_full injector test completed.")
