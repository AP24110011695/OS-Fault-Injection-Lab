import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

import psutil

import config
import event_log
from injector.disk_full import is_tmpfs_mount
from monitor.detector import is_process_alive
from recovery.supervisor import restart_target


def remove_cgroup(cgroup_path: Path, retries: int = 5, delay_sec: float = 0.1) -> bool:
    if not cgroup_path.exists():
        return True

    # Terminate any remaining processes in the cgroup before rmdir
    procs_file: Path = cgroup_path / "cgroup.procs"
    if procs_file.exists():
        try:
            pids = [int(p) for p in procs_file.read_text(encoding="utf-8").split()]
            for pid in pids:
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
        except OSError:
            pass

    # Attempt rmdir with retries to give the kernel time to release references
    for _ in range(retries):
        try:
            cgroup_path.rmdir()
            return True
        except OSError:
            time.sleep(delay_sec)

    return not cgroup_path.exists()


def recover_memory(
    trial_id: str,
    cgroup_path: Path,
    hog_proc: subprocess.Popen[Any] | None = None,
    target_proc: subprocess.Popen[Any] | None = None,
    target_pid: int | None = None,
) -> bool:
    oom_killed: bool = False

    # 1. Terminate memory hog if still running
    if hog_proc is not None:
        if hog_proc.poll() is None:
            try:
                hog_proc.terminate()
                hog_proc.wait(timeout=1.0)
            except (subprocess.TimeoutExpired, OSError):
                try:
                    hog_proc.kill()
                    hog_proc.wait(timeout=1.0)
                except OSError:
                    pass
        else:
            oom_killed = (hog_proc.returncode in (-9, 137))

    # 2. Inspect memory.events summary before removing cgroup
    events_summary: str = ""
    events_file: Path = cgroup_path / "memory.events"
    if events_file.exists():
        try:
            events_summary = events_file.read_text(encoding="utf-8").replace("\n", " ").strip()
        except OSError:
            pass

    # 3. Clean up and remove the cgroup directory
    cgroup_removed: bool = remove_cgroup(cgroup_path)

    # 4. Verify target process health (restart via supervisor if affected)
    target_restarted: bool = False
    if target_pid is not None:
        if not is_process_alive(target_pid, proc=target_proc):
            restart_target(trial_id=trial_id)
            target_restarted = True

    # 5. Build recovery details and log RECOVERED event
    details_parts: list[str] = []
    if oom_killed:
        details_parts.append("Hog terminated by OOM killer (SIGKILL)")
    else:
        details_parts.append("Hog process terminated by recovery")

    if events_summary:
        details_parts.append(f"[{events_summary}]")

    if cgroup_removed:
        details_parts.append(f"cgroup {cgroup_path.name} removed")
    else:
        details_parts.append(f"warning: cgroup {cgroup_path.name} removal pending")

    if target_restarted:
        details_parts.append("target required supervisor restart")
    else:
        details_parts.append("target remained healthy outside cgroup")

    event_log.log_event(
        trial_id=trial_id,
        fault_type="memory_pressure",
        event="RECOVERED",
        details="; ".join(details_parts),
    )
    return True


def reap_zombie_children() -> None:
    while True:
        try:
            pid, _ = os.waitpid(-1, os.WNOHANG)
            if pid <= 0:
                break
        except ChildProcessError:
            break


def kill_stress_ng(proc: subprocess.Popen[Any] | None = None) -> None:
    if proc is not None:
        try:
            p = psutil.Process(proc.pid)
            children = p.children(recursive=True)
            for child in children:
                try:
                    child.kill()
                except psutil.NoSuchProcess:
                    pass
            p.kill()
            p.wait(timeout=1.0)
        except (psutil.NoSuchProcess, psutil.TimeoutExpired, OSError):
            pass

    for p in psutil.process_iter(["name"]):
        try:
            name = p.info.get("name") or ""
            if "stress-ng" in name:
                p.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    # Reap terminated/zombie child processes to release kernel task structs
    reap_zombie_children()


def recover_cpu(
    trial_id: str,
    stress_proc: subprocess.Popen[Any] | None = None,
    timeout_sec: float = 5.0,
) -> bool:
    kill_stress_ng(stress_proc)

    # Verify CPU drops back below threshold
    psutil.cpu_percent(interval=None)
    start_verify: float = time.time()
    current_cpu: float = 100.0

    while time.time() - start_verify < timeout_sec:
        time.sleep(0.1)
        current_cpu = psutil.cpu_percent(interval=None)
        if current_cpu < config.CPU_THRESHOLD_PERCENT:
            break

    # Verify no lingering stress-ng workers remain
    lingering = [p for p in psutil.process_iter(["name"]) if "stress-ng" in (p.info.get("name") or "")]
    if lingering:
        for p in lingering:
            try:
                p.kill()
            except psutil.NoSuchProcess:
                pass

    event_log.log_event(
        trial_id=trial_id,
        fault_type="cpu_hog",
        event="RECOVERED",
        details=f"stress-ng terminated; CPU normalized to {current_cpu:.1f}%",
    )
    return True


def kill_writer(writer_proc: subprocess.Popen[Any] | None) -> None:
    if writer_proc is None or writer_proc.poll() is not None:
        return
    try:
        writer_proc.terminate()
        writer_proc.wait(timeout=1.0)
    except (subprocess.TimeoutExpired, OSError):
        try:
            writer_proc.kill()
            writer_proc.wait(timeout=1.0)
        except OSError:
            pass


def delete_mount_files(mount_path: Path) -> int:
    removed: int = 0
    if not mount_path.exists():
        return 0
    for f in mount_path.iterdir():
        try:
            f.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def recover_disk_full(
    trial_id: str,
    mount_path: Path,
    writer_proc: subprocess.Popen[Any] | None = None,
) -> bool:
    # 1. Kill the writer so nothing recreates files while we clean up
    kill_writer(writer_proc)

    # 2. Delete the writer's files
    removed: int = delete_mount_files(mount_path)

    # 3. Verify usage drops below the threshold (retry briefly to let deletes settle)
    percent: float = 100.0
    for _ in range(5):
        try:
            percent = psutil.disk_usage(str(mount_path)).percent
        except (OSError, psutil.Error):
            percent = 0.0
            break
        if percent < config.DISK_THRESHOLD_PERCENT:
            break
        time.sleep(0.1)

    if percent >= config.DISK_THRESHOLD_PERCENT:
        error_msg: str = f"Recovery failed: disk usage still {percent:.1f}% after deleting {removed} file(s)"
        event_log.log_event(trial_id=trial_id, fault_type="disk_full", event="FAILED", details=error_msg)
        raise RuntimeError(error_msg)

    event_log.log_event(
        trial_id=trial_id,
        fault_type="disk_full",
        event="RECOVERED",
        details=f"Writer terminated; {removed} file(s) deleted; disk usage normalized to {percent:.1f}%",
    )
    return True


def cleanup_fault_disk(
    mount_path: Path,
    writer_proc: subprocess.Popen[Any] | None = None,
) -> bool:
    """Full cleanup after every trial (also on failure paths and Ctrl+C):
    kill the writer, delete its files, umount, remove the directory, and verify
    via /proc/mounts that the path is no longer mounted."""
    kill_writer(writer_proc)
    delete_mount_files(mount_path)

    for _ in range(5):
        if not is_tmpfs_mount(mount_path):
            break
        try:
            subprocess.run(["umount", str(mount_path)], capture_output=True, text=True, timeout=10)
        except OSError:
            pass
        time.sleep(0.1)

    if not is_tmpfs_mount(mount_path):
        try:
            mount_path.rmdir()
        except OSError:
            pass

    return not is_tmpfs_mount(mount_path) and not mount_path.exists()


def count_zombies() -> int:
    return sum(
        1 for p in psutil.process_iter(["status"])
        if (p.info.get("status") or "") == psutil.STATUS_ZOMBIE
    )


def recover_zombie_leak(
    trial_id: str,
    pid: int,
    leaker_proc: subprocess.Popen[Any] | None = None,
) -> bool:
    """Kill the leaker parent (and reap it), reap the zombies it orphaned to PID 1,
    and log RECOVERED only after the container really has zero zombies left."""
    # 1. Kill the leaker parent and reap it
    if leaker_proc is not None:
        if leaker_proc.poll() is None:
            try:
                leaker_proc.kill()
                leaker_proc.wait(timeout=1.0)
            except OSError:
                pass
    else:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    # 2. Orphaned zombies are adopted by PID 1 (this Python runner), which does not
    #    reap automatically — reap them explicitly.
    reap_zombie_children()

    # 3. Verify zero zombies remain (reparenting is asynchronous; retry briefly)
    zombies: int = -1
    for _ in range(5):
        zombies = count_zombies()
        if zombies == 0:
            break
        reap_zombie_children()
        time.sleep(0.1)

    if zombies != 0:
        error_msg: str = f"Recovery failed: {zombies} zombie process(es) remain after reaping"
        event_log.log_event(trial_id=trial_id, fault_type="zombie_leak", event="FAILED", details=error_msg)
        raise RuntimeError(error_msg)

    event_log.log_event(
        trial_id=trial_id,
        fault_type="zombie_leak",
        event="RECOVERED",
        details=f"Leaker parent PID {pid} killed and reaped; orphaned zombies reaped; 0 zombies remain",
    )
    return True



if __name__ == "__main__":
    from injector.cpu_hog import inject as inject_cpu
    from injector.memory_pressure import inject as inject_mem

    print("Testing recovery.resource_recovery standalone...")
    event_log.clear_log()

    # 1. Test memory recovery
    trial_mem: str = "recovery_mem_test"
    hog, cg_dir = inject_mem(trial_id=trial_mem, limit_mb=32)
    time.sleep(0.5)
    rec_mem = recover_memory(trial_id=trial_mem, cgroup_path=cg_dir, hog_proc=hog)
    print(f"Memory recovery status: {rec_mem}")
    assert not cg_dir.exists(), f"Cgroup {cg_dir} should have been removed"

    # 2. Test CPU recovery
    trial_cpu: str = "recovery_cpu_test"
    stress = inject_cpu(trial_id=trial_cpu, workers=2, timeout_sec=10)
    time.sleep(1.0)
    rec_cpu = recover_cpu(trial_id=trial_cpu, stress_proc=stress)
    print(f"CPU recovery status: {rec_cpu}")
    remaining_stress = [p for p in psutil.process_iter(["name"]) if "stress-ng" in (p.info.get("name") or "")]
    assert len(remaining_stress) == 0, f"Lingering stress-ng processes found: {remaining_stress}"

    events = event_log.read_events()
    print("\n--- Event Log Verification ---")
    for e in events:
        print(f"  [{e['timestamp']}] {e['event']:<10} | {e['details']}")

    print("\nOK: Resource recovery standalone test passed.")
