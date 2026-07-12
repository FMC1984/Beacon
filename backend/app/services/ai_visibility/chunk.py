"""Deterministic AI Visibility summary indexed as an `ai_visibility` RAG chunk,
so Nora answers "how do we show up in ChatGPT" the same retrieval way it answers
everything else. Built from the Phase 12 analyzer, but kept sample-size-aware and
directional: never a precise visibility percentage, always "based on N queries",
and it states insufficient-data honestly (mirrors Phase 11 trend gating)."""

from sqlalchemy.orm import Session

from app.services.ai_visibility.analyzer import analyze_ai_visibility
from app.services.ai_visibility.reference import MIN_QUERIES_FOR_VISIBILITY


def ai_visibility_summary_text(db: Session, property_id: int) -> str | None:
    analysis = analyze_ai_visibility(db, property_id)
    if not analysis.get("has_queries"):
        return None

    name = analysis["property_name"]
    dr = analysis["date_range"]
    n = analysis["sample"]["total_queries"]
    lines = [
        f"AI Visibility for {name}. Based on {n} quer{'y' if n == 1 else 'ies'} "
        f"run between {dr['start']} and {dr['end']}.",
    ]
    if not analysis["sample"]["sufficient"]:
        lines.append(
            f"Insufficient queries to determine visibility (only {n} run; at "
            f"least {MIN_QUERIES_FOR_VISIBILITY} recommended). Treat the following "
            "as anecdotal, not a visibility measurement."
        )

    for p in analysis["by_platform"]:
        srcs = ", ".join(s["domain"] for s in p["top_sources"][:6]) or "none cited"
        lines.append(
            f"{p['label']}: brand mentioned in {p['mentions']} of {p['queries']} "
            f"quer{'y' if p['queries'] == 1 else 'ies'} (detected from response "
            f"text, negation-unaware). Sources cited: {srcs}."
        )

    score = analysis["score"]
    if score:
        lines.append(
            f"AI Visibility score: {score['value']}/100 ({score['grade']}), "
            "directional only."
        )

    own = analysis["own_site"]
    if own.get("status") == "not_cited":
        lines.append(f"The property's own site ({own['domain']}) was not cited in "
                     "any sampled response.")
    elif own.get("status") == "cited":
        lines.append(f"The property's own site ({own['domain']}) was cited in "
                     f"{own['cited_in_queries']} response(s).")

    fc = analysis["fact_checks"]
    if fc["contradictions"]:
        fields = ", ".join(sorted({c["field"] for c in fc["contradictions"]}))
        lines.append(
            f"Fact-check hook: {len(fc['contradictions'])} response(s) contradicted "
            f"Beacon's known property data ({fields}). Verify which is correct."
        )
    if fc["cannot_verify_count"]:
        lines.append(
            f"Fact-check hook: property type could not be verified for "
            f"{fc['cannot_verify_count']} response(s) (Property Context not "
            "configured; reported as 'cannot verify', not assumed correct)."
        )

    actionable = [
        r for r in analysis["recommendations"]
        if r["state"] in ("Actionable", "Requires confirmation")
    ]
    if actionable:
        lines.append(
            "Recommendations: "
            + "; ".join(f"{r['title']} [{r['state']}]" for r in actionable[:4])
        )

    lines.append(analysis["directional_caveat"])
    return "\n".join(lines)
