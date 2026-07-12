"""Restamp AI referral classification on all ingested GA4 rows.

Run after updating reference_data/ai_referrer_domains.json so rows ingested
under an older reference list pick up the new platforms/domains:

    .venv/bin/python -m app.cli.backfill_ai
"""

from sqlalchemy.orm import Session

from app.constants import AI_TRAFFIC_DISCLOSURE
from app.db import SessionLocal
from app.models import GA4SessionsDaily
from app.services.classifier import get_classifier


def backfill(db: Session) -> dict:
    classifier = get_classifier()
    scanned = changed = 0
    platform_counts: dict[str, int] = {}

    for row in db.query(GA4SessionsDaily).yield_per(500):
        scanned += 1
        platform = classifier.classify(row.session_source)
        is_ai = platform is not None
        if row.is_ai_referral != is_ai or row.ai_platform != platform:
            row.is_ai_referral = is_ai
            row.ai_platform = platform
            changed += 1
        if platform:
            platform_counts[platform] = platform_counts.get(platform, 0) + 1

    db.commit()
    return {
        "reference_version": classifier.version,
        "rows_scanned": scanned,
        "rows_changed": changed,
        "ai_rows_total": sum(platform_counts.values()),
        "platform_counts": platform_counts,
    }


def main() -> None:
    db = SessionLocal()
    try:
        summary = backfill(db)
    finally:
        db.close()

    print(f"Reference list version: {summary['reference_version']}")
    print(f"Rows scanned: {summary['rows_scanned']}")
    print(f"Rows restamped: {summary['rows_changed']}")
    print(f"AI referral rows: {summary['ai_rows_total']}")
    for key, count in sorted(summary["platform_counts"].items()):
        print(f"  {key}: {count}")
    if summary["ai_rows_total"]:
        print(AI_TRAFFIC_DISCLOSURE)


if __name__ == "__main__":
    main()
