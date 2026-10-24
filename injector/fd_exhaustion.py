import os
import signal
import subprocess
from typing import Any

import psutil

import config
import event_log

# The faulty service: it lowers ITS OWN RLIMIT_NOFILE at startup (only this process
# is affected), idles until SIGUSR1, then opens /dev/null repeatedly until EMFILE
# and keeps running. Keeping the fds open is the leak; nothing is printed.
LEAKER_CODE: str = (
    "import resource, signal, sys, time\n"
    "resource.setrlimit(resource.RLIMIT_NOFILE, (int(sys.argv[1]), int(sys.argv[1])))\n"
    "fds = []\n"
    "state = {'leak': False}\n"
    "def start_leak(signum, frame):\n"
    "    state['leak'] = True\n"
    "signal.signal(signal.SIGUSR1, start_leak)\n"
    "while True:\n"
    "    if state['leak']:\n"
    "        try:\n"
    "            fds.append(open('/dev/null', 'w'))\n"
    "        except OSError:\n"
    "            pass  # EMFILE: keep running like a leaking service would\n"
    "    time.sleep(0.02)\n"
)


def start_leaker(limit: int = config.FD_LIMIT) -> subprocess.Popen[Any]:
    """Start the faulty service for the trial: it caps its own fd limit at startup
    and waits for the injection signal. Started in Step 1 so the monitor can watch
    it before the leak begins."""
    return subprocess.Popen(["python", "-c", LEAKER_CODE, str(limit)])


def inject(target_pid: int, trial_id: str) -> None:
    if not psutil.pid_exists(target_pid):
        error_msg: str = f"Cannot signal leaker PID {target_pid}: process does not exist"
        event_log.log_event(trial_id=trial_id, fault_type="fd_exhaustion", event="FAILED", details=error_msg)
        raise ProcessLookupError(error_msg)

    # SIGUSR1 tells the leaker to begin opening file descriptors
    os.kill(target_pid, signal.SIGUSR1)

    soft_limit: int = psutil.Process(target_pid).rlimit(psutil.RLIMIT_NOFILE)[0]
    event_log.log_event(
        trial_id=trial_id,
        fault_type="fd_exhaustion",
        event="INJECTED",
        details=f"SIGUSR1 sent to leaker PID {target_pid}: fd leak begins (own RLIMIT_NOFILE soft={soft_limit})",
    )


if __name__ == "__main__":
    import time

    from recovery.supervisor import recover_fd_exhaustion

    print("Testing fd_exhaustion injector...")
    trial_id: str = "manual_fd_test"
    event_log.clear_log()

    leaker = start_leaker()
    print(f"Leaker launched with PID {leaker.pid}")
    time.sleep(0.5)
    soft: int = psutil.Process(leaker.pid).rlimit(psutil.RLIMIT_NOFILE)[0]
    print(f"Leaker's own RLIMIT_NOFILE soft limit: {soft}")
    assert soft == config.FD_LIMIT, f"Leaker should have capped its own limit to {config.FD_LIMIT}"

    inject(leaker.pid, trial_id)
    print("Leak triggered; watching fd count climb...")
    for _ in range(100):
        time.sleep(0.1)
        num_fds: int = psutil.Process(leaker.pid).num_fds()
        if num_fds >= soft - 2:
            break
    print(f"Leaker at {num_fds}/{soft} fds (EMFILE plateau)")

    alive: bool = psutil.pid_exists(leaker.pid)
    print(f"Leaker still alive at EMFILE: {alive}")
    assert alive, "Leaker must keep running after EMFILE"

    new_pid: int = recover_fd_exhaustion(trial_id=trial_id, pid=leaker.pid, leaker_proc=leaker)
    clean_fds: int = psutil.Process(new_pid).num_fds()
    print(f"Fresh clean instance PID {new_pid} with {clean_fds} fds")
    assert clean_fds < config.FD_CLEAN_MAX_FDS, "Clean instance should have few fds"

    leaker.wait(timeout=1.0)
    events = event_log.read_events(trial_id=trial_id)
    for e in events:
        print(f"  [{e['timestamp']}] {e['event']}: {e['details']}")

    print("\nOK: fd_exhaustion injector test completed.")
