"""Deterministic Competitor Intelligence summary indexed as a
`competitor_intelligence` RAG chunk, so Nora answers "who shows up more than us
in ChatGPT" through the existing retrieval path. Directional and sample-size
aware, never a precise market share; states insufficient data honestly."""

from sqlalchemy.orm import Session

from app.services.competitor_intelligence.analyzer import analyze_share_of_voice
from app.services.ai_visibility.reference import MIN_QUERIES_FOR_VISIBILITY


def competitor_intelligence_summary_text(db: Session, property_id: int) -> str | None:
    analysis = analyze_share_of_voice(db, property_id)
    # Only produce a chunk when there is something real to say: competitors are
    # tracked AND some AI Visibility data exists.
    if not analysis.get("has_competitors") or not analysis.get("has_ai_data"):
        return None

    sov = analysis["share_of_voice"]
    name = analysis["property_name"]
    n = sov["queries"]
    lines = [
        f"Competitor share of voice for {name} across {n} AI "
        f"quer{'y' if n == 1 else 'ies'} ({analysis['competitor_count']} "
        f"competitor(s) tracked, operator-named).",
    ]
    if not sov["sufficient"]:
        lines.append(
            f"Insufficient queries to determine share of voice (only {n} run; at "
            f"least {MIN_QUERIES_FOR_VISIBILITY} recommended). Treat the counts "
            "below as anecdotal, not a measurement."
        )
    for e in sov["entities"]:
        share = (
            f", {round(e['share'] * 100)}% share" if e.get("share") is not None else ""
        )
        who = "the property" if e["is_property"] else "competitor"
        lines.append(
            f"{e['name']} ({who}): mentioned in {e['mentions']} of {n} responses{share}."
        )

    actionable = [
        r for r in analysis["recommendations"]
        if r["state"] in ("Actionable", "Requires confirmation")
    ]
    if actionable:
        lines.append(
            "Recommendations: "
            + "; ".join(f"{r['title']} [{r['state']}]" for r in actionable[:3])
        )

    lines.append(analysis["directional_caveat"])
    return "\n".join(lines)
