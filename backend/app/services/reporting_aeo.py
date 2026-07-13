"""AEO Readiness report (Phase 16E).

Answer-Engine-Optimization readiness for a property's ingested website content:
an explainable score built from deterministic components, a question-by-page
coverage heatmap, deterministic citation-readiness signals, and an honest
structured-data empty state.

Design rules held here:
- The score is a transparent weighted average of deterministic components. Each
  component publishes its weight, its rule, its raw value, its supporting
  evidence and source pages, and a plain explanation. There is no opaque
  model-generated number.
- A component with no signal (freshness with no dates, structured data not yet
  ingested) is EXCLUDED from the score and reported as excluded, never scored
  as zero.
- Cell classifications in the heatmap come from deterministic term rules, not
  vector similarity. (Vector retrieval may surface candidate answers elsewhere;
  it never decides a cell here.)
- Citation readiness never promises a citation: the disclaimer is fixed copy.
- Structured data is not fabricated. Until an ingest path exists, the section
  reports the not-configured state behind a feature flag.
"""

from datetime import date

from sqlalchemy.orm import Session

from app.connectors.development import DevelopmentDataProvider
from app.models import CANONICAL_PAGES, Property
from app.services.content_intelligence.analyzer import _freshness, _question_coverage
from app.services.content_intelligence.matching import matched_terms, renter_questions
from app.services.property_types import label as property_type_label
from app.services.reporting import DataState

# Structured-data ingestion does not exist yet. The contract and UI are built;
# results are gated off until an ingest path lands, so nothing is fabricated.
STRUCTURED_DATA_ENABLED = False

CITATION_DISCLAIMER = (
    "Citation readiness does not guarantee that an AI platform will cite the page."
)

# A page body shorter than this reads as thin/boilerplate for crawlability.
MIN_CRAWLABLE_CHARS = 200

# Component weights. They sum to 1.0 across the components that can be scored;
# excluded components are dropped and the remaining weights are renormalized.
COMPONENT_WEIGHTS = {
    "question_coverage": 0.30,
    "answer_completeness": 0.20,
    "specificity": 0.15,
    "local_relevance": 0.10,
    "discoverability": 0.10,
    "freshness": 0.05,
    "citation_readiness": 0.10,
}

CELL_FULLY = "fully_answered"
CELL_PARTIALLY = "partially_answered"
CELL_MENTIONED = "mentioned_only"
CELL_MISSING = "missing"
CELL_STALE = "stale"


def _grade(value: float) -> str:
    if value >= 85:
        return "A"
    if value >= 70:
        return "B"
    if value >= 55:
        return "C"
    if value >= 40:
        return "D"
    return "F"


def _component(key, label, raw, rule, explanation, evidence=None, pages=None,
               excluded=False, excluded_reason=None):
    return {
        "key": key,
        "label": label,
        "weight": COMPONENT_WEIGHTS[key],
        "raw_value": None if excluded else round(raw, 1),
        "rule": rule,
        "explanation": explanation,
        "evidence": evidence or [],
        "source_pages": sorted(set(pages or [])),
        "excluded": excluded,
        "excluded_reason": excluded_reason,
    }


# --- heatmap -----------------------------------------------------------------


def _heatmap(prop, records, property_type, stale_pages):
    """Per (question, page) coverage, deterministic term matching only.

    fully_answered   = concept AND detail terms present on the page
    partially_answered = concept present, no detail on the page
    mentioned_only   = a detail term present but no concept (a weak mention)
    missing          = neither present (rendered as a blank cell)
    A page flagged stale by freshness overlays the 'stale' marker.
    """
    questions = renter_questions(property_type)
    pages = sorted({r.page for r in records})
    by_page = {r.page: r for r in records}
    rows = []
    for q in questions:
        cells = []
        for page in pages:
            rec = by_page[page]
            concept = matched_terms(rec.body, q["concept_terms"])
            detail = matched_terms(rec.body, q["detail_terms"])
            if concept and detail:
                state = CELL_FULLY
            elif concept:
                state = CELL_PARTIALLY
            elif detail:
                state = CELL_MENTIONED
            else:
                state = CELL_MISSING
            cells.append({
                "page": page,
                "state": state,
                "stale": page in stale_pages and state != CELL_MISSING,
                "matched_terms": sorted(set(concept) | set(detail)),
            })
        rows.append({
            "id": q["id"],
            "question": q["question"],
            "category": q["category"],
            "importance": q["importance"],
            "cells": cells,
        })
    return {"pages": pages, "rows": rows}


# --- score components --------------------------------------------------------


def _coverage_component(coverage):
    s = coverage["summary"]
    total = s["total"] or 1
    # answered = 1.0, partial = 0.5, missing = 0.
    raw = (s["answered"] + 0.5 * s["partial"]) / total * 100
    return _component(
        "question_coverage", "Question coverage", raw,
        "answered questions count full; partial count half.",
        f"{s['answered']} answered, {s['partial']} partial, {s['missing']} missing "
        f"of {s['total']} important questions.",
        evidence=[f"{s['answered']}/{s['total']} answered"],
    )


def _completeness_component(coverage):
    covered = [q for q in coverage["questions"] if q["status"] in ("answered", "partial")]
    if not covered:
        return _component(
            "answer_completeness", "Answer completeness", 0,
            "share of covered questions that are fully answered, not just partial.",
            "No questions are covered yet, so completeness cannot be assessed.",
            excluded=True, excluded_reason="No covered questions.",
        )
    answered = [q for q in covered if q["status"] == "answered"]
    raw = len(answered) / len(covered) * 100
    return _component(
        "answer_completeness", "Answer completeness", raw,
        "share of covered questions that are fully answered, not just partial.",
        f"{len(answered)} of {len(covered)} covered questions are fully answered.",
        pages=[c["page"] for q in answered for c in q["citations"]],
    )


def _specificity_component(coverage):
    answered = [q for q in coverage["questions"] if q["status"] == "answered"]
    if not answered:
        return _component(
            "specificity", "Specificity", 0,
            "average count of specific detail terms found per answered question, capped at 3.",
            "No fully answered questions to measure specificity on.",
            excluded=True, excluded_reason="No answered questions.",
        )
    # matched_terms already includes detail terms for answered questions; use a
    # capped average so a couple of specifics reads as strong, deterministically.
    per_q = [min(len(q["matched_terms"]), 6) / 6 for q in answered]
    raw = sum(per_q) / len(per_q) * 100
    return _component(
        "specificity", "Specificity", raw,
        "average specific-term density across answered questions, capped.",
        f"Answered questions carry specific terms (for example {', '.join(answered[0]['matched_terms'][:3])}).",
        pages=[c["page"] for q in answered for c in q["citations"]],
    )


def _local_relevance_component(prop, records):
    hay = " ".join(r.body for r in records).lower()
    signals = []
    for token in filter(None, [getattr(prop, "city", None), getattr(prop, "state", None)]):
        if token.lower() in hay:
            signals.append(token)
    # Two local anchors (city + state) is full marks; one is half.
    possible = len([t for t in [getattr(prop, "city", None), getattr(prop, "state", None)] if t])
    raw = (len(signals) / possible * 100) if possible else 0
    if not possible:
        return _component(
            "local_relevance", "Local relevance", 0,
            "presence of the property's city and state in the content.",
            "No city/state on the property record to check for.",
            excluded=True, excluded_reason="No city/state configured.",
        )
    return _component(
        "local_relevance", "Local relevance", raw,
        "presence of the property's city and state in the content.",
        f"Found {len(signals)} of {possible} local anchors ({', '.join(signals) or 'none'}).",
        evidence=signals,
    )


def _discoverability_component(records):
    present = {r.page for r in records}
    have = [p for p in CANONICAL_PAGES if p in present]
    raw = len(have) / len(CANONICAL_PAGES) * 100
    return _component(
        "discoverability", "Page discoverability", raw,
        "share of the canonical page set that has ingested content.",
        f"{len(have)} of {len(CANONICAL_PAGES)} canonical pages present.",
        pages=have,
    )


def _freshness_component(freshness):
    if not freshness["determinable"]:
        return _component(
            "freshness", "Freshness", 0,
            "current content scores full; stale content is penalized.",
            freshness["explanation"],
            excluded=True, excluded_reason="No update dates or dated content.",
        )
    raw = 100.0 if freshness["status"] == "current" else 40.0
    return _component(
        "freshness", "Freshness", raw,
        "current content scores full; stale content is penalized.",
        freshness["explanation"],
        pages=[f["page"] for f in freshness["findings"]],
    )


def _citation_readiness_component(prop, records, coverage):
    """Deterministic page-level citation-readiness signals, averaged."""
    signals_per_page = []
    detail = []
    answered_pages = {
        c["page"] for q in coverage["questions"] if q["status"] == "answered"
        for c in q["citations"]
    }
    name = (prop.name or "").strip().lower()
    for rec in records:
        hay = f"{rec.title or ''} {rec.body or ''}".lower()
        checks = {
            "clear_heading": bool(rec.title and rec.title.strip()),
            "specific_answer_present": rec.page in answered_pages,
            "named_property": bool(name) and name in hay,
            "updated_date": rec.updated_at is not None,
            "crawlable_text": len((rec.body or "").strip()) >= MIN_CRAWLABLE_CHARS,
        }
        score = sum(checks.values()) / len(checks) * 100
        signals_per_page.append(score)
        detail.append({"page": rec.page, "signals": checks})
    raw = sum(signals_per_page) / len(signals_per_page) if signals_per_page else 0
    return _component(
        "citation_readiness", "Citation readiness", raw,
        "average of per-page signals: clear heading, specific answer, named "
        "property, updated date, crawlable text.",
        CITATION_DISCLAIMER,
        pages=[d["page"] for d in detail],
    ), detail


# --- structured data (contract + empty state, feature-flagged) ---------------


def _structured_data():
    if not STRUCTURED_DATA_ENABLED:
        return {
            "state": DataState.NOT_CONFIGURED.value,
            "enabled": False,
            "message": (
                "Structured-data analysis is not ingested yet. When enabled it "
                "will report detected schema types, valid and invalid items, "
                "entity consistency, and pages missing relevant schema. No "
                "results are shown until real validation data exists."
            ),
            "schema_types": [],
            "valid_items": None,
            "invalid_items": None,
        }
    return {"state": DataState.COMPLETE.value, "enabled": True, "schema_types": []}


# --- report ------------------------------------------------------------------


def build_aeo_report(
    db: Session, property_id: int | None, today: date | None = None,
    content_provider=None,
) -> dict:
    today = today or date.today()
    if property_id is None:
        return {
            "scope_required": True,
            "message": "Select a single property to view its AEO Readiness report.",
        }
    prop = db.get(Property, property_id)
    if prop is None:
        raise ValueError("Property not found.")
    property_type = getattr(prop, "property_type", None) or "multifamily_apartment"
    provider = content_provider or DevelopmentDataProvider()
    records = provider.get_content(db, property_id)

    base = {
        "scope_required": False,
        "property_id": property_id,
        "property_name": prop.name,
        "property_type_label": property_type_label(property_type),
        "generated_on": today.isoformat(),
        "citation_disclaimer": CITATION_DISCLAIMER,
    }

    if not records:
        return {
            **base,
            "has_content": False,
            "message": (
                "No website content has been ingested for this property. Add "
                "content to compute AEO readiness."
            ),
            "structured_data": _structured_data(),
        }

    coverage = _question_coverage(prop, records, property_type)
    freshness = _freshness(prop, records, today)
    stale_pages = {f["page"] for f in freshness["findings"] if f["issue"] == "stale page"}

    citation_component, citation_detail = _citation_readiness_component(prop, records, coverage)
    components = [
        _coverage_component(coverage),
        _completeness_component(coverage),
        _specificity_component(coverage),
        _local_relevance_component(prop, records),
        _discoverability_component(records),
        _freshness_component(freshness),
        citation_component,
    ]

    scored = [c for c in components if not c["excluded"]]
    total_weight = sum(c["weight"] for c in scored)
    value = (
        round(sum(c["raw_value"] * c["weight"] for c in scored) / total_weight)
        if total_weight
        else None
    )

    return {
        **base,
        "has_content": True,
        "score": {
            "value": value,
            "grade": _grade(value) if value is not None else None,
            "components": components,
            "excluded_components": [c["key"] for c in components if c["excluded"]],
            "note": (
                "Weighted average of the deterministic components below. Excluded "
                "components carry no signal and are left out, not scored as zero."
            ),
        },
        "question_coverage_summary": coverage["summary"],
        "heatmap": _heatmap(prop, records, property_type, stale_pages),
        "citation_readiness": {
            "value": citation_component["raw_value"],
            "disclaimer": CITATION_DISCLAIMER,
            "pages": citation_detail,
        },
        "structured_data": _structured_data(),
    }
