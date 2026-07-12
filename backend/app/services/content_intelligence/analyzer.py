"""The deterministic Content Intelligence engine.

analyze_property() reasons over a property's ingested website content and returns
an explainable analysis: keyword intent per page, renter-question coverage,
neighborhood coverage, content freshness, prioritized opportunities, and a
composite score whose every component is shown. No LLM is involved; all
judgments are fixed term/topic rules, so the output is reproducible.
"""

import re
from datetime import date, datetime

from sqlalchemy.orm import Session

from app.connectors.base import ContentProvider, ContentRecord
from app.connectors.development import DevelopmentDataProvider
from app.models import CANONICAL_PAGES, Property
from app.services.content_intelligence.matching import (
    content_intent,
    matched_terms,
    neighborhood_config,
    renter_questions,
)
from app.services.property_context import (
    compliance_advisory,
    get_property_context,
    marketing_guidance,
)

STALE_DAYS = 180
FRESHNESS_PENALTY = 25
IMPACT_RANK = {"High": 3, "Medium": 2, "Low": 1}
EFFORT_RANK = {"Low": 1, "Medium": 2, "High": 3}
IMPORTANCE_TO_IMPACT = {"high": "High", "medium": "Medium", "low": "Low"}
WEIGHTS = {
    "keyword_intent": 0.25,
    "question_coverage": 0.35,
    "neighborhood": 0.20,
    "freshness": 0.20,
}
_YEAR_RE = re.compile(r"\b(20\d{2})\b")
_PROMO_TERMS = (
    "special", "promotion", "limited time", "move-in special", "move in special",
    "free month", "one month free", "waived", "look and lease", "act now", "hurry",
)


def _cite(prop: Property, page: str, evidence: list[str]) -> dict:
    return {
        "property_id": prop.id,
        "property_name": prop.name,
        "page": page,
        "source_ref": f"content: property={prop.id}, page={page}",
        "evidence": evidence,
    }


def _grade(value: float) -> str:
    if value < 40:
        return "Poor"
    if value < 60:
        return "Basic"
    if value < 80:
        return "Good"
    return "Excellent"


def _keyword_intent(prop, by_page: dict[str, ContentRecord], property_type: str) -> list[dict]:
    intent = content_intent(property_type)
    threshold = intent["intent_threshold"]
    results = []
    for page in CANONICAL_PAGES:
        record = by_page.get(page)
        spec = intent["pages"].get(page)
        if record is None or spec is None:
            continue
        topics = spec["required_topics"]
        covered, missing = [], []
        for topic in topics:
            if matched_terms(record.body, topic["terms"]):
                covered.append(topic["label"])
            else:
                missing.append(topic["label"])
        ratio = len(covered) / len(topics) if topics else 0.0
        results.append(
            {
                "page": page,
                "mapped_keyword": record.mapped_keyword,
                "intent_satisfied": ratio >= threshold,
                "topic_complete": not missing,
                "covered_topics": covered,
                "missing_topics": missing,
                "coverage_ratio": round(ratio, 2),
                "explanation": (
                    f"The {page} page covers {len(covered)} of {len(topics)} "
                    f"supporting topics a complete page for its mapped keyword "
                    f"should address ({', '.join(covered) or 'none'}). "
                    + (
                        f"Missing: {', '.join(missing)}."
                        if missing
                        else "All supporting topics are present."
                    )
                    + " Judged by topic coverage, not keyword frequency."
                ),
                "citation": _cite(prop, page, covered),
            }
        )
    return results


def _question_coverage(prop, records: list[ContentRecord], property_type: str) -> dict:
    questions = renter_questions(property_type)
    results = []
    counts = {"answered": 0, "partial": 0, "missing": 0}
    for q in questions:
        concept_pages, detail_terms_found = [], []
        for rec in records:
            concept_hits = matched_terms(rec.body, q["concept_terms"])
            detail_hits = matched_terms(rec.body, q["detail_terms"])
            if concept_hits:
                concept_pages.append((rec.page, concept_hits))
            detail_terms_found.extend(detail_hits)

        if not concept_pages:
            status = "missing"
            citations = []
        elif detail_terms_found:
            status = "answered"
            citations = [
                _cite(prop, page, hits + detail_terms_found[:3])
                for page, hits in concept_pages[:2]
            ]
        else:
            status = "partial"
            citations = [_cite(prop, page, hits) for page, hits in concept_pages[:2]]

        counts[status] += 1
        results.append(
            {
                "id": q["id"],
                "question": q["question"],
                "category": q["category"],
                "importance": q["importance"],
                "status": status,
                "matched_terms": sorted(
                    {t for _, hits in concept_pages for t in hits}
                    | set(detail_terms_found)
                ),
                "citations": citations,
                "explanation": {
                    "answered": "A concept and specific details are both present.",
                    "partial": "The topic is mentioned but lacks specifics.",
                    "missing": "No content addresses this question.",
                }[status],
            }
        )
    return {
        "summary": {**counts, "total": len(questions)},
        "questions": results,
    }


def _neighborhood(prop, records: list[ContentRecord]) -> dict:
    config = neighborhood_config()
    categories = config["categories"]
    thresholds = config["rating_thresholds"]
    covered, missing, citations = [], [], []
    for cat in categories:
        hits_pages = []
        for rec in records:
            hits = matched_terms(rec.body, cat["terms"])
            if hits:
                hits_pages.append((rec.page, hits))
        if hits_pages:
            covered.append(cat["label"])
            citations.append(_cite(prop, hits_pages[0][0], hits_pages[0][1]))
        else:
            missing.append(cat["label"])

    n = len(covered)
    if n <= thresholds["poor_max"]:
        rating = "Poor"
    elif n <= thresholds["basic_max"]:
        rating = "Basic"
    elif n <= thresholds["good_max"]:
        rating = "Good"
    else:
        rating = "Excellent"

    return {
        "rating": rating,
        "covered_categories": covered,
        "missing_categories": missing,
        "covered_count": n,
        "total_categories": len(categories),
        "explanation": (
            f"The website discusses {n} of {len(categories)} neighborhood topics "
            f"({', '.join(covered) or 'none'}). "
            + (f"Not covered: {', '.join(missing)}." if missing else "Full coverage.")
        ),
        "citations": citations,
    }


def _freshness(prop, records: list[ContentRecord], today: date) -> dict:
    findings = []
    have_signal = False
    for rec in records:
        if rec.updated_at is not None:
            have_signal = True
            age = (today - rec.updated_at.date()).days
            if age > STALE_DAYS:
                findings.append(
                    {
                        "page": rec.page,
                        "issue": "stale page",
                        "evidence": f"not updated since {rec.updated_at.date().isoformat()} ({age} days)",
                    }
                )
        years = [int(y) for y in _YEAR_RE.findall(rec.body)]
        past_years = [y for y in years if y < today.year]
        promo_hits = matched_terms(rec.body, _PROMO_TERMS)
        if promo_hits:
            have_signal = True
            if past_years:
                findings.append(
                    {
                        "page": rec.page,
                        "issue": "outdated promotion",
                        "evidence": f"promotional language ({', '.join(promo_hits[:2])}) referencing {min(past_years)}",
                    }
                )

    if not have_signal:
        return {
            "determinable": False,
            "status": "unknown",
            "findings": [],
            "explanation": (
                "Freshness cannot be determined honestly: no update timestamps "
                "and no dates in the content. Not guessing."
            ),
        }
    status = "stale" if findings else "current"
    return {
        "determinable": True,
        "status": status,
        "findings": findings,
        "explanation": (
            f"Found {len(findings)} freshness issue(s)."
            if findings
            else "No outdated promotions or stale pages detected."
        ),
    }


def _opportunities(prop, by_page, intent_results, questions, neighborhood, freshness) -> list[dict]:
    opps = []

    # Missing canonical pages.
    for page in CANONICAL_PAGES:
        if page not in by_page:
            opps.append(
                {
                    "title": f"Add a {page.replace('_', ' ')} page",
                    "reason": f"No {page.replace('_', ' ')} content is ingested, so renters and search engines have nothing to find.",
                    "citations": [],
                    "impact": "Medium",
                    "effort": "Medium",
                }
            )

    # Unsatisfied keyword intent.
    for r in intent_results:
        if not r["intent_satisfied"] and r["missing_topics"]:
            opps.append(
                {
                    "title": f"Strengthen {r['page'].replace('_', ' ')} coverage of its mapped keyword",
                    "reason": f"The page covers only {int(r['coverage_ratio'] * 100)}% of the supporting topics its intent needs. Missing: {', '.join(r['missing_topics'])}.",
                    "citations": [r["citation"]],
                    "impact": "High",
                    "effort": "Medium",
                }
            )

    # Missing / partial renter questions (skip low importance to keep it focused).
    for q in questions["questions"]:
        if q["status"] == "answered" or q["importance"] == "low":
            continue
        verb = "Add" if q["status"] == "missing" else "Expand"
        opps.append(
            {
                "title": f"{verb} {q['question'].rstrip('?').lower()} content",
                "reason": q["explanation"]
                + f" This is a {q['importance']}-importance renter question.",
                "citations": q["citations"],
                "impact": IMPORTANCE_TO_IMPACT[q["importance"]],
                "effort": "Low",
            }
        )

    # Weak neighborhood.
    if neighborhood["rating"] in ("Poor", "Basic"):
        opps.append(
            {
                "title": "Expand neighborhood content",
                "reason": neighborhood["explanation"],
                "citations": neighborhood["citations"][:2],
                "impact": "High" if neighborhood["rating"] == "Poor" else "Medium",
                "effort": "Medium",
            }
        )

    # Freshness.
    for f in freshness["findings"]:
        opps.append(
            {
                "title": f"Refresh {f['issue']} on the {f['page'].replace('_', ' ')} page",
                "reason": f["evidence"],
                "citations": [_cite(prop, f["page"], [])],
                "impact": "Medium",
                "effort": "Low",
            }
        )

    opps.sort(key=lambda o: (-IMPACT_RANK[o["impact"]], EFFORT_RANK[o["effort"]]))
    for i, o in enumerate(opps, start=1):
        o["priority"] = i
    return opps


def _score(intent_results, questions, neighborhood, freshness) -> dict:
    components = {}
    if intent_results:
        avg = sum(r["coverage_ratio"] for r in intent_results) / len(intent_results)
        components["keyword_intent"] = (
            round(avg * 100, 1),
            f"Average supporting-topic coverage across {len(intent_results)} analyzed pages.",
        )
    s = questions["summary"]
    if s["total"]:
        qscore = (s["answered"] + 0.5 * s["partial"]) / s["total"] * 100
        components["question_coverage"] = (
            round(qscore, 1),
            f"{s['answered']} answered + half credit for {s['partial']} partial, of {s['total']} renter questions.",
        )
    components["neighborhood"] = (
        round(neighborhood["covered_count"] / neighborhood["total_categories"] * 100, 1),
        f"{neighborhood['covered_count']} of {neighborhood['total_categories']} neighborhood topics covered.",
    )
    if freshness["determinable"]:
        fscore = max(0, 100 - FRESHNESS_PENALTY * len(freshness["findings"]))
        components["freshness"] = (
            float(fscore),
            f"{len(freshness['findings'])} freshness issue(s), {FRESHNESS_PENALTY} points each.",
        )

    active = {k: v for k, v in components.items() if v is not None}
    total_weight = sum(WEIGHTS[k] for k in active)
    value = sum(v[0] * WEIGHTS[k] for k, v in active.items()) / total_weight
    breakdown = [
        {
            "component": k,
            "score": v[0],
            "weight": round(WEIGHTS[k] / total_weight, 2),
            "explanation": v[1],
        }
        for k, v in active.items()
    ]
    return {"value": round(value), "grade": _grade(value), "breakdown": breakdown}


def analyze_property(
    db: Session,
    property_id: int,
    today: date | None = None,
    content_provider: ContentProvider | None = None,
) -> dict:
    today = today or date.today()
    prop = db.get(Property, property_id)
    if prop is None:
        raise ValueError("Property not found.")
    from app.services.property_types import label as property_type_label

    property_type = getattr(prop, "property_type", None) or "multifamily_apartment"
    property_type_display = property_type_label(property_type)
    provider = content_provider or DevelopmentDataProvider()
    records = provider.get_content(db, property_id)

    # Property context (Phase 10.5): consumed from day one so recommendations are
    # not wrong-by-default. Operator-asserted; never inferred.
    context = get_property_context(db, property_id)
    compliance = compliance_advisory(context)
    guidance = marketing_guidance(context)

    if not records:
        return {
            "property_id": property_id,
            "property_name": prop.name,
            "property_type": property_type,
            "property_type_label": property_type_display,
            "has_content": False,
            "property_context": context,
            "compliance": compliance,
            "marketing_guidance": guidance,
            "message": "No website content has been ingested for this property. Add content to enable analysis.",
            "score": None,
            "keyword_intent": [],
            "question_coverage": {"summary": {"answered": 0, "partial": 0, "missing": 0, "total": 0}, "questions": []},
            "neighborhood": None,
            "freshness": {"determinable": False, "status": "unknown", "findings": [], "explanation": "No content to assess."},
            "opportunities": [
                {
                    "title": "Add website content",
                    "reason": "Beacon has no ingested content for this property. Add homepage, amenities, floor plans, neighborhood, and FAQ content to enable analysis.",
                    "citations": [],
                    "impact": "High",
                    "effort": "Medium",
                    "priority": 1,
                }
            ],
            "pages_present": [],
        }

    by_page = {r.page: r for r in records}
    intent_results = _keyword_intent(prop, by_page, property_type)
    questions = _question_coverage(prop, records, property_type)
    neighborhood = _neighborhood(prop, records)
    freshness = _freshness(prop, records, today)
    opportunities = _opportunities(
        prop, by_page, intent_results, questions, neighborhood, freshness
    )
    score = _score(intent_results, questions, neighborhood, freshness)

    return {
        "property_id": property_id,
        "property_name": prop.name,
        "property_type": property_type,
        "property_type_label": property_type_display,
        "has_content": True,
        "analyzed_on": today.isoformat(),
        "pages_present": sorted(by_page),
        "property_context": context,
        "compliance": compliance,
        "marketing_guidance": guidance,
        "score": score,
        "keyword_intent": intent_results,
        "question_coverage": questions,
        "neighborhood": neighborhood,
        "freshness": freshness,
        "opportunities": opportunities,
    }


def content_intelligence_summary_text(analysis: dict) -> str | None:
    """Deterministic summary indexed as a RAG chunk so Nora can answer content
    questions with citations. Returns None when there is no content."""
    if not analysis.get("has_content"):
        return None
    s = analysis["score"]
    qc = analysis["question_coverage"]["summary"]
    nb = analysis["neighborhood"]
    missing_q = [
        q["question"]
        for q in analysis["question_coverage"]["questions"]
        if q["status"] == "missing"
    ]
    top_ops = "; ".join(o["title"] for o in analysis["opportunities"][:3]) or "none"
    satisfied = sum(1 for r in analysis["keyword_intent"] if r["intent_satisfied"])
    ctx = analysis.get("property_context", {})
    eff = ctx.get("effective_regulatory", "unknown")
    guidance = analysis.get("marketing_guidance", [])
    guidance_text = (
        "; ".join(f"{g['label']} ({g['status']})" for g in guidance)
        if guidance
        else "none"
    )
    lines = [
        f"Content Intelligence for {analysis['property_name']} (as of {analysis['analyzed_on']}).",
        f"Client/site type: {analysis.get('property_type_label', 'Multifamily apartment')} "
        f"(scored against its {analysis.get('property_type', 'multifamily_apartment')} "
        "question set and content topics).",
        f"Regulatory/marketing type: {ctx.get('property_type') or 'unspecified'}. "
        f"Regulatory status: {eff.replace('_', ' ')}.",
        f"Marketing restrictions (context-gated themes to avoid or caution): {guidance_text}.",
        f"Compliance note: {analysis['compliance']['message']}",
        f"Content Intelligence score: {s['value']}/100 ({s['grade']}).",
        f"Question coverage: {qc['answered']} answered, {qc['partial']} partial, "
        f"{qc['missing']} missing of {qc['total']} renter questions.",
        f"Missing renter questions: {', '.join(missing_q) if missing_q else 'none'}.",
        f"Neighborhood coverage: {nb['rating']} ({nb['covered_count']} of "
        f"{nb['total_categories']} topics; missing {', '.join(nb['missing_categories']) or 'none'}).",
        f"Content freshness: {analysis['freshness']['status']}.",
        f"Keyword intent: {satisfied} of {len(analysis['keyword_intent'])} pages satisfy their mapped keyword intent.",
        f"Top opportunities: {top_ops}.",
    ]
    return "\n".join(lines)
