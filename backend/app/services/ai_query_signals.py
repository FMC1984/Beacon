"""AI Query Signals: a deterministic, evidence-first view of AI-referred traffic.

Beacon can see that a visit came from an AI platform and where it landed, but
referral analytics NEVER carry the exact prompt a person typed into an LLM. This
module therefore separates what is known into three honest tiers and never
crosses between them:

  1. Observed        - GA4 AI-referred sessions, platforms, landing pages,
                       engagement, conversions, dates (real ingested rows).
  2. Search-Adjacent - Google Search Console queries observed for the SAME
                       landing page. These are Google searches, not LLM prompts;
                       shown only when a page/query association can be established.
  3. Inferred        - Likely topics/renter-questions deduced deterministically
                       from landing-page paths, Content Intelligence topic
                       coverage, stored content, and search-adjacent queries.
                       Every inferred item is explicitly labeled as NOT a prompt.

No external AI is called. No embeddings. No fabricated queries. Recommendations
are evidence-backed and gated through the existing Property Context gate().
"""

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.connectors.base import ContentProvider
from app.connectors.development import DevelopmentDataProvider
from app.models import GA4SessionsDaily, GSCPerformanceDaily, Property
from app.services.classifier import get_classifier
from app.services.content_intelligence import analyze_property
from app.services.content_intelligence.matching import content_intent, matched_terms
from app.services.property_context import (
    REGULATED,
    SUPPRESSED,
    UNKNOWN,
    gate_text,
    get_property_context,
)

# --- fixed thresholds (deterministic) ---
MIN_AI_SESSIONS_FOR_RECS = 5  # below this, we do not generate recommendations
MIN_SESSIONS_FOR_COMPARISON = 20  # AI and non-AI both need this to be compared
LOW_ENGAGEMENT_RATE = 0.40  # engagement below this is flagged as low
GSC_QUERY_DISPLAY_LIMIT = 10
LANDING_PAGE_DISPLAY_LIMIT = 25

# --- fixed user-facing copy (never paraphrased per-surface) ---
PROMPT_LIMITATION = (
    "Beacon can identify AI-referred visits and landing pages, but referral data "
    "does not include the exact prompt someone entered into an AI tool. Exact LLM "
    "prompts cannot be determined from referral analytics alone."
)
OBSERVED_BANNER = (
    "Beacon can identify AI-referred visits and landing pages, but referral data "
    "does not include the exact prompt someone entered into an AI tool."
)
PERSISTENT_NOTE = (
    "AI platforms generally do not pass the exact question or prompt used by a "
    "visitor. Beacon shows observed referral data, related search signals, and "
    "clearly labeled topic inferences."
)
INFERRED_LABEL = (
    "Inferred from landing-page and content signals. This is not an actual AI prompt."
)
SEARCH_ADJACENT_DISCLOSURE = (
    "These are observed Google Search queries associated with this landing page. "
    "They are not prompts entered into ChatGPT, Perplexity, Gemini, or another AI "
    "tool."
)
GSC_UNAVAILABLE = (
    "Search-adjacent query data is unavailable because Google Search Console data "
    "is not connected or does not contain matching page/query data for this period."
)
REQUIRES_CONFIRMATION_MSG = (
    "Eligibility- or pricing-related topic signal detected. Confirm approved "
    "property messaging before creating marketing recommendations."
)

# Topic/keyword hints that make a recommendation compliance-sensitive (price,
# eligibility, affordability, audience/positioning). Deterministic substring set.
SENSITIVE_KEYWORDS = (
    "pricing", "price", "availab", "afford", "income", "eligib", "voucher",
    "special", "concession", "luxury", "student", "senior", "military",
)

# Landing-path/title classifier into a canonical content page. Checked in order;
# first match wins. Tight, explainable keyword sets - never a guess about intent.
_CANONICAL_KEYWORDS = [
    ("faq", ("faq", "faqs", "frequently-asked", "questions", "help")),
    ("floor_plans", ("floor", "floorplan", "floor-plan", "plans", "availab", "apartments")),
    ("amenities", ("amenit", "feature", "pet", "parking", "pool", "gym", "fitness")),
    ("neighborhood", ("neighborhood", "neighbourhood", "location", "nearby", "area", "explore")),
]
_HOMEPAGE_PATHS = {"", "/", "/home", "/index", "home", "index"}

CONFIDENCE_STRONG = "Strong signal"
CONFIDENCE_SUPPORTED = "Supported signal"
CONFIDENCE_LIMITED = "Limited signal"
CONFIDENCE_NONE = "Cannot determine"

_CONFIDENCE_BY_SIGNAL_COUNT = {3: CONFIDENCE_STRONG, 2: CONFIDENCE_SUPPORTED, 1: CONFIDENCE_LIMITED}


def _norm_path(value: str | None) -> str | None:
    """Reduce a landing page / GSC page to a comparable path: strip scheme+host,
    lowercase, drop query/fragment, strip a trailing slash."""
    if not value:
        return None
    s = value.strip().lower()
    if "://" in s:
        s = s.split("://", 1)[1]
        s = s.split("/", 1)[1] if "/" in s else ""
        s = "/" + s
    s = s.split("?", 1)[0].split("#", 1)[0]
    if len(s) > 1:
        s = s.rstrip("/")
    return s or "/"


def _canonical_page(path: str | None, title: str | None = None) -> str | None:
    hay = f"{path or ''} {title or ''}".lower()
    norm = _norm_path(path)
    if norm in _HOMEPAGE_PATHS:
        return "homepage"
    for page, keys in _CANONICAL_KEYWORDS:
        if any(k in hay for k in keys):
            return page
    return None


@dataclass
class _AIGroup:
    landing_page: str
    sessions: int = 0
    engaged: int = 0
    key_events: int = 0
    platforms: dict | None = None

    def __post_init__(self):
        if self.platforms is None:
            self.platforms = {}


def _within(q, model, start: date | None, end: date | None):
    if start is not None:
        q = q.filter(model.date >= start)
    if end is not None:
        q = q.filter(model.date <= end)
    return q


def analyze_ai_query_signals(
    db: Session,
    property_id: int,
    start: date | None = None,
    end: date | None = None,
    platform: str | None = None,
    landing_page: str | None = None,
    content_provider: ContentProvider | None = None,
    today: date | None = None,
) -> dict:
    today = today or date.today()
    prop = db.get(Property, property_id)
    if prop is None:
        raise ValueError("Property not found.")
    provider = content_provider or DevelopmentDataProvider()
    labels = {p.key: p.label for p in get_classifier().platforms}

    ai_q = db.query(GA4SessionsDaily).filter_by(
        property_id=property_id, is_ai_referral=True
    )
    ai_q = _within(ai_q, GA4SessionsDaily, start, end)
    if platform:
        ai_q = ai_q.filter(GA4SessionsDaily.ai_platform == platform)
    ai_rows = ai_q.all()
    if landing_page:
        target = _norm_path(landing_page)
        ai_rows = [r for r in ai_rows if _norm_path(r.landing_page) == target]

    context = get_property_context(db, property_id)

    base = {
        "property_id": property_id,
        "property_name": prop.name,
        "meta": {
            "data_source": "GA4 AI-referred sessions (manual upload)",
            "date_range": None,
            "generated_on": today.isoformat(),
            "platform_filter": platform,
            "landing_page_filter": landing_page,
        },
        "disclaimers": {
            "prompt_limitation": OBSERVED_BANNER,
            "persistent_note": PERSISTENT_NOTE,
        },
    }

    if not ai_rows:
        return {
            **base,
            "has_ai_traffic": False,
            "overview": None,
            "landing_pages": [],
            "search_adjacent": {
                "available": False,
                "evidence_type": "search_adjacent",
                "message": GSC_UNAVAILABLE,
                "associations": [],
            },
            "inferred_topics": [],
            "renter_question_signals": [],
            "recommendations": [],
            "limitations": [
                PROMPT_LIMITATION,
                "No AI-referred sessions are recorded for this property in the "
                "selected period, so there are no signals to analyze.",
            ],
        }

    # --- OBSERVED ---
    ai_dates = [r.date for r in ai_rows]
    obs_start, obs_end = min(ai_dates), max(ai_dates)
    base["meta"]["date_range"] = {"start": obs_start.isoformat(), "end": obs_end.isoformat()}

    total_ai_sessions = sum(r.sessions for r in ai_rows)
    ai_engaged = sum(r.engaged_sessions for r in ai_rows)
    ai_key_events = sum(r.key_events for r in ai_rows)

    platform_mix: dict[str, int] = {}
    for r in ai_rows:
        platform_mix[r.ai_platform] = platform_mix.get(r.ai_platform, 0) + r.sessions
    platform_mix_list = [
        {"platform": k, "label": labels.get(k, k), "sessions": v}
        for k, v in sorted(platform_mix.items(), key=lambda kv: -kv[1])
    ]

    # Non-AI comparison, only when both sides have enough volume.
    non_ai_q = _within(
        db.query(GA4SessionsDaily).filter_by(property_id=property_id, is_ai_referral=False),
        GA4SessionsDaily, start, end,
    )
    non_ai_rows = non_ai_q.all()
    non_ai_sessions = sum(r.sessions for r in non_ai_rows)
    non_ai_engaged = sum(r.engaged_sessions for r in non_ai_rows)
    comparison = None
    if total_ai_sessions >= MIN_SESSIONS_FOR_COMPARISON and non_ai_sessions >= MIN_SESSIONS_FOR_COMPARISON:
        comparison = {
            "ai_engagement_rate": round(ai_engaged / total_ai_sessions, 3) if total_ai_sessions else 0.0,
            "non_ai_engagement_rate": round(non_ai_engaged / non_ai_sessions, 3) if non_ai_sessions else 0.0,
        }

    # Landing-page grouping (observed).
    groups: dict[str, _AIGroup] = {}
    for r in ai_rows:
        key = r.landing_page or "(not set)"
        g = groups.setdefault(key, _AIGroup(landing_page=key))
        g.sessions += r.sessions
        g.engaged += r.engaged_sessions
        g.key_events += r.key_events
        g.platforms[r.ai_platform] = g.platforms.get(r.ai_platform, 0) + r.sessions
    ordered_groups = sorted(groups.values(), key=lambda g: -g.sessions)

    # Content Intelligence, reused once for topic coverage + citations.
    ci = analyze_property(db, property_id, today=today, content_provider=provider)

    # --- SEARCH-ADJACENT (GSC) ---
    gsc_q = _within(
        db.query(GSCPerformanceDaily).filter_by(property_id=property_id),
        GSCPerformanceDaily, start, end,
    )
    gsc_rows = [r for r in gsc_q.all()]
    gsc_present = len(gsc_rows) > 0
    # Index GSC rows by normalized page (only rows that carry both page + query).
    gsc_by_page: dict[str, list] = {}
    for r in gsc_rows:
        if r.page and r.query:
            gsc_by_page.setdefault(_norm_path(r.page), []).append(r)

    search_associations = []
    for g in ordered_groups:
        norm = _norm_path(g.landing_page)
        matches = gsc_by_page.get(norm) if norm else None
        if not matches:
            continue
        agg: dict[str, dict] = {}
        for r in matches:
            a = agg.setdefault(
                r.query, {"clicks": 0, "impressions": 0, "pos_weight": 0.0}
            )
            a["clicks"] += r.clicks
            a["impressions"] += r.impressions
            a["pos_weight"] += r.position * r.impressions
        queries = sorted(
            (
                {
                    "query": q,
                    "clicks": v["clicks"],
                    "impressions": v["impressions"],
                    "ctr": round(v["clicks"] / v["impressions"], 4) if v["impressions"] else 0.0,
                    "avg_position": round(v["pos_weight"] / v["impressions"], 1) if v["impressions"] else 0.0,
                    "evidence_type": "search_adjacent",
                }
                for q, v in agg.items()
            ),
            key=lambda x: -x["clicks"],
        )[:GSC_QUERY_DISPLAY_LIMIT]
        search_associations.append(
            {
                "landing_page": g.landing_page,
                "query_count": len(agg),
                "queries": queries,
                "source_ref": f"gsc_performance_daily: property={property_id}, page={norm}",
            }
        )

    search_adjacent = {
        "available": bool(search_associations),
        "gsc_present": gsc_present,
        "evidence_type": "search_adjacent",
        "disclosure": SEARCH_ADJACENT_DISCLOSURE,
        "message": SEARCH_ADJACENT_DISCLOSURE if search_associations else GSC_UNAVAILABLE,
        "associations": search_associations,
    }
    # Queries matched to a landing page, for inferred-topic corroboration.
    queries_for_page = {a["landing_page"]: [q["query"] for q in a["queries"]] for a in search_associations}

    # --- LANDING PAGES (observed + deterministic content association) ---
    intent = content_intent()
    ci_by_page = {r["page"]: r for r in ci.get("keyword_intent", [])}
    landing_pages = []
    ai_canonical_pages: dict[str, int] = {}  # canonical page -> AI sessions
    for g in ordered_groups[:LANDING_PAGE_DISPLAY_LIMIT]:
        canonical = _canonical_page(g.landing_page)
        related_topics = []
        ci_findings = []
        citations = [
            {
                "source_table": "ga4_sessions_daily",
                "source_ref": f"ga4_sessions_daily: property={property_id}, landing_page={g.landing_page}",
                "evidence_type": "observed",
            }
        ]
        if canonical:
            ai_canonical_pages[canonical] = ai_canonical_pages.get(canonical, 0) + g.sessions
            spec = intent["pages"].get(canonical)
            if spec:
                related_topics = [t["label"] for t in spec["required_topics"]]
            page_ci = ci_by_page.get(canonical)
            if page_ci:
                if page_ci["missing_topics"]:
                    ci_findings.append(
                        f"Content Intelligence: the {canonical.replace('_', ' ')} "
                        f"page is missing topics: {', '.join(page_ci['missing_topics'])}."
                    )
                else:
                    ci_findings.append(
                        f"Content Intelligence: the {canonical.replace('_', ' ')} "
                        "page covers all its expected topics."
                    )
                citations.append(
                    {
                        "source_table": "content_intelligence",
                        "source_ref": f"content: property={property_id}, page={canonical}",
                        "evidence_type": "inferred",
                    }
                )
        landing_pages.append(
            {
                "landing_page": g.landing_page,
                "evidence_type": "observed",
                "sessions": g.sessions,
                "engaged_sessions": g.engaged,
                "engagement_rate": round(g.engaged / g.sessions, 3) if g.sessions else 0.0,
                "key_events": g.key_events,
                "platform_breakdown": [
                    {"platform": k, "label": labels.get(k, k), "sessions": v}
                    for k, v in sorted(g.platforms.items(), key=lambda kv: -kv[1])
                ],
                "date_range": {"start": obs_start.isoformat(), "end": obs_end.isoformat()},
                "canonical_page": canonical,
                "related_topics": related_topics,
                "ci_findings": ci_findings,
                "citations": citations,
            }
        )

    # --- INFERRED TOPICS ---
    inferred_topics = _infer_topics(
        property_id, ai_canonical_pages, ordered_groups, ci_by_page,
        queries_for_page, intent,
    )

    # --- RENTER QUESTION SIGNALS ---
    renter_signals = _renter_question_signals(
        ci, ai_canonical_pages, ordered_groups, queries_for_page, context,
    )

    # --- RECOMMENDATIONS (evidence-backed, gated) ---
    recommendations, rec_limitations = _recommendations(
        total_ai_sessions, inferred_topics, renter_signals, landing_pages, context,
    )

    limitations = [PROMPT_LIMITATION]
    if not search_adjacent["available"]:
        limitations.append(GSC_UNAVAILABLE)
    if total_ai_sessions < MIN_AI_SESSIONS_FOR_RECS:
        limitations.append(
            f"AI-referred volume is low ({total_ai_sessions} sessions); "
            "recommendations are withheld until there is more traffic."
        )
    if all(g.landing_page == "(not set)" for g in ordered_groups):
        limitations.append(
            "Landing pages are not present in the ingested GA4 export, so "
            "page-level and topic inferences cannot be established."
        )
    limitations.extend(rec_limitations)

    return {
        **base,
        "has_ai_traffic": True,
        "overview": {
            "evidence_type": "observed",
            "banner": OBSERVED_BANNER,
            "total_ai_sessions": total_ai_sessions,
            "ai_platform_mix": platform_mix_list,
            "top_landing_pages": [
                {"landing_page": g.landing_page, "sessions": g.sessions}
                for g in ordered_groups[:5]
            ],
            "engagement": {
                "ai_engaged_sessions": ai_engaged,
                "ai_engagement_rate": round(ai_engaged / total_ai_sessions, 3) if total_ai_sessions else 0.0,
                "comparison": comparison,
            },
            "conversions": {"ai_key_events": ai_key_events},
            "date_range": {"start": obs_start.isoformat(), "end": obs_end.isoformat()},
        },
        "landing_pages": landing_pages,
        "search_adjacent": search_adjacent,
        "inferred_topics": inferred_topics,
        "renter_question_signals": renter_signals,
        "recommendations": recommendations,
        "limitations": limitations,
    }


def _infer_topics(
    property_id, ai_canonical_pages, ordered_groups, ci_by_page,
    queries_for_page, intent,
) -> list[dict]:
    """Deterministic topic inference. A topic is corroborated by up to three
    independent signal types: (1) an AI landing page whose intent includes it,
    (2) the property's content covering it, (3) related GSC queries matching its
    terms. Confidence is the count of distinct signal types."""
    # landing-page label lookup for the canonical page
    page_landing = {}
    for g in ordered_groups:
        c = _canonical_page(g.landing_page)
        if c:
            page_landing.setdefault(c, []).append(g.landing_page)

    merged: dict[str, dict] = {}
    for canonical, ai_sessions in ai_canonical_pages.items():
        spec = intent["pages"].get(canonical)
        if not spec:
            continue
        page_ci = ci_by_page.get(canonical)
        covered = set(page_ci["covered_topics"]) if page_ci else set()
        # GSC queries associated with any landing page mapped to this canonical.
        related_queries = []
        for lp in page_landing.get(canonical, []):
            related_queries.extend(queries_for_page.get(lp, []))

        for topic in spec["required_topics"]:
            label = topic["label"]
            signals = {"landing_page"}
            if label in covered:
                signals.add("content_topic")
            gsc_hits = [
                qtext for qtext in related_queries
                if matched_terms(qtext, topic["terms"])
            ]
            if gsc_hits:
                signals.add("gsc_query")

            entry = merged.setdefault(
                label,
                {
                    "topic": label,
                    "evidence_type": "inferred",
                    "signal_types": set(),
                    "supporting_landing_pages": set(),
                    "supporting_gsc_query_count": 0,
                    "content_covered": False,
                    "citations": [],
                    "label": INFERRED_LABEL,
                },
            )
            entry["signal_types"] |= signals
            entry["supporting_landing_pages"] |= set(page_landing.get(canonical, []))
            entry["supporting_gsc_query_count"] += len(gsc_hits)
            entry["content_covered"] = entry["content_covered"] or (label in covered)

    result = []
    for label, e in merged.items():
        signal_types = sorted(e["signal_types"])
        confidence = _CONFIDENCE_BY_SIGNAL_COUNT.get(len(signal_types), CONFIDENCE_NONE)
        landing = sorted(e["supporting_landing_pages"])
        citations = [
            {
                "source_table": "ga4_sessions_daily",
                "source_ref": f"ga4_sessions_daily: property={property_id}, landing_pages={', '.join(landing) or 'n/a'}",
                "evidence_type": "observed",
            }
        ]
        if e["content_covered"]:
            citations.append(
                {
                    "source_table": "content_intelligence",
                    "source_ref": f"content_intelligence: property={property_id}",
                    "evidence_type": "inferred",
                }
            )
        if e["supporting_gsc_query_count"]:
            citations.append(
                {
                    "source_table": "gsc_performance_daily",
                    "source_ref": f"gsc_performance_daily: property={property_id}",
                    "evidence_type": "search_adjacent",
                }
            )
        parts = ["AI-referred visitors landed on a page whose intent includes this topic"]
        if e["content_covered"]:
            parts.append("the property's content covers it")
        if e["supporting_gsc_query_count"]:
            parts.append(
                f"related Google Search queries also match it ({e['supporting_gsc_query_count']})"
            )
        explanation = ", and ".join(parts) + ". " + INFERRED_LABEL
        result.append(
            {
                "topic": label,
                "evidence_type": "inferred",
                "signal_types": signal_types,
                "confidence": confidence,
                "supporting_landing_pages": landing,
                "supporting_gsc_query_count": e["supporting_gsc_query_count"],
                "content_covered": e["content_covered"],
                "explanation": explanation,
                "label": INFERRED_LABEL,
                "citations": citations,
            }
        )
    # Strongest evidence first.
    order = {CONFIDENCE_STRONG: 3, CONFIDENCE_SUPPORTED: 2, CONFIDENCE_LIMITED: 1, CONFIDENCE_NONE: 0}
    result.sort(key=lambda t: (-order[t["confidence"]], t["topic"]))
    return result


def _renter_question_signals(
    ci, ai_canonical_pages, ordered_groups, queries_for_page, context,
) -> list[dict]:
    """Map Content Intelligence renter-question coverage to AI-traffic signals.
    A question is 'signaled' when its content citations sit on an AI-landed page
    or related GSC queries match it. Derived from known content and search
    signals, never guessed behavior."""
    if not ci.get("has_content"):
        return []
    ai_pages = set(ai_canonical_pages)
    all_related_queries = [q for qs in queries_for_page.values() for q in qs]
    signals = []
    for q in ci["question_coverage"]["questions"]:
        cited_pages = {c["page"] for c in q["citations"]}
        on_ai_page = bool(cited_pages & ai_pages)
        gsc_hits = [
            qt for qt in all_related_queries
            if matched_terms(qt, [q["question"]] + q.get("matched_terms", []))
        ]
        if not on_ai_page and not gsc_hits:
            continue
        signal_count = int(on_ai_page) + int(bool(gsc_hits))
        evidence = _CONFIDENCE_BY_SIGNAL_COUNT.get(
            signal_count + (1 if q["status"] == "answered" else 0), CONFIDENCE_LIMITED
        )
        related_landing = sorted(
            {g.landing_page for g in ordered_groups if _canonical_page(g.landing_page) in cited_pages}
        )
        action = None
        if q["status"] in ("missing", "partial"):
            verb = "Add" if q["status"] == "missing" else "Expand"
            action = (
                f"{verb} content answering '{q['question']}' - it is a topic signal "
                f"from AI traffic but the website coverage is {q['status']}."
            )
        signals.append(
            {
                "question": q["question"],
                "category": q["category"],
                "evidence_type": "inferred",
                "evidence_level": evidence,
                "related_landing_pages": related_landing,
                "related_gsc_query_count": len(gsc_hits),
                "content_coverage_status": q["status"],
                "recommended_action": action,
                "citations": q["citations"],
                "label": INFERRED_LABEL,
            }
        )
    order = {CONFIDENCE_STRONG: 3, CONFIDENCE_SUPPORTED: 2, CONFIDENCE_LIMITED: 1, CONFIDENCE_NONE: 0}
    signals.sort(key=lambda s: (-order[s["evidence_level"]], s["question"]))
    return signals


def _gate_recommendation(context, topic_label: str, text: str) -> tuple[str | None, str | None]:
    """Return (blocking_state, reason) if Property Context restricts this
    recommendation, else (None, None). Positioning themes can be suppressed; any
    price/eligibility-adjacent topic requires confirmation when the property's
    regulatory status is regulated or unknown."""
    probe = f"{topic_label} {text}"
    gt = gate_text(context, probe)
    if gt.status == SUPPRESSED:
        return "Suppressed", gt.reason
    sensitive = any(kw in probe.lower() for kw in SENSITIVE_KEYWORDS)
    if sensitive and context["effective_regulatory"] in (UNKNOWN, REGULATED):
        return "Requires confirmation", REQUIRES_CONFIRMATION_MSG
    return None, None


def _recommendations(
    total_ai_sessions, inferred_topics, renter_signals, landing_pages, context,
) -> tuple[list[dict], list[str]]:
    """Evidence-backed only. States: Actionable, Monitor, Requires confirmation,
    Suppressed. (Insufficient data is expressed by returning no recommendations
    plus a limitation.)"""
    if total_ai_sessions < MIN_AI_SESSIONS_FOR_RECS:
        return [], []

    recs = []
    limitations = []

    def add(title, reason, topic_label, evidence_level, citations, base_state):
        block_state, block_reason = _gate_recommendation(context, topic_label, f"{title} {reason}")
        if block_state == "Suppressed":
            recs.append(
                {
                    "title": title, "reason": reason, "topic": topic_label,
                    "state": "Suppressed", "gate_reason": block_reason,
                    "evidence_level": evidence_level, "citations": citations,
                }
            )
            return
        state = block_state or base_state
        recs.append(
            {
                "title": title, "reason": reason, "topic": topic_label,
                "state": state, "gate_reason": block_reason,
                "evidence_level": evidence_level, "citations": citations,
            }
        )

    # 1. Signaled renter questions with a coverage gap.
    for s in renter_signals:
        if s["content_coverage_status"] in ("missing", "partial") and s["recommended_action"]:
            base_state = "Actionable" if s["evidence_level"] in (CONFIDENCE_STRONG, CONFIDENCE_SUPPORTED) else "Monitor"
            add(
                s["recommended_action"].split(" - ")[0],
                f"AI-referred traffic signals interest in '{s['question']}' but website "
                f"coverage is {s['content_coverage_status']}.",
                s["question"], s["evidence_level"], s["citations"], base_state,
            )

    # 2. Inferred topics with GSC corroboration but incomplete content.
    for t in inferred_topics:
        if t["supporting_gsc_query_count"] and not t["content_covered"]:
            add(
                f"Strengthen {t['topic']} content",
                f"Related Google Search queries ({t['supporting_gsc_query_count']}) and "
                f"AI landing-page signals point to {t['topic']}, but the property's "
                "content does not cover it.",
                t["topic"], t["confidence"], t["citations"], "Actionable",
            )

    # 3. Landing pages with low engagement from AI visitors.
    for lp in landing_pages:
        if lp["sessions"] >= MIN_AI_SESSIONS_FOR_RECS and lp["engagement_rate"] < LOW_ENGAGEMENT_RATE:
            add(
                f"Review the {lp['landing_page']} landing experience",
                f"{lp['sessions']} AI-referred sessions landed here with a low "
                f"engagement rate ({int(lp['engagement_rate'] * 100)}%).",
                lp.get("canonical_page") or lp["landing_page"],
                "Supported signal", lp["citations"], "Monitor",
            )

    if not recs:
        limitations.append(
            "No evidence-backed recommendations met the confidence and volume bar "
            "for this period."
        )
    return recs, limitations


def ai_query_signals_summary_text(analysis: dict) -> str | None:
    """Deterministic summary indexed as an `ai_query_signals` RAG chunk so Nora
    answers AI-traffic questions with citations and inherits the exact-prompt
    limitation. Returns None when there is no AI-referred traffic."""
    if not analysis.get("has_ai_traffic"):
        return None
    ov = analysis["overview"]
    name = analysis["property_name"]
    dr = ov["date_range"]
    mix = "; ".join(f"{m['label']} {m['sessions']}" for m in ov["ai_platform_mix"]) or "none"
    top_pages = "; ".join(
        f"{p['landing_page']} ({p['sessions']})" for p in ov["top_landing_pages"]
    ) or "none recorded"

    sa = analysis["search_adjacent"]
    if sa["available"]:
        themes = []
        for a in sa["associations"]:
            themes.append(
                f"{a['landing_page']}: " + ", ".join(q["query"] for q in a["queries"][:5])
            )
        sa_line = "Search-adjacent Google Search queries (NOT LLM prompts): " + " | ".join(themes)
    else:
        sa_line = "Search-adjacent queries: unavailable (no matching GSC page/query data)."

    inferred = "; ".join(
        f"{t['topic']} ({t['confidence']})" for t in analysis["inferred_topics"][:6]
    ) or "none"
    gaps = "; ".join(
        s["question"] for s in analysis["renter_question_signals"]
        if s["content_coverage_status"] in ("missing", "partial")
    ) or "none identified"
    recs = "; ".join(f"{r['title']} [{r['state']}]" for r in analysis["recommendations"][:5]) or "none"

    lines = [
        f"AI Query Signals for {name}. Period: {dr['start']} to {dr['end']}.",
        f"Observed AI-referred sessions: {ov['total_ai_sessions']}. "
        f"AI platform mix: {mix}.",
        f"Top AI-referred landing pages: {top_pages}.",
        f"AI-referred conversions (key events): {ov['conversions']['ai_key_events']}.",
        sa_line,
        f"Inferred topic signals (deterministic, not prompts): {inferred}.",
        f"Content coverage gaps tied to AI-traffic signals: {gaps}.",
        f"Evidence-backed recommendations: {recs}.",
        f"IMPORTANT LIMITATION: {PROMPT_LIMITATION}",
    ]
    ctx = analysis.get("property_context") if isinstance(analysis.get("property_context"), dict) else None
    if any(r["state"] in ("Suppressed", "Requires confirmation") for r in analysis["recommendations"]):
        lines.append(
            "Some recommendations are gated by Property Context (suppressed or "
            "requiring confirmation of approved messaging)."
        )
    return "\n".join(lines)
