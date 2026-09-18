"""Action lifecycle with automatic retest (competitive roadmap 7).

A person tracks an action (from the Opportunity Engine, a truth conflict or
an area of concern). It moves open -> in progress -> implemented. On
implementation Beacon records a baseline from the evidence the action came
from, waits a stated number of days, then retests that same evidence:

  listing_gap   re-reads the cited page: does it name the property now?
                resolved | persists | inconclusive (page unreadable)
  fact          re-checks the AI answers since implementation that state
                this fact: any conflicts left?
                resolved | persists | inconclusive (too few statements)
  content_gap / topic
                AI Visibility on that question or topic, 30 days before vs
                since implementation, both sample-gated:
                improved | no_change | declined | inconclusive
                Reported as association: many things move AI answers.
  general       no automatic check exists; a person closes it (done).

An inconclusive retest is rescheduled a week later, up to MAX_RETESTS, then
recorded as inconclusive. Beacon never marks an action resolved without the
evidence showing it, and never predicts a lift.
"""

import hashlib
import re
from collections import Counter
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.models import (
    AICitedPage,
    AIContentGap,
    AIPromptCluster,
    AIPropertyObservation,
    AIVisibilityQuery,
    ContentChange,
    Property,
)
from app.models.ai_actions import (
    KIND_CONTENT,
    KIND_FACT,
    KIND_GENERAL,
    KIND_LISTING,
    KIND_TOPIC,
    KINDS,
    OUTCOME_DECLINED,
    OUTCOME_IMPROVED,
    OUTCOME_INCONCLUSIVE,
    OUTCOME_NO_CHANGE,
    OUTCOME_PERSISTS,
    OUTCOME_RESOLVED,
    STATUS_DISMISSED,
    STATUS_DONE,
    STATUS_IMPLEMENTED,
    STATUS_IN_PROGRESS,
    STATUS_OPEN,
    STATUS_RETESTED,
    AIAction,
)
from app.models.ai_cited_pages import CHECK_OK
from app.models.ai_intelligence import CLAIM_CONFIRMED, CLAIM_CONFLICT, CLAIM_LIKELY_ACCURATE
from app.models.content_change import ChangeType
from app.services.ai_visibility.mentions import resolve_property_terms
from app.services.ai_visibility.parsing import find_mention
from app.services.ai_visibility.reference import MIN_QUERIES_FOR_VISIBILITY
from app.services.jobs.queue import utcnow
from app.services.observatory import LABEL_MEASURED, utc_today
from app.services.observatory.claims import _content_topics, extract_claims
from app.services.observatory.observability import log_event
from app.services.observatory.tenancy import property_org_id
from app.services.property_context import get_property_context
from app.services.reporting import pct_point_change, rate

# Days to wait after implementation before the first retest, per kind.
RETEST_AFTER_DAYS = {KIND_LISTING: 3, KIND_FACT: 21, KIND_CONTENT: 21, KIND_TOPIC: 21}
RETRY_DAYS = 7
MAX_RETESTS = 4
BASELINE_DAYS = 30
MIN_FACT_STATEMENTS = 3
# Topic outcomes: a stated threshold, not a significance test.
CHANGE_POINTS = 0.05


def action_key(source: str | None, title: str) -> str:
    return hashlib.sha256(f"{source or ''}|{title.strip().lower()}".encode()).hexdigest()[:40]


def _kind_from_citations(db: Session, property_id: int, citations: list[dict] | None) -> tuple[str, dict]:
    """Recognize the Observatory action types from their source_ref."""
    for c in citations or []:
        ref = str(c.get("source_ref") or "")
        m = re.search(r"listing_gap=(\S+)", ref)
        if m:
            return KIND_LISTING, {"normalized_url": m.group(1).rstrip(","), "url": c.get("page")}
        m = re.search(r"gap=(\d+)", ref)
        if m:
            gap = db.get(AIContentGap, int(m.group(1)))
            if gap and gap.property_id == property_id:
                return KIND_CONTENT, {"gap_id": gap.id, "cluster_id": gap.cluster_id, "topic_key": gap.topic_key,
                                      "question": gap.question, "page": gap.target_page}
    return KIND_GENERAL, {}


def track_action(db: Session, property_id: int, *, title: str, source: str | None = None, source_label: str | None = None,
                 reason: str | None = None, citations: list[dict] | None = None, kind: str | None = None,
                 target: dict | None = None) -> tuple[AIAction, bool]:
    """Create the tracked action, or return the existing one (idempotent by
    source + title per property)."""
    prop = db.get(Property, property_id)
    if prop is None:
        raise ValueError("Property not found.")
    if not (title or "").strip():
        raise ValueError("An action needs a title.")
    if kind is not None and kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}.")
    key = action_key(source, title)
    row = db.query(AIAction).filter_by(property_id=property_id, action_key=key).one_or_none()
    if row is not None:
        return row, False
    if kind is None:
        kind, derived = _kind_from_citations(db, property_id, citations)
        target = {**derived, **(target or {})}
    if kind == KIND_TOPIC and not (target or {}).get("topic_key"):
        raise ValueError("A topic action needs target.topic_key.")
    if kind == KIND_FACT and not (target or {}).get("fact_key"):
        raise ValueError("A fact action needs target.fact_key.")
    row = AIAction(
        organization_id=property_org_id(db, property_id), property_id=property_id, action_key=key, kind=kind,
        target=target or {}, source=source, source_label=source_label, title=title.strip()[:300], reason=reason,
        evidence=citations or [], status=STATUS_OPEN, updated_at=utcnow(),
    )
    db.add(row)
    db.commit()
    return row, True


# --- measurements ---------------------------------------------------------------


def _bounds(lo: date, hi: date) -> tuple[datetime, datetime]:
    return datetime.combine(lo, datetime.min.time()), datetime.combine(hi, datetime.min.time())


def _visibility(db: Session, property_id: int, lo: date, hi: date, *, cluster_id=None, topic_key=None) -> dict:
    """AI Visibility on one question (cluster) or topic over [lo, hi)."""
    s, e = _bounds(lo, hi)
    q = (db.query(AIPropertyObservation.mentioned)
         .filter(AIPropertyObservation.property_id == property_id, AIPropertyObservation.eligible.is_(True),
                 AIPropertyObservation.observed_at >= s, AIPropertyObservation.observed_at < e))
    if cluster_id is not None:
        q = q.filter(AIPropertyObservation.cluster_id == cluster_id)
    elif topic_key is not None:
        q = q.join(AIPromptCluster, AIPromptCluster.id == AIPropertyObservation.cluster_id).filter(
            AIPromptCluster.topic_key == topic_key)
    rows = [m for (m,) in q.all()]
    r = rate(sum(1 for m in rows if m), len(rows), MIN_QUERIES_FOR_VISIBILITY)
    return {**r, "window": {"start": lo.isoformat(), "end": (hi - timedelta(days=1)).isoformat()}}


def _fact_statements(db: Session, prop: Property, fact_key: str, lo: date, hi: date) -> dict:
    """What AI answers in [lo, hi) said about one fact, re-checked with the
    same claim extractors the Accuracy tab uses."""
    from app.services.observatory.truth import _fact_key

    s, e = _bounds(lo, hi)
    rids = [rid for (rid,) in db.query(AIPropertyObservation.response_id).filter(
        AIPropertyObservation.property_id == prop.id, AIPropertyObservation.eligible.is_(True),
        AIPropertyObservation.mentioned.is_(True),
        AIPropertyObservation.observed_at >= s, AIPropertyObservation.observed_at < e).distinct()]
    ctx = get_property_context(db, prop.id)
    topics = _content_topics(db, prop.id)
    counts: Counter = Counter()
    examples: list[str] = []
    for (text,) in db.query(AIVisibilityQuery.raw_response_text).filter(AIVisibilityQuery.id.in_(rids or [-1])).all():
        for d in extract_claims(text or "", prop, ctx, topics):
            if _fact_key(d.claim_type, d.topic) != fact_key:
                continue
            if d.status == CLAIM_CONFLICT:
                counts["conflict"] += 1
                if len(examples) < 3:
                    examples.append(d.text[:200])
            elif d.status in (CLAIM_CONFIRMED, CLAIM_LIKELY_ACCURATE):
                counts["agree"] += 1
            else:
                counts["other"] += 1
    return {"answers_checked": len(rids), "statements": sum(counts.values()), "conflict": counts["conflict"],
            "agree": counts["agree"], "other": counts["other"], "conflict_examples": examples,
            "window": {"start": lo.isoformat(), "end": (hi - timedelta(days=1)).isoformat()}}


def _listing_state(db: Session, prop: Property, normalized_url: str) -> dict:
    page = db.query(AICitedPage).filter_by(normalized_url=normalized_url).one_or_none()
    if page is None:
        return {"state": "unchecked"}
    if page.status != CHECK_OK:
        return {"state": "unreachable", "detail": page.error or page.status, "checked_at": page.fetched_at.isoformat()}
    hit = find_mention(page.body or "", resolve_property_terms(prop))
    return {"state": "mentioned" if hit else "not_mentioned", "checked_at": page.fetched_at.isoformat(),
            "detail": f"names it as \"{hit['term']}\"" if hit else None}


def measure(db: Session, action: AIAction, implemented: date, today: date) -> dict:
    """Baseline (before implementation) and current (since) for the action's evidence."""
    prop = db.get(Property, action.property_id)
    t = action.target or {}
    before_lo = implemented - timedelta(days=BASELINE_DAYS)
    after_hi = today + timedelta(days=1)
    if action.kind == KIND_LISTING:
        return {"current": _listing_state(db, prop, t.get("normalized_url", ""))}
    if action.kind == KIND_FACT:
        return {"before": _fact_statements(db, prop, t["fact_key"], before_lo, implemented),
                "after": _fact_statements(db, prop, t["fact_key"], implemented, after_hi)}
    if action.kind in (KIND_CONTENT, KIND_TOPIC):
        scope = {"cluster_id": t.get("cluster_id")} if action.kind == KIND_CONTENT and t.get("cluster_id") else {"topic_key": t.get("topic_key")}
        return {"before": _visibility(db, action.property_id, before_lo, implemented, **scope),
                "after": _visibility(db, action.property_id, implemented, after_hi, **scope), "scope": scope}
    return {}


def _judge(action: AIAction, m: dict) -> tuple[str, str]:
    """(outcome, plain sentence) from a measurement, by a stated rule."""
    if action.kind == KIND_LISTING:
        st = m["current"]["state"]
        if st == "mentioned":
            return OUTCOME_RESOLVED, "The cited page now names the property."
        if st == "not_mentioned":
            return OUTCOME_PERSISTS, "Beacon re-read the cited page and it still does not name the property."
        return OUTCOME_INCONCLUSIVE, "Beacon could not read the page, so it cannot tell whether it was fixed."
    if action.kind == KIND_FACT:
        a = m["after"]
        if a["statements"] < MIN_FACT_STATEMENTS:
            return OUTCOME_INCONCLUSIVE, (f"Only {a['statements']} AI statement(s) about this fact since the fix "
                                          f"(needs {MIN_FACT_STATEMENTS}).")
        if a["conflict"] == 0:
            return OUTCOME_RESOLVED, f"None of the {a['statements']} AI statements about this fact since the fix conflict with the record."
        return OUTCOME_PERSISTS, f"{a['conflict']} of {a['statements']} AI statements since the fix still conflict with the record."
    if action.kind in (KIND_CONTENT, KIND_TOPIC):
        b, a = m["before"], m["after"]
        if b["value"] is None or a["value"] is None:
            return OUTCOME_INCONCLUSIVE, (f"Not enough monitored answers to compare ({b['denominator']} before, "
                                          f"{a['denominator']} since; needs {MIN_QUERIES_FOR_VISIBILITY} in each).")
        pts = pct_point_change(a["value"], b["value"]) or 0.0
        p = round(pts * 100)
        line = (f"AI Visibility here went from {round(b['value'] * 100)}% ({b['numerator']} of {b['denominator']}) to "
                f"{round(a['value'] * 100)}% ({a['numerator']} of {a['denominator']}), {'+' if p >= 0 else ''}{p} points. "
                "This is association: other changes can move AI answers too.")
        if pts >= CHANGE_POINTS:
            return OUTCOME_IMPROVED, line
        if pts <= -CHANGE_POINTS:
            return OUTCOME_DECLINED, line
        return OUTCOME_NO_CHANGE, line
    return OUTCOME_INCONCLUSIVE, "No automatic check exists for this kind of action."


# --- lifecycle ---------------------------------------------------------------------


def update_action(db: Session, action_id: int, *, status: str | None = None, owner: str | None = None,
                  notes: str | None = None, implemented_on: date | None = None, page_url: str | None = None,
                  change_type: str | None = None, today: date | None = None) -> AIAction:
    row = db.get(AIAction, action_id)
    if row is None:
        raise LookupError("Action not found.")
    today = today or utc_today()
    now = utcnow()
    if owner is not None:
        row.owner = owner.strip()[:120] or None
    if notes is not None:
        row.notes = notes.strip() or None
    if status is not None:
        allowed = {
            STATUS_OPEN: {STATUS_IN_PROGRESS, STATUS_IMPLEMENTED, STATUS_DISMISSED, STATUS_DONE},
            STATUS_IN_PROGRESS: {STATUS_OPEN, STATUS_IMPLEMENTED, STATUS_DISMISSED, STATUS_DONE},
            STATUS_IMPLEMENTED: {STATUS_IN_PROGRESS},
            STATUS_RETESTED: {STATUS_IN_PROGRESS},
            STATUS_DONE: {STATUS_IN_PROGRESS},
            STATUS_DISMISSED: {STATUS_OPEN},
        }[row.status]
        if status not in allowed:
            raise ValueError(f"Cannot move an action from {row.status} to {status}.")
        if status == STATUS_DONE and row.kind != KIND_GENERAL:
            raise ValueError("This action is retested automatically; mark it implemented instead.")
        if status == STATUS_IMPLEMENTED and row.kind == KIND_GENERAL:
            status = STATUS_DONE
        if status == STATUS_IN_PROGRESS and row.started_at is None:
            row.started_at = now
        if status in (STATUS_IN_PROGRESS, STATUS_OPEN):
            row.outcome, row.retest_after, row.retest_count = None, None, 0
        if status == STATUS_IMPLEMENTED:
            day = implemented_on or today
            if day > today:
                raise ValueError("The implementation date cannot be in the future.")
            row.implemented_on = day
            row.retest_after = day + timedelta(days=RETEST_AFTER_DAYS.get(row.kind, 21))
            row.retest_count, row.outcome, row.result = 0, None, None
            row.baseline = measure(db, row, day, day)
            if page_url and row.kind in (KIND_CONTENT, KIND_TOPIC, KIND_FACT):
                cc = ContentChange(
                    property_id=row.property_id, company_id=db.get(Property, row.property_id).company_id,
                    page_url=page_url.strip()[:1000], change_title=row.title[:300],
                    change_type=ChangeType(change_type) if change_type else ChangeType.EXPANDED_CONTENT,
                    date_implemented=day, notes=row.notes, related_opportunity=row.title[:500], created_by="Beacon action",
                )
                db.add(cc)
                db.flush()
                row.content_change_id = cc.id
        row.status = status
    row.updated_at = now
    db.commit()
    return row


def retest(db: Session, action: AIAction, today: date | None = None, refetch: bool = False) -> AIAction:
    """Measure again and record the outcome. `refetch` re-reads a listing page
    first (network; never for sample properties)."""
    today = today or utc_today()
    if action.status not in (STATUS_IMPLEMENTED, STATUS_RETESTED) or action.implemented_on is None:
        raise ValueError("Only an implemented action can be retested.")
    prop = db.get(Property, action.property_id)
    if refetch and action.kind == KIND_LISTING and not (prop.attributes or {}).get("sample_data"):
        from app.services.observatory.citation_pages import _store_fetch

        url = (action.target or {}).get("url") or "https://" + (action.target or {}).get("normalized_url", "")
        _store_fetch(db, url, utcnow())
        db.commit()
    m = measure(db, action, action.implemented_on, today)
    outcome, sentence = _judge(action, m)
    action.retest_count = (action.retest_count or 0) + 1
    action.retested_at = utcnow()
    action.result = {**m, "sentence": sentence, "data_label": LABEL_MEASURED, "retest": action.retest_count}
    if outcome == OUTCOME_INCONCLUSIVE and action.retest_count < MAX_RETESTS and action.kind != KIND_GENERAL:
        action.status = STATUS_IMPLEMENTED
        action.outcome = None
        action.retest_after = today + timedelta(days=RETRY_DAYS)
    else:
        action.status = STATUS_RETESTED
        action.outcome = outcome
        action.retest_after = None
    action.updated_at = utcnow()
    db.commit()
    log_event("action.retested", action_id=action.id, kind=action.kind, outcome=action.outcome)
    return action


def retest_due(db: Session, today: date | None = None) -> dict:
    today = today or utc_today()
    due = (db.query(AIAction).filter(AIAction.status == STATUS_IMPLEMENTED, AIAction.retest_after.isnot(None),
                                     AIAction.retest_after <= today).all())
    out = Counter()
    for a in due:
        retest(db, a, today=today, refetch=True)
        out[a.outcome or "rescheduled"] += 1
    return {"retested": len(due), **out}


def action_out(a: AIAction) -> dict:
    return {
        "id": a.id, "property_id": a.property_id, "kind": a.kind, "target": a.target or {}, "source": a.source,
        "source_label": a.source_label, "title": a.title, "reason": a.reason, "evidence": a.evidence or [],
        "status": a.status, "owner": a.owner, "notes": a.notes,
        "started_at": a.started_at.isoformat() if a.started_at else None,
        "implemented_on": a.implemented_on.isoformat() if a.implemented_on else None,
        "retest_after": a.retest_after.isoformat() if a.retest_after else None,
        "retest_count": a.retest_count or 0,
        "retested_at": a.retested_at.isoformat() if a.retested_at else None,
        "baseline": a.baseline, "result": a.result, "outcome": a.outcome,
        "content_change_id": a.content_change_id,
        "automatic_retest": a.kind != KIND_GENERAL,
        "retest_rule": {KIND_LISTING: "Re-reads the cited page 3 days after implementation.",
                        KIND_FACT: "Re-checks AI answers about this fact 21 days after implementation.",
                        KIND_CONTENT: "Compares AI Visibility on this question, 30 days before vs since, after 21 days.",
                        KIND_TOPIC: "Compares AI Visibility on this topic, 30 days before vs since, after 21 days.",
                        KIND_GENERAL: "No automatic check exists for this kind of action; close it when done."}[a.kind],
    }


def list_actions(db: Session, property_id: int, include_closed: bool = True) -> dict:
    q = db.query(AIAction).filter_by(property_id=property_id)
    if not include_closed:
        q = q.filter(AIAction.status.notin_([STATUS_DISMISSED, STATUS_DONE, STATUS_RETESTED]))
    rows = q.order_by(AIAction.updated_at.desc().nullslast(), AIAction.id.desc()).all()
    counts = Counter(r.status for r in rows)
    outcomes = Counter(r.outcome for r in rows if r.outcome)
    return {"property_id": property_id, "actions": [action_out(r) for r in rows], "by_status": dict(counts),
            "by_outcome": dict(outcomes),
            "note": ("Retests re-measure the evidence each action came from. Topic results are association, not causation; "
                     "Beacon never marks an action resolved without the evidence showing it.")}


def status_by_key(db: Session, property_id: int) -> dict[str, dict]:
    return {a.action_key: {"id": a.id, "status": a.status, "outcome": a.outcome}
            for a in db.query(AIAction).filter_by(property_id=property_id).all()}
