"""Question-set import (DCHP seed format).

Ingests an operator-authored question-set JSON (the dchp-beacon-queries
shape) into Beacon's existing structures - nothing is guessed:

- questions -> standing AIVisibilityPrompt rows (upserted by prompt text, so
  re-importing a revised file updates metadata instead of duplicating).
- named organization competitors -> Competitor rows (operator-asserted, with
  domains, so the GEO source landscape classifies their citations).
- run_config/budget/alert_rules are advisory for the operator; the parts
  Beacon enforces (web search, output caps, cadence) live in settings and
  the scheduler. must_contain is evaluated deterministically at read time,
  never by an LLM judge - matching the file's own llm_judge: false.
"""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import AIVisibilityPrompt, Competitor, Property

# Domains from a question set's known_competitors list that are ORGANIZATION
# competitors (contested for the same answers) rather than listing sites or
# federal references; only these become Competitor rows. Everything else is
# already classified by the GEO source classifier (government/directory).
ORG_COMPETITORS = {
    "douglasco.gov": ("Douglas County Government", ["Douglas County", "douglasco.gov"]),
    "chfainfo.com": ("CHFA", ["Colorado Housing and Finance Authority", "CHFA"]),
    "coloradohousingconnects.org": (
        "Colorado Housing Connects", ["Colorado Housing Connects"],
    ),
}

VALID_CADENCES = {"weekly", "monthly"}


def import_question_set(db: Session, property_id: int, payload: dict) -> dict:
    prop = db.get(Property, property_id)
    if prop is None:
        raise ValueError("Property not found.")
    questions = payload.get("questions") or []
    if not questions:
        raise ValueError("Question set contains no questions.")

    engine = (payload.get("run_config") or {}).get("engine", "chatgpt")
    created = updated = 0
    for q in questions:
        text = (q.get("question") or "").strip()
        if not text:
            continue
        cadence = q.get("cadence") if q.get("cadence") in VALID_CADENCES else "weekly"
        fields = {
            "platform": engine,
            "active": True,
            "cadence": cadence,
            "runs_per_cycle": int(q.get("runs") or 1),
            "intent": (q.get("intent") or None),
            "owning_url": (q.get("owning_url") or None),
            "volatile": bool(q.get("volatile")),
            "must_contain": q.get("must_contain") or None,
            "notes": (q.get("notes") or None),
        }
        row = (
            db.query(AIVisibilityPrompt)
            .filter(
                AIVisibilityPrompt.property_id == property_id,
                AIVisibilityPrompt.prompt_text == text,
            )
            .first()
        )
        if row is None:
            db.add(AIVisibilityPrompt(
                property_id=property_id, prompt_text=text, **fields
            ))
            created += 1
        else:
            for k, v in fields.items():
                setattr(row, k, v)
            updated += 1

    competitors_created = []
    known = (payload.get("scoring") or {}).get("known_competitors") or []
    for domain in known:
        info = ORG_COMPETITORS.get(domain)
        if not info:
            continue  # listing/government sites stay with the source classifier
        name, aliases = info
        exists = (
            db.query(Competitor)
            .filter(Competitor.property_id == property_id, Competitor.name == name)
            .first()
        )
        if exists is None:
            db.add(Competitor(
                property_id=property_id, name=name, aliases=aliases, domain=domain,
            ))
            competitors_created.append(name)

    db.commit()
    return {
        "prompts_created": created,
        "prompts_updated": updated,
        "competitors_created": competitors_created,
        "imported_at": datetime.now(timezone.utc).isoformat(),
        "note": (
            "Cadence and runs drive the scheduler when the AI Visibility "
            "autorun flag is on; web-search enforcement comes from settings. "
            "must_contain is checked deterministically at read time."
        ),
    }


def evaluate_must_contain(response_text: str, must_contain: list | None) -> list[dict]:
    """Deterministic containment check (case-insensitive) of each required
    component against a stored response. Never an LLM judge."""
    if not must_contain:
        return []
    hay = (response_text or "").lower()
    return [
        {"component": c, "present": c.lower() in hay}
        for c in must_contain
        if isinstance(c, str) and c.strip()
    ]
