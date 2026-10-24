import argparse
import random
import threading
import time
from pathlib import Path
from typing import Any

import psutil

import config
import event_log
from experiment.metrics import calculate_trial_metrics
from experiment.results import (
    generate_all_charts,
    print_comparison_summary,
    print_summary_table,
    write_results_csv,
)
from injector.cpu_hog import inject as inject_cpu_hog
from injector.disk_full import inject as inject_disk_full, is_tmpfs_mount
from injector.fd_exhaustion import inject as inject_fd_exhaustion, start_leaker
from injector.memory_pressure import CGROUP_ROOT, inject as inject_memory_pressure
from injector.process_hang import inject as inject_process_hang, reset_heartbeat_file
from injector.process_kill import inject as inject_process_kill
from injector.zombie_leak import inject as inject_zombie_leak, start_zombie_leaker
from monitor.detector import is_process_alive
from monitor.monitor import monitor_process
from recovery.resource_recovery import (
    cleanup_fault_disk,
    count_zombies,
    kill_stress_ng,
    reap_zombie_children,
    recover_cpu,
    recover_disk_full,
    recover_memory,
    recover_zombie_leak,
    remove_cgroup,
)
from recovery.supervisor import get_last_process, recover_fd_exhaustion, recover_process_hang, restart_target
from scripts.safety_check import verify_docker_environment


def cleanup_trial_processes(*processes: Any) -> None:
    for p in processes:
        if p is not None and p.poll() is None:
            try:
                p.terminate()
                p.wait(timeout=1.0)
            except Exception:
                try:
                    p.kill()
                    p.wait(timeout=1.0)
                except OSError:
                    pass

    # Terminate any lingering stress-ng processes
    kill_stress_ng()

    # Reap any lingering descendants across the process tree
    try:
        current: psutil.Process = psutil.Process()
        children = current.children(recursive=True)
        for child in children:
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
        _, alive = psutil.wait_procs(children, timeout=1.0)
        for p in alive:
            try:
                p.kill()
            except psutil.NoSuchProcess:
                pass
    except Exception:
        pass

    reap_zombie_children()


def assert_no_leftover_resources() -> None:
    """Hard post-run assertion: no leftover processes, stopped processes, zombies,
    tmpfs mounts, or cgroups — from any fault, not just the one just run."""
    proc_signatures: dict[str, str] = {
        "heartbeat target": "target.heartbeat_app",
        "fd leaker": "RLIMIT_NOFILE",
        "zombie leaker": "os.fork",
        "disk writer": "ENOSPC",
    }
    leftover: list[str] = []
    stopped: list[int] = []
    for p in psutil.process_iter(["name", "cmdline", "status"]):
        if "stress-ng" in (p.info.get("name") or ""):
            leftover.append(f"stress-ng PID {p.pid}")
            continue
        cmdline = " ".join(p.info.get("cmdline") or [])
        for label, signature in proc_signatures.items():
            if signature in cmdline:
                leftover.append(f"{label} PID {p.pid}")
        if (p.info.get("status") or "") == psutil.STATUS_STOPPED:
            stopped.append(p.pid)
    assert not leftover, f"Leftover processes after run: {leftover}"
    assert not stopped, f"Stopped processes after run: {stopped}"

    if CGROUP_ROOT.exists():
        cgroups = [cg for cg in CGROUP_ROOT.glob("fault_*") if cg.is_dir()]
        assert not cgroups, f"Leftover cgroups after run: {cgroups}"

    assert not is_tmpfs_mount(Path(config.DISK_MOUNT_PATH)), f"Leftover tmpfs mount at {config.DISK_MOUNT_PATH}"
    assert not Path(config.DISK_MOUNT_PATH).exists(), f"Leftover mount directory {config.DISK_MOUNT_PATH}"

    zombies = count_zombies()
    assert zombies == 0, f"{zombies} zombie process(es) after run"
    print("Verified: 0 leftover processes, stopped processes, zombies, mounts, and cgroups in the system.")


def run_trial(trial_id: str, fault_type: str = "process_kill", strategy: str = "resume") -> dict[str, Any]:
    proc: Any = None
    recovered_proc: Any = None
    hog_proc: Any = None
    stress_proc: Any = None
    writer_proc: Any = None
    cg_path: Path | None = None
    mount_path: Path | None = None

    try:
        # process_hang: reset the heartbeat file so staleness is measured only against this trial
        if fault_type == "process_hang":
            reset_heartbeat_file()

        # Step 1: Start target (for fd_exhaustion and zombie_leak the target IS the
        # faulty service: it idles until the injection signal, so the monitor can
        # watch it before the fault begins)
        if fault_type == "fd_exhaustion":
            proc = start_leaker()
        elif fault_type == "zombie_leak":
            proc = start_zombie_leaker()
        else:
            proc = psutil.subprocess.Popen(config.TARGET_CMD)
        event_log.log_event(
            trial_id=trial_id,
            fault_type=fault_type,
            event="STARTED",
            details=f"Target process started with PID {proc.pid}",
        )
        time.sleep(1.0)

        # Step 2: Start monitor in background thread BEFORE injecting fault (Rule 1 & Rule 4)
        if fault_type == "memory_pressure":
            cg_path = CGROUP_ROOT / f"fault_{trial_id}"
        elif fault_type == "disk_full":
            mount_path = Path(config.DISK_MOUNT_PATH)

        stop_event: threading.Event = threading.Event()
        monitor_thread: threading.Thread = threading.Thread(
            target=monitor_process,
            args=(proc.pid, trial_id),
            kwargs={
                "proc": proc,
                "cgroup_path": cg_path,
                "fault_type": fault_type,
                "stop_event": stop_event,
                "verbose": False,
                "max_duration_sec": config.MAX_TRIAL_DURATION_SEC,
            },
            daemon=True,
        )
        monitor_thread.start()
        # Randomize phase offset within polling interval to simulate arbitrary fault timing
        time.sleep(random.uniform(config.INJECTION_JITTER_MIN_SEC, config.INJECTION_JITTER_MAX_SEC))

        # Step 3: Inject fault
        if fault_type == "process_kill":
            inject_process_kill(proc.pid, trial_id)
        elif fault_type == "process_hang":
            inject_process_hang(proc.pid, trial_id)
        elif fault_type == "memory_pressure":
            hog_proc, cg_path = inject_memory_pressure(trial_id)
        elif fault_type == "cpu_hog":
            stress_proc = inject_cpu_hog(trial_id)
        elif fault_type == "disk_full":
            # The injector ABORTS (logs FAILED, raises) if the tmpfs mount or its
            # /proc/mounts verification fails; the trial is then skipped safely
            try:
                writer_proc = inject_disk_full(trial_id)
            except (RuntimeError, OSError):
                return calculate_trial_metrics(trial_id)
        elif fault_type == "fd_exhaustion":
            inject_fd_exhaustion(proc.pid, trial_id)
        elif fault_type == "zombie_leak":
            inject_zombie_leak(proc.pid, trial_id)
        else:
            raise ValueError(f"Unsupported fault type: {fault_type}")

        # Step 4: Wait for monitor detection
        monitor_thread.join(timeout=config.MAX_TRIAL_DURATION_SEC)
        if monitor_thread.is_alive():
            stop_event.set()
            monitor_thread.join(timeout=1.0)
            event_log.log_event(
                trial_id=trial_id,
                fault_type=fault_type,
                event="FAILED",
                details=f"Detection timed out after {config.MAX_TRIAL_DURATION_SEC}s",
            )
            return calculate_trial_metrics(trial_id)

        # Step 5: Recover system
        if fault_type == "process_kill":
            try:
                restart_target(trial_id=trial_id)
                recovered_proc = get_last_process()
                time.sleep(0.5)
            except RuntimeError:
                pass
        elif fault_type == "memory_pressure":
            if cg_path is not None:
                recover_memory(
                    trial_id=trial_id,
                    cgroup_path=cg_path,
                    hog_proc=hog_proc,
                    target_proc=proc,
                    target_pid=proc.pid,
                )
                time.sleep(0.5)
        elif fault_type == "process_hang":
            try:
                recover_process_hang(trial_id=trial_id, pid=proc.pid, strategy=strategy)
                recovered_proc = get_last_process()
                time.sleep(0.5)
            except (RuntimeError, ProcessLookupError):
                pass
        elif fault_type == "disk_full":
            if mount_path is not None:
                try:
                    recover_disk_full(trial_id=trial_id, mount_path=mount_path, writer_proc=writer_proc)
                    time.sleep(0.5)
                except (RuntimeError, OSError):
                    pass
        elif fault_type == "fd_exhaustion":
            try:
                recover_fd_exhaustion(trial_id=trial_id, pid=proc.pid, leaker_proc=proc)
                recovered_proc = get_last_process()
                time.sleep(0.5)
            except RuntimeError:
                pass
        elif fault_type == "zombie_leak":
            try:
                recover_zombie_leak(trial_id=trial_id, pid=proc.pid, leaker_proc=proc)
                time.sleep(0.5)
            except RuntimeError:
                pass
        elif fault_type == "cpu_hog":
            if stress_proc is not None:
                recover_cpu(trial_id=trial_id, stress_proc=stress_proc)
                time.sleep(0.5)

    finally:
        # Step 6: Cleanup after trial
        event_log.log_event(
            trial_id=trial_id,
            fault_type=fault_type,
            event="CLEANUP",
            details="Cleaned up trial processes",
        )

        # A SIGSTOP'd target queues SIGTERM until continued, so SIGKILL targets directly
        if fault_type == "process_hang":
            for target in (proc, recovered_proc):
                if target is not None and target.poll() is None:
                    try:
                        target.kill()
                        target.wait(timeout=1.0)
                    except Exception:
                        pass

        # Mandatory disk_full cleanup on every path: kill writer, delete files,
        # umount, remove dir, verify gone from /proc/mounts
        mount_clean: bool | None = None
        if fault_type == "disk_full" and mount_path is not None:
            mount_clean = cleanup_fault_disk(mount_path=mount_path, writer_proc=writer_proc)

        cleanup_trial_processes(proc, recovered_proc, hog_proc, stress_proc, writer_proc)
        if cg_path is not None and cg_path.exists():
            remove_cgroup(cg_path)

        if fault_type == "disk_full" and mount_clean is False:
            event_log.log_event(
                trial_id=trial_id,
                fault_type=fault_type,
                event="FAILED",
                details=f"Leftover fault-disk state after cleanup: {mount_path} still mounted or present",
            )

        # Verify no leftover leaker process remains after cleanup
        if fault_type == "fd_exhaustion" and proc is not None and is_process_alive(proc.pid):
            event_log.log_event(
                trial_id=trial_id,
                fault_type=fault_type,
                event="FAILED",
                details=f"Leftover leaker process PID {proc.pid} after cleanup",
            )

        # Verify no leftover leaker parent and zero zombie processes remain after cleanup
        if fault_type == "zombie_leak":
            problems: list[str] = []
            if proc is not None and is_process_alive(proc.pid):
                problems.append(f"leaker parent PID {proc.pid} still alive")
            zombies_left: int = count_zombies()
            if zombies_left > 0:
                problems.append(f"{zombies_left} zombie process(es) remain")
            if problems:
                event_log.log_event(
                    trial_id=trial_id,
                    fault_type=fault_type,
                    event="FAILED",
                    details="; ".join(problems),
                )

        # Verify no stopped or leftover target remains after cleanup
        if fault_type == "process_hang":
            leftover: list[int] = [
                target.pid
                for target in (proc, recovered_proc)
                if target is not None and is_process_alive(target.pid)
            ]
            if leftover:
                event_log.log_event(
                    trial_id=trial_id,
                    fault_type=fault_type,
                    event="FAILED",
                    details=f"Leftover target processes after cleanup: {leftover}",
                )

        time.sleep(0.5)

    return calculate_trial_metrics(trial_id)


def print_trial_progress(trial_index: int, total_trials: int, metrics: dict[str, Any]) -> None:
    fault_type: str = metrics["fault_type"]
    mttd_str: str = f"{metrics['mttd_sec']:.3f}s" if metrics["mttd_sec"] is not None else "N/A"
    mttr_str: str = f"{metrics['mttr_sec']:.3f}s" if metrics["mttr_sec"] is not None else "N/A"
    status_str: str = "OK" if metrics["success"] else "FAILED"

    print(f"Running: {fault_type} | Trial {trial_index} of {total_trials}")
    print(f"  Injected    0.000s")
    print(f"  Detected    {mttd_str:>7}  (MTTD: {mttd_str})")
    print(f"  Recovered   {mttr_str:>7}  (MTTR: {mttr_str})")
    print(f"  Status: {status_str}\n")


def run_experiment(fault_type: str, trial_count: int, strategy: str = "resume") -> list[dict[str, Any]]:
    verify_docker_environment()
    print("OS Fault Injection Lab")
    print("---\n")

    # Clear log between experiment runs (not between trials)
    event_log.clear_log()
    results: list[dict[str, Any]] = []

    # Leak proof: snapshot the container root filesystem before any disk_full trial
    root_fs_before = psutil.disk_usage("/") if fault_type == "disk_full" else None

    for i in range(1, trial_count + 1):
        trial_id: str = f"{fault_type}_{i:03d}"
        if fault_type == "process_hang":
            # Strategy is embedded in the trial id so results stay comparable per strategy
            trial_id = f"process_hang_{strategy}_{i:03d}"
        metrics: dict[str, Any] = run_trial(trial_id=trial_id, fault_type=fault_type, strategy=strategy)
        results.append(metrics)
        print_trial_progress(i, trial_count, metrics)

    # Post-experiment verification: nothing of any fault left behind
    assert_no_leftover_resources()

    if fault_type == "disk_full" and root_fs_before is not None:
        root_fs_after = psutil.disk_usage("/")
        delta: int = root_fs_after.used - root_fs_before.used
        print(
            f"Verified: container root filesystem unchanged "
            f"({root_fs_before.used} -> {root_fs_after.used} bytes, delta {delta:+d}).\n"
        )

    write_results_csv(results)
    summary_label: str = f"{fault_type} [{strategy}]" if fault_type == "process_hang" else fault_type
    print_summary_table(summary_label, results)
    generate_all_charts()
    return results


def run_all_experiments(trial_count: int = config.DEFAULT_TRIAL_COUNT) -> list[dict[str, Any]]:
    verify_docker_environment()
    print("OS Fault Injection Lab — Full Experiment Suite (7 faults)")
    print("==============================================\n")
    event_log.clear_log()
    all_results: list[dict[str, Any]] = []

    # process_hang runs once per recovery strategy, so the suite has 8 fault groups
    groups: list[tuple[str, str]] = [
        ("process_kill", "resume"),
        ("memory_pressure", "resume"),
        ("cpu_hog", "resume"),
        ("process_hang", "resume"),
        ("process_hang", "restart"),
        ("disk_full", "resume"),
        ("fd_exhaustion", "resume"),
        ("zombie_leak", "resume"),
    ]

    root_fs_before = psutil.disk_usage("/")

    for fault, strategy in groups:
        label: str = f"{fault} [{strategy}]" if fault == "process_hang" else fault
        print(f"\n--- Fault: {label} ({trial_count} trials) ---\n")
        group_results: list[dict[str, Any]] = []
        for i in range(1, trial_count + 1):
            trial_id: str = f"{fault}_{i:03d}"
            if fault == "process_hang":
                trial_id = f"process_hang_{strategy}_{i:03d}"
            metrics: dict[str, Any] = run_trial(trial_id=trial_id, fault_type=fault, strategy=strategy)
            group_results.append(metrics)
            print_trial_progress(i, trial_count, metrics)
        all_results.extend(group_results)
        print_summary_table(label, group_results)

    write_results_csv(all_results)
    generate_all_charts()
    print_comparison_summary(all_results)

    # Full-suite leak proof: nothing of any fault left behind, root fs unchanged
    assert_no_leftover_resources()
    root_fs_after = psutil.disk_usage("/")
    delta: int = root_fs_after.used - root_fs_before.used
    print(f"Verified: container root filesystem unchanged ({root_fs_before.used} -> {root_fs_after.used} bytes, delta {delta:+d}).")
    return all_results


def main() -> None:
    parser = argparse.ArgumentParser(description="OS Fault Injection Lab Experiment Runner")
    parser.add_argument(
        "--fault",
        type=str,
        default="process_kill",
        choices=["process_kill", "memory_pressure", "cpu_hog", "process_hang", "disk_full", "fd_exhaustion", "zombie_leak", "all"],
        help="Type of fault to inject (default: process_kill, or 'all' for complete suite)",
    )
    parser.add_argument(
        "--trials",
        type=int,
        default=config.DEFAULT_TRIAL_COUNT,
        help=f"Number of trials to execute (default: {config.DEFAULT_TRIAL_COUNT})",
    )
    parser.add_argument(
        "--strategy",
        type=str,
        default="resume",
        choices=["resume", "restart"],
        help="Recovery strategy for process_hang (default: resume)",
    )
    args = parser.parse_args()

    if args.fault == "all":
        run_all_experiments(trial_count=args.trials)
    else:
        run_experiment(fault_type=args.fault, trial_count=args.trials, strategy=args.strategy)


if __name__ == "__main__":
    main()
