import os
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

import config

_RUNNING: bool = True


def handle_sigterm(signum: int, frame: object) -> None:
    global _RUNNING
    _RUNNING = False
    print(f"[heartbeat] PID {os.getpid()} received SIGTERM, exiting cleanly.", flush=True)
    sys.exit(0)


def run_heartbeat() -> None:
    signal.signal(signal.SIGTERM, handle_sigterm)
    pid: int = os.getpid()
    print(f"[heartbeat] Target application started with PID {pid}", flush=True)

    heartbeat_path: Path = Path(config.HEARTBEAT_FILE_PATH)
    heartbeat_path.parent.mkdir(parents=True, exist_ok=True)

    counter: int = 0
    buffer: list[int] = []

    while _RUNNING:
        counter += 1
        now: str = datetime.now().isoformat()
        # Maintain active memory pages to simulate a running service
        buffer.append(counter % 1000)
        if len(buffer) > 10000:
            buffer.clear()

        # Timestamps in a file let the monitor measure freshness (process_hang detection)
        with open(heartbeat_path, "a", encoding="utf-8") as hb:
            hb.write(f"{now}\n")

        print(f"[heartbeat] PID {pid} alive at {now} (tick {counter})", flush=True)
        time.sleep(1.0)


if __name__ == "__main__":
    run_heartbeat()
