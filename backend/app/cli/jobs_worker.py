"""Standalone jobs worker (Phase 19).

    python -m app.cli.jobs_worker           # drain the queue once and exit
    python -m app.cli.jobs_worker --loop    # keep draining every few seconds

The same runner the app drives in-process (BEACON_JOBS_RUNNER=1); run this
as a separate process instead when you want the web worker to stay idle.
"""

import os
import sys
import time

from app.services.jobs.runner import drain_once

POLL_SECONDS = 5


def main() -> None:
    loop = "--loop" in sys.argv
    worker_id = f"cli-{os.getpid()}"
    while True:
        counts = drain_once(worker_id)
        if counts["claimed"] or counts["reclaimed"]:
            print(
                f"claimed {counts['claimed']}, completed {counts['completed']}, "
                f"requeued {counts['requeued']}, dead {counts['dead']}, "
                f"reclaimed {counts['reclaimed']}"
            )
        if not loop:
            break
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
