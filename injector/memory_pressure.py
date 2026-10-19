import subprocess
import time
from pathlib import Path
from typing import Any

import config
import event_log

CGROUP_ROOT: Path = Path("/sys/fs/cgroup")


def ensure_cgroup_root_ready() -> None:
    """Ensure root cgroup has empty processes so subtree_control can delegate controllers."""
    subtree = CGROUP_ROOT / "cgroup.subtree_control"
    if not subtree.exists():
        raise RuntimeError("cgroups v2 not available: /sys/fs/cgroup/cgroup.subtree_control missing")

    current_controllers = subtree.read_text(encoding="utf-8").strip()
    if "memory" in current_controllers:
        return

    # Move any processes in root cgroup to /sys/fs/cgroup/init to satisfy cgroups v2 no-internal-processes rule
    init_cg = CGROUP_ROOT / "init"
    init_cg.mkdir(exist_ok=True)
    root_procs_file = CGROUP_ROOT / "cgroup.procs"
    if root_procs_file.exists():
        for pid in root_procs_file.read_text(encoding="utf-8").split():
            try:
                (init_cg / "cgroup.procs").write_text(f"{pid}\n", encoding="utf-8")
            except OSError:
                pass

    try:
        subtree.write_text("+memory +cpu\n", encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"Failed to enable memory controller in cgroup.subtree_control: {exc}") from exc


def setup_memory_cgroup(trial_id: str, limit_mb: int = config.CGROUP_MEMORY_LIMIT_MB) -> Path:
    ensure_cgroup_root_ready()
    cg_path = CGROUP_ROOT / f"fault_{trial_id}"
    cg_path.mkdir(exist_ok=True)

    # Set hard memory limit
    limit_bytes: int = limit_mb * 1024 * 1024
    (cg_path / "memory.max").write_text(str(limit_bytes), encoding="utf-8")

    # Disable swap for this cgroup so the OOM killer triggers immediately on limit breach
    swap_max_file = cg_path / "memory.swap.max"
    if swap_max_file.exists():
        try:
            swap_max_file.write_text("0", encoding="utf-8")
        except OSError:
            pass

    return cg_path


def inject(trial_id: str, limit_mb: int = config.CGROUP_MEMORY_LIMIT_MB) -> tuple[subprocess.Popen[Any], Path]:
    cg_path = setup_memory_cgroup(trial_id=trial_id, limit_mb=limit_mb)

    # Python memory hog that rapidly allocates resident bytearrays in chunks
    hog_code = (
        "import time\n"
        "time.sleep(0.05)\n"
        "chunks = []\n"
        "while True:\n"
        "    chunks.append(bytearray(8 * 1024 * 1024))\n"
        "    time.sleep(0.05)\n"
    )
    proc = subprocess.Popen(["python", "-c", hog_code])

    # Move hog process into the memory-constrained cgroup
    try:
        (cg_path / "cgroup.procs").write_text(f"{proc.pid}\n", encoding="utf-8")
    except OSError as exc:
        proc.kill()
        proc.wait()
        cg_path.rmdir()
        error_msg = f"Failed to attach hog PID {proc.pid} to cgroup: {exc}"
        event_log.log_event(trial_id, "memory_pressure", "FAILED", error_msg)
        raise RuntimeError(error_msg) from exc

    event_log.log_event(
        trial_id=trial_id,
        fault_type="memory_pressure",
        event="INJECTED",
        details=f"Memory hog PID {proc.pid} launched in cgroup {cg_path.name} with limit {limit_mb}MB",
    )
    return proc, cg_path


if __name__ == "__main__":
    print("Testing memory_pressure injector...")
    trial_id: str = "manual_mem_test"
    event_log.clear_log()

    hog_proc, cg_dir = inject(trial_id, limit_mb=32)
    print(f"Hog PID: {hog_proc.pid}, Cgroup: {cg_dir}")

    # Observe memory allocation and OOM kill
    for _ in range(20):
        time.sleep(0.1)
        cur = (cg_dir / "memory.current").read_text().strip()
        max_b = (cg_dir / "memory.max").read_text().strip()
        print(f"  cgroup memory: {int(cur)//1024//1024}MB / {int(max_b)//1024//1024}MB")
        if hog_proc.poll() is not None:
            print(f"Hog exited with returncode {hog_proc.returncode}")
            events = (cg_dir / "memory.events").read_text().strip()
            print(f"memory.events:\n{events}")
            break

    # Clean up
    try:
        cg_dir.rmdir()
        print("Cgroup removed successfully.")
    except Exception as e:
        print(f"Failed to remove cgroup: {e}")

    print("OK: Memory pressure injector test complete.")
