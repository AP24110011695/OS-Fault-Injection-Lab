import os
import signal
import subprocess
from typing import Any

import psutil

import config
import event_log

# The leaker parent: idle until SIGUSR1, then forks short-lived children it NEVER
# reaps (no wait/waitpid/poll), so they pile up as zombies. os.fork + os._exit is
# mandatory: subprocess/multiprocessing children would be reaped automatically.
# SIGCHLD is left at its default (SIG_DFL) — SIG_IGN would make the kernel auto-reap.
LEAKER_CODE: str = (
    "import os, signal, sys, time\n"
    "max_children = int(sys.argv[1])\n"
    "state = {'spawn': False, 'count': 0}\n"
    "def start_spawn(signum, frame):\n"
    "    state['spawn'] = True\n"
    "signal.signal(signal.SIGUSR1, start_spawn)\n"
    "while True:\n"
    "    if state['spawn'] and state['count'] < max_children:\n"
    "        pid = os.fork()\n"
    "        if pid == 0:\n"
    "            os._exit(0)  # child exits immediately; the parent never waits\n"
    "        state['count'] += 1\n"
    "    time.sleep(0.05)\n"
)


def start_zombie_leaker(max_children: int = config.ZOMBIE_LEAK_MAX_CHILDREN) -> subprocess.Popen[Any]:
    """Start the leaker parent for the trial: idle until the injection signal,
    then spawns up to max_children short-lived children it never reaps."""
    return subprocess.Popen(["python", "-c", LEAKER_CODE, str(max_children)])


def inject(target_pid: int, trial_id: str) -> None:
    if not psutil.pid_exists(target_pid):
        error_msg: str = f"Cannot signal leaker parent PID {target_pid}: process does not exist"
        event_log.log_event(trial_id=trial_id, fault_type="zombie_leak", event="FAILED", details=error_msg)
        raise ProcessLookupError(error_msg)

    # SIGUSR1 tells the leaker parent to begin forking unreaped children
    os.kill(target_pid, signal.SIGUSR1)
    event_log.log_event(
        trial_id=trial_id,
        fault_type="zombie_leak",
        event="INJECTED",
        details=f"SIGUSR1 sent to leaker parent PID {target_pid}: spawning up to {config.ZOMBIE_LEAK_MAX_CHILDREN} unreaped children",
    )


if __name__ == "__main__":
    import time

    from monitor.detector import count_zombie_children
    from recovery.resource_recovery import count_zombies, recover_zombie_leak

    print("Testing zombie_leak injector...")
    trial_id: str = "manual_zombie_test"
    event_log.clear_log()

    leaker = start_zombie_leaker()
    print(f"Leaker parent launched with PID {leaker.pid}")
    time.sleep(0.3)
    inject(leaker.pid, trial_id)
    print("Spawning triggered; watching zombie children climb...")
    zombies: int = 0
    for _ in range(60):
        time.sleep(0.2)
        zombies = count_zombie_children(leaker.pid)
        if zombies > config.ZOMBIE_THRESHOLD:
            break
    print(f"Zombie children of leaker parent: {zombies}")
    assert zombies > config.ZOMBIE_THRESHOLD, "Zombies should accumulate above the threshold"
    assert psutil.pid_exists(leaker.pid), "Leaker parent must stay alive while leaking"

    rec: bool = recover_zombie_leak(trial_id=trial_id, pid=leaker.pid, leaker_proc=leaker)
    print(f"Recovery status: {rec}")
    remaining: int = count_zombies()
    print(f"Zombies container-wide after recovery: {remaining}")
    assert remaining == 0, "All zombies must be gone after recovery"

    leaker.wait(timeout=1.0)
    events = event_log.read_events(trial_id=trial_id)
    for e in events:
        print(f"  [{e['timestamp']}] {e['event']}: {e['details']}")

    print("\nOK: zombie_leak injector test completed.")
