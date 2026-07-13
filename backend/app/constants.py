# Fixed user-facing copy. The disclosure text is set by the PRD (section 4.2) and
# must accompany every AI traffic figure in any API response, report, or Nora
# answer. Do not paraphrase it and do not add per-surface variants.
AI_TRAFFIC_DISCLOSURE = (
    "This reflects AI traffic that passed referrer data. "
    "Actual AI-influenced traffic is likely higher."
)

# Shown on the admin status page. TEST_COUNT is updated manually at each
# release checkpoint (pytest does not run in the server process).
APP_VERSION = "0.16.0"
APP_PHASE = (
    "Phases 1-8 complete; Phase 9 platform architecture, Phase 10 Content "
    "Intelligence, Phase 10.5 Property Context, Phase 11 Review Intelligence, "
    "Phase 11.5 AI Visibility Foundation, Phase 12 AI Visibility Scanner, Phase "
    "13 Competitor Intelligence, and Phase 14 Opportunity Engine complete; "
    "Phase 15a Semantic Intelligence (enrichment + negation) and 15b hybrid "
    "retrieval (deterministic rerank + debug) complete; 15c clustering pending. "
    "Google GA4/GSC auto-sync, admin self-check, and scheduled AI Visibility "
    "standing prompts live. Phase 16A Reports foundation (tabs, shared "
    "controls, data states, source status), 16B SEO Performance report "
    "(summary, trends, distribution, quadrant, movers, landing pages), and 16C "
    "Executive report (composed metrics, deterministic cited narrative, top "
    "actions, CSV export, print layout), and 16D GEO Visibility report "
    "(distinct metrics, sample-gated rates, prompt matrix + evidence drawers, "
    "deterministic source landscape, competitor share of tested answers), and "
    "16E AEO Readiness report (explainable weighted score, question coverage "
    "heatmap, citation readiness, structured-data empty state), and 16F "
    "(Content Impact report with before/after windows and no-causation caveat, "
    "content change log, RAG Index Health + retrieval transparency), and 16G "
    "(Audience geography report: sessions and users by city and region from GA4, "
    "AI-referral split, located-share honesty, executive top-cities panel), and "
    "16H (Google Business Profile reviews: manual CSV import now, plus a "
    "flag-gated live GBP OAuth + reviews sync connector ready for when Google "
    "approves API access), and 16I (GA4 city/region now pulled by the live sync "
    "into the Audience report, and a new GA4 events breakdown from sync + CSV "
    "shown on the Dashboard and SEO report) complete"
)
TEST_COUNT = 524
