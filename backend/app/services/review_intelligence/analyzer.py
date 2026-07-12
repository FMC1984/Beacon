"""Deterministic Review Intelligence engine.

analyze_property_reviews() reasons over a property's reviews and returns an
explainable analysis: overview + sentiment, per-theme sentiment, strengths,
operational opportunities, trends, marketing insights, and a composite Review
Health Score. No LLM, no sentiment model, no embeddings. Every rule is fixed and
documented in-line and echoed in the API output, so output is reproducible.

Recommendations and marketing insights pass through the Phase 10.5 property-
context gating utility; property type / regulatory status is read, never
inferred from review content.
"""

import math
from datetime import date

from sqlalchemy.orm import Session

from app.connectors.base import ReviewProvider, ReviewRecord
from app.connectors.development import DevelopmentDataProvider
from app.models import Property
from app.services.property_context import (
    ALLOWED,
    CAUTION,
    SUPPRESSED,
    compliance_advisory,
    gate,
    get_property_context,
    marketing_guidance,
)
from app.services.review_intelligence.matching import (
    marketing_themes,
    operational_config,
    review_themes,
    sentiment_terms,
)
from app.services.semantic import match_with_negation

TREND_MIN_REVIEWS = 3  # per comparison period, per metric/theme
PRIMARY_WINDOW_DAYS = 90
FALLBACK_WINDOW_DAYS = 180
IMPACT_RANK = {"High": 3, "Medium": 2, "Low": 1}
EFFORT_RANK = {"Low": 1, "Medium": 2, "High": 3}
STABLE_EPSILON = 0.2  # rating change within this is "Stable"

SCORE_WEIGHTS = {
    "rating_health": 0.30,
    "sentiment_balance": 0.20,
    "complaint_severity": 0.20,
    "recent_review_health": 0.10,
    "response_rate": 0.10,
    "theme_consistency": 0.10,
}


def _round_half_up(value: float) -> int:
    return int(math.floor(value + 0.5))


def _bucket(rating: float | None) -> str:
    if rating is None:
        return "no_rating"
    return str(min(5, max(1, _round_half_up(rating))))


def _text(r: ReviewRecord) -> str:
    return f"{r.title or ''} {r.text or ''}"


def _rdate(r: ReviewRecord) -> date | None:
    """Review date from the connector's published_at datetime."""
    return r.published_at.date() if r.published_at else None


def _cite(prop: Property, r: ReviewRecord) -> dict:
    excerpt = (r.title or r.text or "")[:140]
    return {
        "property_id": prop.id,
        "property_name": prop.name,
        "review_id": r.review_id,
        "provider": r.provider,
        "source_ref": f"review: property={prop.id}, review_id={r.review_id}, provider={r.provider}",
        "excerpt": excerpt,
    }


# --- per-review precomputation ---


def _classify_sentiment(r: ReviewRecord, terms: dict) -> str:
    """Deterministic overall sentiment (see module docstring / API notes):
    4-5 stars positive unless a strong-negative term is present; 1-2 negative
    unless a strong-positive term is present; the middle band (and 3 stars) is
    neutral unless exactly one strong polarity is present; null rating is
    classified by term balance alone (neutral if nothing matches). Positive
    terms are negation-aware (Phase 15a): a negated positive ("not great")
    counts as negative evidence, never positive."""
    text = _text(r)
    pos_matches = match_with_negation(
        text, [t["term"] for t in terms["positive"]], positive=True
    )
    neg_matches = match_with_negation(text, [t["term"] for t in terms["negative"]])
    strong_terms = {t["term"] for t in terms["positive"] if t["strong"]}
    strong_pos = any(t in strong_terms for t in pos_matches.clean)
    strong_neg = any(
        t in {x["term"] for x in terms["negative"] if x["strong"]}
        for t in neg_matches.clean
    ) or any(t in strong_terms for t in pos_matches.flipped)

    if r.rating is None:
        p = len(pos_matches.clean)
        n = len(neg_matches.clean) + len(pos_matches.flipped)
        if p > n:
            return "positive"
        if n > p:
            return "negative"
        return "neutral"

    if r.rating >= 4:
        return "negative" if strong_neg else "positive"
    if r.rating <= 2:
        return "positive" if strong_pos else "negative"
    # middle band (2 < rating < 4, includes 3 and 3.5)
    if strong_pos and not strong_neg:
        return "positive"
    if strong_neg and not strong_pos:
        return "negative"
    return "neutral"


def _theme_class(text: str, theme: dict) -> tuple[str | None, int, int]:
    """Classify a single review for one theme. Returns (class, pos, neg) where
    class is positive/negative/mixed/neutral, or None if not a mention. A mention
    requires a positive, negative, or detail term; classification compares
    positive vs negative term counts (mention counted once regardless of term
    repetition).

    Negation-aware (Phase 15a): a negated positive term ("not very clean")
    counts as negative evidence; a term inside an absence phrase ("did not
    have a maintenance issue", "no maintenance issues") is not a mention at
    all. Plain cues never cancel negative terms, so "never fixed my broken
    heater" stays a complaint."""
    pos_m = match_with_negation(text, theme["positive_terms"], positive=True)
    neg_m = match_with_negation(text, theme["negative_terms"])
    det_m = match_with_negation(text, theme.get("detail_terms", []))
    pos = len(pos_m.clean)
    neg = len(neg_m.clean) + len(pos_m.flipped)
    detail = len(det_m.clean)
    if pos == 0 and neg == 0 and detail == 0:
        return None, 0, 0
    if pos > neg:
        return "positive", pos, neg
    if neg > pos:
        return "negative", pos, neg
    if pos > 0:  # equal and both present
        return "mixed", pos, neg
    return "neutral", pos, neg  # detail-only mention


def _window_weight(age_days: int, windows: list[dict]) -> float:
    for w in windows:
        if w["max_age_days"] is None or age_days <= w["max_age_days"]:
            return w["weight"]
    return windows[-1]["weight"]


# --- sections ---


def _overview(prop, reviews, per_review, terms) -> dict:
    total = len(reviews)
    rated = [r.rating for r in reviews if r.rating is not None]
    dist = {b: 0 for b in ("1", "2", "3", "4", "5", "no_rating")}
    for r in reviews:
        dist[_bucket(r.rating)] += 1

    sentiments = [p["sentiment"] for p in per_review]
    pos = sentiments.count("positive")
    neg = sentiments.count("negative")
    neu = sentiments.count("neutral")

    dates = [_rdate(r) for r in reviews if _rdate(r)]
    responded = sum(1 for r in reviews if (r.response_text or "").strip())
    providers = sorted({r.provider for r in reviews})

    overview = {
        "total_reviews": total,
        "average_rating": round(sum(rated) / len(rated), 2) if rated else None,
        "rating_distribution": dist,
        "rating_distribution_note": "Buckets round to the nearest whole star (round half up); reviews without a rating are counted in 'no_rating'. Buckets sum to total.",
        "most_recent_review": max(dates).isoformat() if dates else None,
        "providers": providers,
        "sentiment_breakdown": {
            "positive": pos,
            "neutral": neu,
            "negative": neg,
            "positive_pct": round(pos / total * 100, 1) if total else 0.0,
            "neutral_pct": round(neu / total * 100, 1) if total else 0.0,
            "negative_pct": round(neg / total * 100, 1) if total else 0.0,
        },
        "sentiment_note": "Positive: 4-5 stars unless a strong negative term is present. Negative: 1-2 stars unless a strong positive term is present. Neutral: 3 stars or a strong-term balance. Null rating: classified by term balance, neutral if none match.",
    }
    # Response rate is omitted entirely when no responses exist (never shown as 0%).
    if responded:
        overview["response_rate"] = round(responded / total, 3)
        overview["responses"] = responded
    return overview


def _themes(prop, reviews, per_review, anchor) -> list[dict]:
    op_cfg = operational_config()
    windows = op_cfg["severity_settings"]["recency"]["windows"]
    results = []
    for theme in review_themes():
        key = theme["key"]
        counts = {"positive": 0, "negative": 0, "mixed": 0, "neutral": 0}
        neg_reviews, pos_reviews, any_reviews = [], [], []
        recency_negatives = 0.0
        for r, pr in zip(reviews, per_review):
            cls = pr["themes"].get(key)
            if cls is None:
                continue
            counts[cls] += 1
            any_reviews.append(r)
            if cls == "negative":
                neg_reviews.append(r)
                if _rdate(r) and anchor:
                    age = (anchor - _rdate(r)).days
                    recency_negatives += _window_weight(age, windows)
                else:
                    recency_negatives += 1.0
            elif cls == "positive":
                pos_reviews.append(r)
        mentions = sum(counts.values())
        if mentions == 0:
            continue
        cat = op_cfg["categories"][theme["category"]]
        severity = round(
            cat["severity_weight"] * cat["severity_multiplier"] * recency_negatives, 1
        )
        results.append(
            {
                "theme": key,
                "label": theme["label"],
                "category": theme["category"],
                "mention_count": mentions,
                "positive": counts["positive"],
                "negative": counts["negative"],
                "mixed": counts["mixed"],
                "neutral": counts["neutral"],
                "net_sentiment": counts["positive"] - counts["negative"],
                "severity": severity,
                "citations": [_cite(prop, r) for r in (neg_reviews or any_reviews)[:5]],
                "evidence_note": "Detected from matching review terms; not semantic understanding.",
                "_neg_reviews": neg_reviews,
                "_pos_reviews": pos_reviews,
            }
        )
    return results


def _opportunities(prop, themes) -> list[dict]:
    op_cfg = operational_config()
    actions = op_cfg["suggested_actions"]
    opps = []
    for t in themes:
        if t["negative"] == 0:
            continue
        cat = op_cfg["categories"][t["category"]]
        related = [r.rating for r in t["_neg_reviews"] if r.rating is not None]
        avg_related = sum(related) / len(related) if related else 3.0
        impact_raw = t["negative"] * (6 - avg_related)
        impact = "High" if impact_raw >= 8 else "Medium" if impact_raw >= 3 else "Low"
        effort = cat["effort"]
        opps.append(
            {
                "theme": t["theme"],
                "label": t["label"],
                "negative_mentions": t["negative"],
                "severity": t["severity"],
                "severity_level": (
                    "High" if t["severity"] >= 12 else "Medium" if t["severity"] >= 4 else "Low"
                ),
                "impact": impact,
                "impact_score": min(100, round(impact_raw * 10)),
                "effort": effort,
                "suggested_action": actions[t["category"]],
                "citations": t["citations"],
                "formula_note": "Severity = severity_weight x severity_multiplier x recency-weighted negative mentions. Impact from negative mention count and average related rating. Effort is the fixed per-category default. Priority sorts high-impact/low-effort first.",
            }
        )
    opps.sort(key=lambda o: (-IMPACT_RANK[o["impact"]], EFFORT_RANK[o["effort"]]))
    for i, o in enumerate(opps, start=1):
        o["priority"] = i
    return opps


def _strengths(prop, themes, context) -> list[dict]:
    mk_by_source: dict[str, list[dict]] = {}
    for mt in marketing_themes()["themes"]:
        for src in mt["source_themes"]:
            mk_by_source.setdefault(src, []).append(mt)
    strengths = []
    for t in sorted(themes, key=lambda x: -x["positive"]):
        if t["positive"] == 0 or t["net_sentiment"] <= 0:
            continue
        rated = [r.rating for r in t["_pos_reviews"] if r.rating is not None]
        uses = []
        for mt in mk_by_source.get(t["theme"], []):
            uses.append(_gate_marketing_use(mt, context))
        strengths.append(
            {
                "theme": t["theme"],
                "label": t["label"],
                "positive_mentions": t["positive"],
                "avg_positive_rating": round(sum(rated) / len(rated), 2) if rated else None,
                "citations": [_cite(prop, r) for r in t["_pos_reviews"][:5]],
                "suggested_marketing_use": uses,
            }
        )
    return strengths


def _gate_marketing_use(marketing_theme: dict, context: dict) -> dict:
    """Gate a marketing suggestion through the property-context utility."""
    context_theme = marketing_theme.get("context_theme")
    if context_theme:
        result = gate(context, context_theme)
        status, reason = result.status, result.reason
    else:
        status, reason = ALLOWED, "No property-context restriction applies."
    return {
        "marketing_theme": marketing_theme["key"],
        "label": marketing_theme["label"],
        "suggested_use": marketing_theme["suggested_use"],
        "gating_status": status,
        "gating_reason": reason,
    }


def _marketing_insights(prop, themes, context) -> dict:
    by_theme = {t["theme"]: t for t in themes}
    cfg = marketing_themes()
    th = cfg["confidence_thresholds"]
    insights = []
    for mt in cfg["themes"]:
        pos = sum(by_theme[s]["positive"] for s in mt["source_themes"] if s in by_theme)
        neg = sum(by_theme[s]["negative"] for s in mt["source_themes"] if s in by_theme)
        support = pos + neg
        share = pos / support if support else 0.0
        if pos == 0 or neg > pos:
            confidence = "not_recommended"
        elif (
            pos >= th["supported"]["min_positive_mentions"]
            and share >= th["supported"]["min_positive_share"]
        ):
            confidence = "supported"
        else:
            confidence = "mixed"
        if pos == 0 and neg == 0:
            continue  # no review evidence at all

        gated = _gate_marketing_use(mt, context)
        caution = confidence != "supported" or gated["gating_status"] != ALLOWED
        insights.append(
            {
                "theme": mt["key"],
                "label": mt["label"],
                "confidence": confidence,
                "positive_mentions": pos,
                "negative_mentions": neg,
                "supporting_citation_count": pos + neg,
                "suggested_use": mt["suggested_use"],
                "gating_status": gated["gating_status"],
                "gating_reason": gated["gating_reason"],
                "caution": caution,
            }
        )
    return {
        "insights": insights,
        "confidence_note": "Confidence uses fixed thresholds: 'supported' needs >= 3 positive mentions and >= 60% positive share; 'not_recommended' when negatives outnumber positives or there is no positive evidence; otherwise 'mixed'.",
        "compliance": compliance_advisory(context),
        "context_guidance": marketing_guidance(context),
    }


def _window(reviews, lo: date, hi: date):
    """Reviews with review_date in [lo, hi] inclusive."""
    return [r for r in reviews if _rdate(r) and lo <= _rdate(r) <= hi]


def _trend_status(recent: float, prior: float, higher_is_better: bool) -> str:
    delta = recent - prior
    if abs(delta) <= STABLE_EPSILON * max(1.0, abs(prior)) and abs(delta) < 1:
        return "Stable"
    improving = delta > 0 if higher_is_better else delta < 0
    return "Improving" if improving else "Declining"


def _trends(prop, reviews, per_review, anchor) -> dict:
    dated = [(r, pr) for r, pr in zip(reviews, per_review) if _rdate(r)]
    if not dated or anchor is None:
        return {
            "determinable": False,
            "note": "Cannot determine trends: reviews have no dates.",
            "metrics": {},
        }

    from datetime import timedelta

    def windows(size):
        recent_lo = anchor - timedelta(days=size - 1)
        prior_hi = recent_lo - timedelta(days=1)
        prior_lo = prior_hi - timedelta(days=size - 1)
        recent = [(r, pr) for r, pr in dated if recent_lo <= _rdate(r) <= anchor]
        prior = [(r, pr) for r, pr in dated if prior_lo <= _rdate(r) <= prior_hi]
        return recent, prior, (recent_lo, anchor), (prior_lo, prior_hi)

    recent, prior, r_bounds, p_bounds = windows(PRIMARY_WINDOW_DAYS)
    window_days = PRIMARY_WINDOW_DAYS
    if len(recent) < TREND_MIN_REVIEWS or len(prior) < TREND_MIN_REVIEWS:
        recent, prior, r_bounds, p_bounds = windows(FALLBACK_WINDOW_DAYS)
        window_days = FALLBACK_WINDOW_DAYS

    def insufficient(reason_counts):
        return {"status": "Insufficient data", **reason_counts,
                "note": "Cannot determine a reliable trend because there are not enough reviews in both comparison periods."}

    metrics = {}
    enough = len(recent) >= TREND_MIN_REVIEWS and len(prior) >= TREND_MIN_REVIEWS

    # Average rating (per-metric threshold on rated reviews in each period).
    rr = [r.rating for r, _ in recent if r.rating is not None]
    pr_ = [r.rating for r, _ in prior if r.rating is not None]
    if len(rr) >= TREND_MIN_REVIEWS and len(pr_) >= TREND_MIN_REVIEWS:
        ra, pa = sum(rr) / len(rr), sum(pr_) / len(pr_)
        metrics["average_rating"] = {
            "status": _trend_status(ra, pa, True),
            "recent": round(ra, 2), "prior": round(pa, 2),
            "recent_n": len(rr), "prior_n": len(pr_),
        }
    else:
        metrics["average_rating"] = insufficient({"recent_n": len(rr), "prior_n": len(pr_)})

    # Negative review percentage (needs enough reviews in both periods).
    if enough:
        rn = sum(1 for _, p in recent if p["sentiment"] == "negative") / len(recent) * 100
        pn = sum(1 for _, p in prior if p["sentiment"] == "negative") / len(prior) * 100
        metrics["negative_pct"] = {
            "status": _trend_status(rn, pn, False),
            "recent": round(rn, 1), "prior": round(pn, 1),
            "recent_n": len(recent), "prior_n": len(prior),
        }
        metrics["review_volume"] = {
            "status": _trend_status(len(recent), len(prior), True),
            "recent": len(recent), "prior": len(prior),
        }
        rresp = sum(1 for r, _ in recent if (r.response_text or "").strip()) / len(recent) * 100
        presp = sum(1 for r, _ in prior if (r.response_text or "").strip()) / len(prior) * 100
        metrics["response_rate"] = {
            "status": _trend_status(rresp, presp, True),
            "recent": round(rresp, 1), "prior": round(presp, 1),
        }
    else:
        for m in ("negative_pct", "review_volume", "response_rate"):
            metrics[m] = insufficient({"recent_n": len(recent), "prior_n": len(prior)})

    # Per-theme complaint and praise changes. The volume threshold is applied
    # independently per theme: a theme is only trended when it has at least
    # TREND_MIN_REVIEWS mentions in EACH period, otherwise it is omitted
    # (insufficient at that granularity) even if the global volume is sufficient.
    theme_trends = {}
    for theme in review_themes():
        k = theme["key"]
        r_ment = sum(1 for _, p in recent if p["themes"].get(k) is not None)
        p_ment = sum(1 for _, p in prior if p["themes"].get(k) is not None)
        if r_ment < TREND_MIN_REVIEWS or p_ment < TREND_MIN_REVIEWS:
            continue
        r_neg = sum(1 for _, p in recent if p["themes"].get(k) == "negative")
        p_neg = sum(1 for _, p in prior if p["themes"].get(k) == "negative")
        r_pos = sum(1 for _, p in recent if p["themes"].get(k) == "positive")
        p_pos = sum(1 for _, p in prior if p["themes"].get(k) == "positive")
        theme_trends[k] = {
            "label": theme["label"],
            "complaints": {
                "status": _trend_status(r_neg, p_neg, False),
                "recent": r_neg, "prior": p_neg,
            },
            "praise": {
                "status": _trend_status(r_pos, p_pos, True),
                "recent": r_pos, "prior": p_pos,
            },
        }

    return {
        "determinable": True,
        "window_days": window_days,
        "anchored_to": anchor.isoformat(),
        "recent_period": [r_bounds[0].isoformat(), r_bounds[1].isoformat()],
        "prior_period": [p_bounds[0].isoformat(), p_bounds[1].isoformat()],
        "recent_count": len(recent),
        "prior_count": len(prior),
        "min_reviews_per_period": TREND_MIN_REVIEWS,
        "metrics": metrics,
        "theme_trends": theme_trends,
        "note": "Windows are anchored to the most recent review date, not today, so dormant profiles are not falsely flagged as declining.",
    }


def _score(overview, themes, opportunities, trends) -> dict:
    components = {}
    avg = overview["average_rating"]
    if avg is not None:
        components["rating_health"] = (round(avg / 5 * 100, 1), f"Average rating {avg}/5.")
    total = overview["total_reviews"]
    sb = overview["sentiment_breakdown"]
    if total:
        net = (sb["positive"] - sb["negative"]) / total
        components["sentiment_balance"] = (
            round((net + 1) / 2 * 100, 1),
            f"{sb['positive']} positive vs {sb['negative']} negative of {total} reviews.",
        )
    total_sev = sum(o["severity"] for o in opportunities)
    components["complaint_severity"] = (
        round(max(0.0, 100 - min(100, total_sev)), 1),
        f"Total complaint severity {round(total_sev, 1)} (higher severity lowers the score).",
    )
    if "average_rating" in trends.get("metrics", {}) and trends["metrics"]["average_rating"].get("recent") is not None:
        rr = trends["metrics"]["average_rating"]["recent"]
        components["recent_review_health"] = (round(rr / 5 * 100, 1), f"Recent-window average rating {rr}/5.")
    if "response_rate" in overview:
        components["response_rate"] = (
            round(overview["response_rate"] * 100, 1),
            f"Owner responded to {overview['responses']} of {total} reviews.",
        )
    mentioned = [t for t in themes if t["mention_count"] > 0]
    if mentioned:
        pos_themes = sum(1 for t in mentioned if t["net_sentiment"] > 0)
        components["theme_consistency"] = (
            round(pos_themes / len(mentioned) * 100, 1),
            f"{pos_themes} of {len(mentioned)} discussed themes are net-positive.",
        )

    total_weight = sum(SCORE_WEIGHTS[k] for k in components)
    value = sum(v[0] * SCORE_WEIGHTS[k] for k, v in components.items()) / total_weight
    label = (
        "Critical" if value < 20 else
        "Needs Attention" if value < 40 else
        "Basic" if value < 60 else
        "Healthy" if value < 80 else
        "Excellent"
    )
    return {
        "value": round(value),
        "label": label,
        "breakdown": [
            {"component": k, "score": v[0], "weight": round(SCORE_WEIGHTS[k] / total_weight, 2), "explanation": v[1]}
            for k, v in components.items()
        ],
    }


def analyze_property_reviews(
    db: Session,
    property_id: int,
    today: date | None = None,
    review_provider: ReviewProvider | None = None,
) -> dict:
    today = today or date.today()
    prop = db.get(Property, property_id)
    if prop is None:
        raise ValueError("Property not found.")
    provider = review_provider or DevelopmentDataProvider()
    reviews = provider.get_reviews(db, property_id)
    context = get_property_context(db, property_id)

    if not reviews:
        return {
            "property_id": property_id,
            "property_name": prop.name,
            "has_reviews": False,
            "message": "No reviews have been ingested for this property. Add reviews to enable analysis.",
            "property_context": context,
            "score": None,
            "overview": {"total_reviews": 0},
            "themes": [],
            "strengths": [],
            "opportunities": [],
            "trends": {"determinable": False, "note": "No reviews.", "metrics": {}},
            "marketing": {"insights": [], "compliance": compliance_advisory(context),
                          "context_guidance": marketing_guidance(context)},
        }

    terms = sentiment_terms()
    per_review = [
        {
            "sentiment": _classify_sentiment(r, terms),
            "themes": {
                t["key"]: _theme_class(_text(r), t)[0] for t in review_themes()
            },
        }
        for r in reviews
    ]
    anchor = max((_rdate(r) for r in reviews if _rdate(r)), default=None)

    overview = _overview(prop, reviews, per_review, terms)
    themes = _themes(prop, reviews, per_review, anchor)
    opportunities = _opportunities(prop, themes)
    strengths = _strengths(prop, themes, context)
    trends = _trends(prop, reviews, per_review, anchor)
    marketing = _marketing_insights(prop, themes, context)
    score = _score(overview, themes, opportunities, trends)

    # Strip internal helper keys before returning.
    public_themes = [{k: v for k, v in t.items() if not k.startswith("_")} for t in themes]

    return {
        "property_id": property_id,
        "property_name": prop.name,
        "has_reviews": True,
        "analyzed_on": today.isoformat(),
        "property_context": context,
        "score": score,
        "overview": overview,
        "themes": public_themes,
        "strengths": strengths,
        "opportunities": opportunities,
        "trends": trends,
        "marketing": marketing,
    }


def review_intelligence_summary_text(analysis: dict) -> str | None:
    """Deterministic summary indexed as a RAG chunk. Insufficient-data and
    confidence statements are stated verbatim so Nora grounds disclaimers in
    retrieved text, and property context is referenced for gated answers."""
    if not analysis.get("has_reviews"):
        return None
    s = analysis["score"]
    ov = analysis["overview"]
    ctx = analysis["property_context"]
    top_complaints = "; ".join(
        f"{o['label']} ({o['negative_mentions']} negative, {o['severity_level']} severity)"
        for o in analysis["opportunities"][:3]
    ) or "none"
    top_strengths = "; ".join(
        f"{st['label']} ({st['positive_mentions']} positive)" for st in analysis["strengths"][:3]
    ) or "none"
    priorities = "; ".join(
        f"{o['label']} (impact {o['impact']}, effort {o['effort']})"
        for o in analysis["opportunities"][:3]
    ) or "none"
    trends = analysis["trends"]
    if not trends.get("determinable"):
        trend_line = trends.get("note", "Trends cannot be determined.")
    else:
        parts = []
        for name, m in trends["metrics"].items():
            parts.append(f"{name}: {m['status']}")
        trend_line = "; ".join(parts)
    marketing_guidance_text = "; ".join(
        f"{g['label']} ({g['status']})" for g in analysis["marketing"]["context_guidance"]
    ) or "none"

    lines = [
        f"Review Intelligence for {analysis['property_name']} (as of {analysis['analyzed_on']}).",
        f"Property type: {ctx.get('property_type') or 'unspecified'}. "
        f"Regulatory status: {ctx['effective_regulatory'].replace('_', ' ')}.",
        f"Review Health Score: {s['value']}/100 ({s['label']}).",
        f"Reviews: {ov['total_reviews']} total, average rating "
        f"{ov['average_rating'] if ov['average_rating'] is not None else 'no ratings'}, "
        f"most recent {ov.get('most_recent_review') or 'unknown'}.",
        f"Sentiment: {ov['sentiment_breakdown']['positive']} positive, "
        f"{ov['sentiment_breakdown']['neutral']} neutral, {ov['sentiment_breakdown']['negative']} negative.",
        f"Top resident complaints: {top_complaints}.",
        f"Top resident praise: {top_strengths}.",
        f"Priority opportunities: {priorities}.",
        f"Review trends: {trend_line}.",
        f"Marketing restrictions (context-gated themes to avoid or caution): {marketing_guidance_text}.",
        f"Compliance note: {analysis['marketing']['compliance']['message']}",
    ]
    return "\n".join(lines)
