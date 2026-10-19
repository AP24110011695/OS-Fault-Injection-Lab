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
from injector.memory_pressure import CGROUP_ROOT, inject as inject_memory_pressure
from injector.process_kill import inject as inject_process_kill
from monitor.monitor import monitor_process
from recovery.resource_recovery import (
    kill_stress_ng,
    reap_zombie_children,
    recover_cpu,
    recover_memory,
    remove_cgroup,
)
from recovery.supervisor import get_last_process, restart_target
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


def run_trial(trial_id: str, fault_type: str = "process_kill") -> dict[str, Any]:
    proc: Any = None
    recovered_proc: Any = None
    hog_proc: Any = None
    stress_proc: Any = None
    cg_path: Path | None = None

    try:
        # Step 1: Start target
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
        elif fault_type == "memory_pressure":
            hog_proc, cg_path = inject_memory_pressure(trial_id)
        elif fault_type == "cpu_hog":
            stress_proc = inject_cpu_hog(trial_id)
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
        cleanup_trial_processes(proc, recovered_proc, hog_proc, stress_proc)
        if cg_path is not None and cg_path.exists():
            remove_cgroup(cg_path)
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


def run_experiment(fault_type: str, trial_count: int) -> list[dict[str, Any]]:
    verify_docker_environment()
    print("OS Fault Injection Lab")
    print("---\n")

    # Clear log between experiment runs (not between trials)
    event_log.clear_log()
    results: list[dict[str, Any]] = []

    for i in range(1, trial_count + 1):
        trial_id: str = f"{fault_type}_{i:03d}"
        metrics: dict[str, Any] = run_trial(trial_id=trial_id, fault_type=fault_type)
        results.append(metrics)
        print_trial_progress(i, trial_count, metrics)

    # Post-experiment verification: zero lingering cgroups
    if fault_type == "memory_pressure" and CGROUP_ROOT.exists():
        leftovers = [p for p in CGROUP_ROOT.glob("fault_*") if p.is_dir()]
        assert len(leftovers) == 0, f"Found {len(leftovers)} leftover cgroup(s) after experiment: {leftovers}"
        print("Verified: 0 leftover cgroup directories in /sys/fs/cgroup.\n")

    # Post-experiment verification: zero lingering stress-ng processes
    if fault_type == "cpu_hog":
        lingering = [p for p in psutil.process_iter(["name"]) if "stress-ng" in (p.info.get("name") or "")]
        assert len(lingering) == 0, f"Found {len(lingering)} lingering stress-ng processes after experiment: {lingering}"
        print("Verified: 0 leftover stress-ng processes in the system.\n")

    write_results_csv(results)
    print_summary_table(fault_type, results)
    generate_all_charts()
    return results


def run_all_experiments(trial_count: int = config.DEFAULT_TRIAL_COUNT) -> list[dict[str, Any]]:
    verify_docker_environment()
    print("OS Fault Injection Lab — Full Experiment Suite")
    print("==============================================\n")
    event_log.clear_log()
    all_results: list[dict[str, Any]] = []

    for fault in ["process_kill", "memory_pressure", "cpu_hog"]:
        print(f"\n--- Fault: {fault} ({trial_count} trials) ---\n")
        fault_results: list[dict[str, Any]] = []
        for i in range(1, trial_count + 1):
            trial_id: str = f"{fault}_{i:03d}"
            metrics: dict[str, Any] = run_trial(trial_id=trial_id, fault_type=fault)
            fault_results.append(metrics)
            print_trial_progress(i, trial_count, metrics)

        if fault == "memory_pressure" and CGROUP_ROOT.exists():
            leftovers = [p for p in CGROUP_ROOT.glob("fault_*") if p.is_dir()]
            assert len(leftovers) == 0, f"Found {len(leftovers)} leftover cgroup(s): {leftovers}"

        if fault == "cpu_hog":
            lingering = [p for p in psutil.process_iter(["name"]) if "stress-ng" in (p.info.get("name") or "")]
            assert len(lingering) == 0, f"Found {len(lingering)} lingering stress-ng processes: {lingering}"

        all_results.extend(fault_results)
        print_summary_table(fault, fault_results)

    write_results_csv(all_results)
    generate_all_charts()
    print_comparison_summary(all_results)
    return all_results


def main() -> None:
    parser = argparse.ArgumentParser(description="OS Fault Injection Lab Experiment Runner")
    parser.add_argument(
        "--fault",
        type=str,
        default="process_kill",
        choices=["process_kill", "memory_pressure", "cpu_hog", "all"],
        help="Type of fault to inject (default: process_kill, or 'all' for complete suite)",
    )
    parser.add_argument(
        "--trials",
        type=int,
        default=config.DEFAULT_TRIAL_COUNT,
        help=f"Number of trials to execute (default: {config.DEFAULT_TRIAL_COUNT})",
    )
    args = parser.parse_args()

    if args.fault == "all":
        run_all_experiments(trial_count=args.trials)
    else:
        run_experiment(fault_type=args.fault, trial_count=args.trials)


if __name__ == "__main__":
    main()
