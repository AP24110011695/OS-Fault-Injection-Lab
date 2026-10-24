import importlib
import shutil
import subprocess
import sys
from pathlib import Path

# Ensure project root is importable when executed directly as a script
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from injector.disk_full import is_tmpfs_mount


def is_inside_docker() -> bool:
    if Path("/.dockerenv").exists():
        return True

    cgroup_path = Path("/proc/1/cgroup")
    if cgroup_path.exists():
        try:
            content = cgroup_path.read_text(encoding="utf-8")
            if "docker" in content or "containerd" in content:
                return True
        except (OSError, UnicodeDecodeError):
            pass

    return False


def is_cgroup_v2_available() -> bool:
    cgroup_root = Path("/sys/fs/cgroup")
    controllers_file = cgroup_root / "cgroup.controllers"
    return cgroup_root.is_dir() and controllers_file.exists()


def is_stress_ng_available() -> bool:
    return shutil.which("stress-ng") is not None


def is_psutil_available() -> bool:
    try:
        importlib.import_module("psutil")
        return True
    except ImportError:
        return False


def is_tmpfs_mounting_available() -> bool:
    """Mount a 1MB tmpfs, verify it via /proc/mounts, and clean it up —
    leaving nothing behind whether the check passes or fails."""
    mount_path = Path("/tmp/safety_check_tmpfs")
    mounted = False
    try:
        mount_path.mkdir(parents=True, exist_ok=True)
        result: subprocess.CompletedProcess[str] = subprocess.run(
            ["mount", "-t", "tmpfs", "-o", "size=1m", "tmpfs", str(mount_path)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        mounted = result.returncode == 0 and is_tmpfs_mount(mount_path, expected_size_mb=1)
        return mounted
    except OSError:
        return False
    finally:
        subprocess.run(["umount", str(mount_path)], capture_output=True, text=True, timeout=10)
        try:
            mount_path.rmdir()
        except OSError:
            pass


def verify_docker_environment(verbose: bool = False) -> None:
    if not is_inside_docker():
        print(
            "ERROR: Not running inside Docker. Fault injection is disabled for safety.\n"
            "       Run this project with: docker compose up --build",
            file=sys.stderr,
        )
        sys.exit(1)

    if not is_cgroup_v2_available():
        print(
            "ERROR: cgroups v2 is not available at /sys/fs/cgroup.\n"
            "       Ensure Docker container runs with cgroups v2 enabled.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not is_stress_ng_available():
        print(
            "ERROR: stress-ng is not installed or not in PATH.\n"
            "       Ensure Dockerfile installs stress-ng.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not is_psutil_available():
        print(
            "ERROR: psutil is not importable.\n"
            "       Ensure dependencies are installed via requirements.txt.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not is_tmpfs_mounting_available():
        print(
            "ERROR: tmpfs mounting is not available (required by the disk_full fault).\n"
            "       Ensure the container runs privileged and 'mount' is installed.",
            file=sys.stderr,
        )
        sys.exit(1)

    if verbose:
        print("[x] Docker environment verified")
        print("[x] cgroups v2 available (/sys/fs/cgroup)")
        print("[x] stress-ng binary available")
        print("[x] psutil library importable")
        print("[x] tmpfs mounting available (verified and cleaned up)")
    print("OK: Safety checks passed (Docker, cgroups v2, stress-ng, psutil, tmpfs mount)")


if __name__ == "__main__":
    verify_docker_environment(verbose=True)
