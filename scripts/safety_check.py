import importlib
import shutil
import sys
from pathlib import Path


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

    if verbose:
        print("[x] Docker environment verified")
        print("[x] cgroups v2 available (/sys/fs/cgroup)")
        print("[x] stress-ng binary available")
        print("[x] psutil library importable")
    print("OK: Safety checks passed (Docker, cgroups v2, stress-ng, psutil)")


if __name__ == "__main__":
    verify_docker_environment(verbose=True)
