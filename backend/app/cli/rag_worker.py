"""Background RAG sync worker.

    python -m app.cli.rag_worker           # drain the queue once and exit
    python -m app.cli.rag_worker --loop    # keep draining every few seconds

In a normal single-user run the app can also auto-drain after uploads (set
BEACON_RAG_AUTOSYNC=1); this CLI is the standalone worker for when autosync is
off or you want a dedicated process.
"""

import sys
import time

from app.services.rag_sync_service import drain_queue

POLL_SECONDS = 5


def main() -> None:
    loop = "--loop" in sys.argv
    while True:
        result = drain_queue()
        if result["processed"] or result["failed"]:
            print(
                f"Processed {result['processed']} job(s), "
                f"{result['failed']} failed."
            )
        if not loop:
            break
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
