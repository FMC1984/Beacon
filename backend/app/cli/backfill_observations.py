"""Derive Observatory observations for every stored AI response that has
none yet, then rebuild the daily rollups (Phase 19, slice 3).

    python -m app.cli.backfill_observations

Idempotent: safe to re-run after alias or domain edits (pass --rederive to
recompute every response, not only the missing ones).
"""

import sys

from app.db import SessionLocal
from app.models import AIVisibilityQuery
from app.services.observatory.derivation import backfill_observations, rederive_response
from app.services.observatory.rollups import rebuild_rollups


def main() -> None:
    db = SessionLocal()
    try:
        if "--rederive" in sys.argv:
            n = 0
            for (rid,) in db.query(AIVisibilityQuery.id).order_by(AIVisibilityQuery.id).all():
                rederive_response(db, rid)
                n += 1
            print(f"re-derived {n} response(s)")
        else:
            out = backfill_observations(db)
            print(f"derived {out['responses_processed']} of {out['responses_total']} missing response(s)")
        roll = rebuild_rollups(db)
        print(f"rollups rebuilt: {roll['keys']} property-day key(s), {roll['rows_written']} row(s)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
