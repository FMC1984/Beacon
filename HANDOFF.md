# Beacon — Session Handoff

Last updated: 2026-07-12. Read this first in a new session before touching anything.

## What Beacon is

Internal AI-performance intelligence dashboard for multifamily/housing-authority
marketing, built for Tina. FastAPI + SQLite/Alembic + ChromaDB backend, Next.js
frontend. Tracks AI referral traffic, ties it to CRM/lease outcomes, and
surfaces Nora, a retrieval-grounded analyst that answers only from ingested,
cited data. Deterministic-first philosophy: every intelligence module (Content,
Review, AI Query Signals, AI Visibility, Competitor, Opportunity Engine) is rule-
based and explainable, never an LLM guessing. The only non-deterministic calls
in the whole system are: OpenAI embeddings, Nora's generation step, and the
external AI-visibility query execution (asking ChatGPT a question) — everything
downstream of those is deterministic parsing.

Read `CLAUDE.md` (build rules/hard rules), `docs/beacon-prd-v2.md`, and
`docs/beacon-build-plan-v1.md` before changing code. README.md is the
operational doc (env vars, deploy steps, feature docs per phase).

## Where it lives

- **Local:** `/Users/fiorentinawilliamson/Beacon` (this repo). Backend port 8600,
  frontend port 3100. `~/Builder/.claude/launch.json` has `beacon-backend` /
  `beacon-frontend` preview configs.
- **GitHub:** `https://github.com/FMC1984/Beacon` (private). Pushing to `main`
  auto-deploys both Render services.
- **Hosted (the real one Tina uses):** frontend
  `https://beacon-frontend-app.onrender.com`, backend
  `https://beacon-backend-s6yd.onrender.com`. **Note the `-s6yd` suffix is
  load-bearing** — `beacon-backend.onrender.com` (no suffix) is a STRANGER'S
  Express app, not ours; that subdomain was taken. Never point config at the
  no-suffix URL.
- Render backend has a 1GB persistent disk at `/var/data` holding
  `beacon.db`, `.chroma/`, and `data/uploads/`. Frontend has no disk (stateless,
  free tier).

## Local vs hosted — they are SEPARATE databases

The Mac's `beacon.db` and Render's `/var/data/beacon.db` do not sync
automatically. Local will drift stale since Render's daily Google auto-sync
only touches Render's copy. **Treat the hosted instance as the source of
truth going forward.** If local ever needs to be pushed up again, there's a
one-time admin endpoint for it (see "DB restore" below) — do not casually
run it again without checking which direction data should flow first.

## Access & secrets

- Hosted Beacon is behind a shared access key: `BEACON_ACCESS_KEY` env var on
  Render's backend. The frontend has a one-time unlock screen
  (`components/AccessGate.tsx`) that stores the key in localStorage and
  attaches it as `X-Beacon-Key` to every API call via a patched `fetch`.
  `/api/health` and `/api/google/callback` are exempt (health checks and
  Google's redirect can't send custom headers).
- `backend/.env` (gitignored, chmod 600) holds the real OpenAI key locally.
  Render has its own copy in the dashboard env vars (`sync: false` in
  render.yaml — entered once by Tina, not in git).
- **Never commit `.env`, `beacon.db`, `.chroma/`, or `data/`.** `.gitignore`
  already excludes these; double-check `git status` before any commit that
  touches config.

## Deploy mechanics

- `render.yaml` at repo root is the Blueprint — both services, their env vars,
  disk config, build/start commands. Editing it requires a `git push` to take
  effect (Render doesn't hot-reload the blueprint).
- Backend start command runs `alembic upgrade head` before `uvicorn`, so a
  broken migration blocks the whole deploy (Render shows it as failed, old
  version stays live — not a silent bad deploy, but check logs if a deploy
  doesn't go live within ~5 min).
- After pushing, poll `curl https://beacon-backend-s6yd.onrender.com/api/health`
  — expect a `502` for the first ~30-90s while it restarts, then
  `{"status":"ok","database":"reachable"}`.
- **SQLite + Alembic gotcha:** SQLite can't `ALTER` in a new FK constraint via
  plain `add_column`. Any migration adding a `ForeignKey`-backed column MUST
  use `op.batch_alter_table(...)` (see `d0e1f2a3b4c5_google_connection_fields.py`
  for the pattern) or `alembic upgrade` throws
  `NotImplementedError: No support for ALTER of constraints`.

## What's built (reverse chronological, most recent first)

### Flow P1d: Nora reads the Observatory (2026-09-16, 827 tests)
- `services/observatory/summary.py`: `observatory_summary_text` builds one
  deterministic chunk per property from the same rollups the Overview
  reads (AI Visibility, Citation Rate, Recommendation Rate, Share of Voice
  with point changes and labels), `source_influence` top domains, cited
  pages that do not mention the property, rankings by question (needs-work
  rows with the leader), open claim conflicts and open alerts. None below
  the monitoring sample minimum. `explain_visibility_change` mirrors
  `explain_sov_change` over `ai_cluster_visibility_daily`: the one cluster
  whose change covers at least half the aggregate move in the same
  direction, both windows sufficient, aggregate at least 3 points
  (`MIN_AGGREGATE_CHANGE`), else None.
- RAG: source `ai_observatory` (`_ai_observatory_chunks`,
  `chroma_id ai_observatory-p{id}`); the `ai_visibility`, `competitors` and
  `property_context` widen lists refresh it. Existing hosted indexes pick it
  up at the next sync or a full rebuild from Admin.
- Nora: `is_visibility_question`, `VISIBILITY_DIAGNOSIS_PROMPT` /
  `VISIBILITY_NO_DIAGNOSIS_PROMPT`, `visibility_gate` in the ask result
  (null for unrelated questions; Share of Voice questions keep their own
  gate and never trigger both).
- Tests: `tests/test_flow_nora_observatory.py` (8).

### Flow P1c: one definition of AI visibility (2026-09-16, 819 tests)
- `reporting_geo.py`: summary, sufficiency and the daily trend now come from
  `ai_property_observations` (eligible rows for the property), using
  `observatory.metrics.metric_from_counts` so mention rate IS AI Visibility
  and citation rate IS Citation Rate (owned-site citations), same keys,
  formula and sample gate as the AI Visibility tab. "Answers citing any
  source" stays as a count (`citation_count`), never as the rate.
  `build_geo_report(..., days=None)` windows every section (both ends) when
  `days` is given; `GET /reports/geo?days=` and the report passes the
  control-bar window. `summary.definition == "observatory"`.
  Reconciliation test: GEO numerators equal the drilldown evidence counts.
- Retired `components/observatory/legacy/AnalysisPanel.tsx` (fact checks
  and recommendations from the pre-Observatory analyzer, superseded by the
  Accuracy tab's claims and the Recommendations tab's content gaps) and
  `RunQueriesPanel.tsx` (one-off query; the Prompts tab runs any prompt
  now). `StandingPanel` (standing-prompt evaluator and score history, used
  by DCHP) stays on Trends.

### Flow P1b: sidebar grouped by stage (2026-09-16)
- `components/Sidebar.tsx` groups now follow the flow: Overview (Dashboard,
  Monthly Briefing), Set up (Properties, Property Context, Data & Uploads),
  Watch (AI Visibility), Understand (Competitor IQ, Content IQ, Review IQ,
  AI Query Signals), Act (Opportunities), Prove (Reports), Assistant, System.
  Each group carries the question it answers as a tooltip (`hint`). Routes
  are unchanged; only order and labels moved.

### Flow P1a: property setup checklist (2026-09-16, 817 tests)
**The first stage of the user flow made visible.**
- `services/setup.py` `property_setup(db, property_id)`: six dependency-ordered
  steps (identity, data, facts, competitors, prompts, monitoring). Each is a
  deterministic check over rows that already exist (Property fields, GA4 and
  GSC rows or a connected Google account, PropertyProfile plus recorded
  attributes and site pages, Competitor rows, prompt assignments or standing
  prompts, eligible observations) and carries `missing`, `optional_hints`,
  `unlocks` and an `href`. Housing authorities are never asked for a single
  pet policy; the hint says per-development facts are not recorded yet.
  `GET /api/properties/{id}/setup`.
- `components/SetupChecklist.tsx`: `SetupChecklist` on the property dashboard
  (full card while incomplete, one line with "Review steps" once complete,
  hidden for sample properties) and `SetupBanner` on the AI Visibility and
  Reports layouts, which names the next step relevant to that surface
  (`requires`) and links to it.
- Deep links: `lib/urlScope.ts` `requestedPropertyId()`; Properties opens the
  editor for `?property_id=`, Uploads, Property Context and Competitors
  preselect it. All read inside fetch callbacks (no set-state-in-effect).
- Tests: `tests/test_property_setup.py` (5).

### Top citation pages with "mentioned on page" + visibility rankings by topic (2026-09-16, 812 tests)
**Two more Profound-style views, both from evidence Beacon holds.**
- `ai_cited_pages` (migration `c8d9e0f1a2b3`): a per-URL cache of fetched
  page text (status ok | unreachable | blocked | not_html, error, title,
  body, `source` fetch | sample). One row per URL, shared across properties;
  the mention check is a `find_mention` text match over the stored body and
  costs no request.
- `services/observatory/citation_pages.py`: `top_citation_pages` groups the
  property's eligible observations' citations by normalized URL (citations,
  answers, share, per-viewer source type) and reports `mentioned_on_page`
  as one of four states. Only a page fetched OK can be "not mentioned"; an
  unfetched page is "unchecked" and a failed fetch is "unreachable" with the
  reason. `check_cited_pages` fetches the most-cited unchecked or stale
  (14 days) pages, `CHECK_BATCH=25` per run, via `content_fetch`; it skips
  sample properties (their listing URLs are fictional paths on real hosts).
  Job `check_cited_pages` runs one batch daily from the startup loop and on
  demand from `POST /api/ai-observatory/citations/pages/check` (idempotent
  per property per day). `GET /citations/pages` reads.
- `services/observatory/topic_rankings.py`: per prompt cluster, ranks the
  property and its tracked competitors by how many of that cluster's
  answers named each (`Mention` rows joined to the property's observations),
  ties share a rank (copied from `competitive_ranking`), `property_rank` is
  null below `MIN_QUERIES_FOR_VISIBILITY`, `needs_work` when sufficient and
  ranked 4th or worse or unranked. Untracked names never enter a ranking.
  `GET /api/ai-observatory/rankings`.
- UI: `components/observatory/RankingPanels.tsx`. `TopCitationPagesPanel`
  on the Sources tab (state chips, table, "Check unchecked pages" button
  disabled at zero) and `TopicRankingsGrid` on the Competitors tab (#1..#10
  columns, property highlighted, "Needs work" and "Small sample" badges).
- Sample Portfolio stocks the page cache with labeled `source="sample"`
  rows (own pages name the property, market directory pages name about
  half, listing pages name it, one blocked) so every state shows without a
  network call; removal deletes only sample rows.
- Tests: `tests/test_obs_citation_pages.py` (10): reconciliation to raw
  citations, unreachable never reads as not mentioned, batch limit and
  failed-fetch storage, successful fetch matched, sample skip, sample
  removal, tie ranks, rankings reconcile to Mention rows, endpoints,
  tracked-only ranking.

### Drilldown everywhere + query fanouts, average position, sentiment reasons (2026-09-16, 802 tests)
**Every number opens the rows behind it.**
- Reports: `ReportMetricCard` takes an optional `drill={propertyId, card, days}`
  and becomes a button; `components/reports/DrilldownDrawer.tsx` fetches
  `GET /api/reports/drilldown?card=` and renders rows plus totals, so 740
  clicks on the card is 740 in the drawer. Wired on Executive, SEO,
  Audience, GEO and Share of Voice cards (the sub-components that render
  cards now call `useReportContext()` for scope and days).
- `services/reporting_drilldown.py`: one registry (`RESOLVERS`) mapping each
  card key to the rows it came from: Search Console by query, GA4 by
  source/medium, city or landing page, Content IQ score components,
  Opportunity Engine actions, AI Visibility via the Observatory evidence.
  An unknown card returns `available: false` with a reason instead of an
  empty list that would imply nothing happened.
  `GET /api/reports/drilldown/cards` lists what can be expanded.
- Observatory: `ObsMetricCard` takes `onDrill`; `EvidenceDrawer` in
  `components/observatory/DrilldownPanels.tsx` reads
  `GET /api/ai-observatory/evidence?metric=` which returns exactly the
  observations in a metric's numerator (`only_counting=false` for the full
  denominator, flagged per row), with the answer text and citations.
  `EVIDENCE_FILTERS` in `drilldown.py` is the single definition of what
  "counts" for each metric, so the drawer and the KPI cannot disagree
  (`test_evidence_matches_the_metric_it_explains`).

**Three Profound-style views the data already supported** (`services/observatory/drilldown.py`):
- Query fanouts (`/fanouts`, Prompts tab): the retrieval searches the
  provider reported per prompt cluster, with count and share. OBSERVED, and
  labeled as what the AI searched, not what people typed; coverage is
  stated because some providers and runs report none.
- Average position (`/position`, Overview): mean `mention_rank` among named
  brands, first-named rate, a 1 to 5+ distribution, per-prompt breakdown,
  previous-window change with lower-is-better. Also folded into
  `/overview` as `position`. Sample-gated at 3 named answers.
- Sentiment reasons (`/sentiment`, Overview): positive share of answers
  that carried any sentiment, neutral share, and the topics attached to
  positive and negative mentions with counts and two quotes each. Built
  from `enrich_text(...)["sentiment_by_topic"]` on the stored excerpt, so
  "positive because of amenities and pets" is a count of answers, not a
  model's summary. MODELED.
- Not built, on purpose: Prompt Volumes (fabricated AI search volume, which
  the spec forbids; the Opportunity Score is the honest stand-in) and
  model-written outreach pitches.

### Semantic Intelligence report + Observatory scale rollups (2026-09-16, 793 tests)
**Semantic Intelligence (the last "planned" Reports tab) is built.**
- Why it was unblocked rather than waiting: it was deferred with Phase 15c,
  whose blocker was SIMILARITY CLUSTERING. This report needs none: it uses
  the fixed 17-topic taxonomy that already tags every RAG chunk. 15c's
  clustering stays honestly deferred, and the report says so in `deferred`.
- `services/reporting_semantic.py` puts four sources side by side per topic:
  site content, reviews (clause sentiment), monitored AI answers, and Search
  Console queries. `GET /api/reports/semantic`, component
  `components/reports/SemanticReport.tsx`.
- Gap types: `demand_gap`, `content_gap`, `mismatch` (site markets what
  reviews dislike), `ai_gap`. A gap is only raised when BOTH compared sources
  exist for the property, so a property with no reviews never produces
  "residents talk about X".
- Two honesty fixes found by looking at real output:
  - A search gap now needs a query genuinely ABOUT the topic (a multi-word
    phrase, or two topic terms). "apartments for rent" contains the pricing
    term "rent" but is generic discovery; it is still counted and shown, it
    just cannot raise a gap. Matching is whole-word, so "coffee" no longer
    hits "fee".
  - `lean` is null when the lexicon matched no sentiment either way. It
    previously said "mixed", which implies both directions were found; plenty
    of real complaints use words the lexicon does not know. `sentiment_detected`
    carries the distinction.

**Observatory scale rollups.** `ai_source_domains`, `ai_run_costs_daily`,
`ai_competitor_stats` (migration b7c8d9e0f1a2, models `ai_rollups.py`,
service `scale_rollups.py`, job `rebuild_scale_rollups`, daily in
`start_observatory_daily`).
- They are a CACHE, not a second opinion: each builder calls the same
  function the live readers call (`source_influence`, `cost_report`, the
  derived observations), so the cache cannot drift into its own arithmetic.
  `tests/test_obs_scale_rollups.py` holds cached == live for all three.
- Readers (`source_influence_cached`, `cost_summary_cached`,
  `competitor_stats`) fall back to computing live when no rollup matches, so
  nothing ever waits on a job having run; `from_rollup` says which path ran.
- New `GET /api/ai-observatory/competitors/standings`: per tracked
  competitor, shared answers, who was named, who was cited, rates null below
  the minimum sample.
- Fixed while testing: rollups survived property deletion. Now pruned by
  `prune_orphans`, by the property-delete cascade, and by sample removal.
- Two test premises of mine were wrong, and the code was right: demo runs
  carry a real configured rate of ZERO, so cost reads MODELED $0.00, not
  UNAVAILABLE.

**Stale copy fixed.** The legacy AI Visibility panel listed competitor share
of voice as not measured; it shipped in Phase 18. Removed from `DEFERRED`.

### Sample Portfolio: first-party data for the Reports tabs (2026-09-16, 775 tests)
- `demo_seed._seed_first_party` adds 90 days per sample property: GA4
  sessions (5 non-AI source/medium splits + 3 AI referral sources classified
  through the real `get_classifier`), GA4 events, Search Console rows,
  Business Profile metrics, ~46 CRM leads walking a lead/tour/application/
  lease funnel, 9 to 14 reviews, and 3 logged content changes. Every row
  hangs off a labeled sample `Upload` so the provenance CHECK constraint is
  satisfied the same way a real import satisfies it.
- Numbers are built to cohere, because a demo that contradicts itself is
  worse than an empty one. Locked in by
  `test_sample_first_party_data_is_coherent_and_local`:
  - GSC queries carry an explicit (impression share, position, CTR) instead
    of deriving clicks from position. Total Search Console clicks now land
    within 0.4x to 1.6x of Google organic sessions; the first draft showed
    5,238 clicks against 892 organic sessions.
  - Visitor cities come from `GEO_BY_STATE` weighted toward the property's
    own metro, so a Texas property no longer draws Denver traffic.
  - AI referral sessions follow the same scripted curve as that property's
    AI visibility, giving the AI + Search panel a real (association-only)
    story.
  - A mild site-wide growth curve (0.86 to 1.14 across the window) so trend
    lines move and before/after comparisons are not uniformly negative. It
    is a site trend, not a lift attributed to any change.
  - Content changes sit 35 to 55 days back so the default 30-day before AND
    after windows both land inside seeded data (they read "partial period"
    otherwise).
  - Brand answers now cite the property's own site ~65% of the time rather
    than always, and name a tracked competitor ~45% of the time. Without the
    latter the property was the only brand named and every legacy Share of
    Voice read a meaningless 100% at rank "#1 of 1"; it now reads 54 to 64%.
- Covered: Executive, Audience, SEO Performance, GEO Visibility, AEO
  Readiness, Content Impact, AI Share of Voice, plus Content IQ, Review IQ
  and the Opportunity Engine. Semantic Intelligence stays "planned /
  deferred" in `/api/reports/meta`: that report is not built, which is a
  product gap, not a data gap, and the tab says so.
- `remove_sample_portfolio` deletes all of it, asserted row-by-row.

### Sample Portfolio + tenant-confined market runs (2026-09-16, 774 tests)
- `services/observatory/demo_seed.py`: `build_sample_portfolio(db)` creates
  organization `sample-portfolio` (settings.sample_data = true), company
  "Sample Portfolio (demo data)", two fictional markets (Lakemont, CO and
  Harbor Bend, TX), eight fictional properties (attributes.sample_data =
  true, amenities, pet_policy, rent_range, Property Context, site pages,
  tracked fictional competitors), prompts and clusters built directly (no
  embedding calls), then 13 weeks of scripted answers pushed through the REAL
  `execute_market_prompt` / `execute_observation` with a `ScriptedSampleProvider`
  (provider "demo", zero cost). Shares are paced exactly (an accumulator, not
  a coin flip) so scripted trends are the trends the rollups show; two
  properties have a late cliff so alerts fire for the intended reason; one
  property is scripted "pet friendly" against a not_allowed policy so
  Accuracy shows a conflict; two untracked names recur so Competitors shows
  candidates. Then gaps and alerts are evaluated. ~290 runs, ~1,070
  observations, under 5 seconds. `remove_sample_portfolio(db)` deletes every
  row (markets only if empty). Rebuild is idempotent.
- Admin: `GET/POST(?confirm=true)/DELETE /api/admin/sample-portfolio`;
  AI Ops panel gains Add / Rebuild / Remove buttons with a confirm dialog;
  `/api/admin/ai-ops` reports `sample_portfolio`.
- UI: Observatory layout shows an amber "Sample data" banner whenever the
  selected property has attributes.sample_data; ScopeSelect suffixes
  "(sample)"; `useObservatory().isSample`.
- Tenant isolation fix (real bug): `derivation.eligible_properties` now
  confines a market run to `run.organization_id` (markets are shared
  geography, so another organization's property in the same city was being
  scored from it). `markets.market_members(organization_id=...)` now uses
  `org_property_ids`, so unassigned properties still count for the default
  organization.
- Per-viewer citation types: `metrics.source_influence` and the citations
  endpoint relabel "owned" relative to the viewing property (another scored
  property's site is `property_site`); a shared answer is classified once
  against every property it scored, which had shown a sibling's site as owned.
- `/api/ai-observatory/costs?property_id=` now scopes to that property's
  organization, so a real organization's usage panel never blends in sample
  runs. `observatory.utc_today()` replaces `date.today()` defaults in
  alerts, costs, content_gaps, impact, portfolio and opportunity_score
  (naive-UTC timestamps vs a local calendar date drifted a day around
  midnight UTC, which a cost test caught).
- Known demo quirk: the Phase 18 Share of Voice dashboard card counts only
  property-owned answers, so a sample property shows "below the visibility
  sample minimum" there while the AI Observatory card beside it is
  populated from shared answers. Not changed: the Phase 18 definition is
  tested as is.

### Phase 19 slice 7: Gemini, Claude, Perplexity connectors, dormant (2026-09-15, 770 tests)
- No keys are configured; nothing calls these providers. A keyed connector is
  live only when its key is set and demo mode is off
  (`reference.connector_configured`, `KEYED_CONNECTORS`):
  `BEACON_GEMINI_API_KEY`, `BEACON_ANTHROPIC_API_KEY`,
  `BEACON_PERPLEXITY_API_KEY`. Models: `BEACON_AI_GEMINI_MODEL`
  (gemini-2.5-flash), `BEACON_AI_CLAUDE_MODEL` (claude-opus-5; change to
  claude-haiku-4-5 for cheaper high-volume monitoring),
  `BEACON_AI_PERPLEXITY_MODEL` (sonar). Pricing entries ship null (cost
  UNAVAILABLE) like the rest.
- `get_ai_visibility_provider(platform)` routes by the platform's connector;
  a connector without its key (or Copilot, which has no API) raises
  PlatformNotConnectedError before any run row is written. The OpenAI
  provider now refuses non-openai platforms.
- `providers_gemini.py` (httpx REST, generateContent + `google_search` tool):
  webSearchQueries -> retrieval queries, groundingChunks -> citations
  (`grounding_chunk`), groundingSupports -> offsets, one search operation per
  grounded prompt. Redirect links (vertexaisearch.cloud.google.com) take the
  chunk title as the source domain in `citations.extract_citations`; the
  redirect URL itself is kept. Ungrounded answers are discarded with spend.
- `providers_anthropic.py` (official `anthropic` SDK, added to
  requirements): `client.beta.messages.create` with `web_search_20260209`
  (max_uses, user_location), `fallbacks="default"` +
  `server-side-fallback-2026-07-01`, resumes `pause_turn` up to 3 times,
  refusal -> ProviderRefusalError (error_class provider_refusal, final).
- `providers_perplexity.py` (httpx REST): search_results (titles) or citations
  -> citations; retrieval queries not exposed, left empty (UNAVAILABLE).
- `classify_error` reads httpx status codes; 429 -> rate_limit (retried).
- Scheduler rotation: `platform_cadence_multiplier` in ai_scheduler.json
  (ChatGPT 1x weekly primary, others 4x as validation). A platform only gets
  schedule rows once live.
- Admin AI Ops lists each platform as connected / needs <KEY> / no API.
  `tests/conftest.py` blanks the new keys for every test.

### Phase 19 slice 6: content gaps, AI + Search impact, portfolio (2026-09-12, 763 tests)
- Migration a6b7c8d9e0f3: `ai_content_gaps` (model `AIContentGap` in
  `app/models/ai_intelligence.py`), unique `gap_key` = property:cluster.
- `content_gaps.evaluate_gaps(db, property_id, days, today)`: per active
  cluster assignment, needs >= 3 answers (cluster rollup), visibility <= 34%,
  and either competitor wins or cited sources. Evidence: absent response ids,
  non-owned cited domains, tracked competitors named. Coverage via Content IQ
  `matched_terms` over PropertyContent title+body with the taxonomy terms;
  target page = best-matching page, else topic -> canonical page map. No
  content -> Insufficient data. Gate: `gate_text` suppression, then
  price/eligibility keywords + unknown/regulated status -> Requires
  confirmation. Gaps that stop qualifying auto-resolve. Daily job
  `create_recommendations` (free) queued by `start_observatory_daily`.
- Opportunity Engine: new source `ai_observatory` ("AI Observatory") from
  `gap_opportunities`, citations `source_ref: ai_observatory: gap=, cluster=`.
  The Opportunities page now renders every card's citations (it previously
  dropped Content IQ and SEO evidence too).
- `impact.impact_summary`: chain AI Visibility (MEASURED) -> generative-AI
  impressions (always UNAVAILABLE, the GSC API does not split them) -> GA4 AI
  referral sessions -> AI key events; a source with no rows in the period is
  UNAVAILABLE with "latest <date>", never zero. Alignment same/opposite/not
  comparable plus a fixed association-not-causation note. `mode` ai_only vs
  ai_plus_search.
- `portfolio.portfolio_summary`: scope via `metrics._resolve_scope`; averages
  only over properties with a value (>= 2 required); shared gaps = topics
  with open gaps on >= 2 properties; top cited domains across the portfolio.
- Endpoints: `GET /recommendations`, `POST /recommendations/evaluate`,
  `POST /recommendations/{id}/status`, `GET /impact`, `GET /portfolio`.
- UI: Recommendations tab `ContentGapsPanel` (missing vs covered terms,
  evidence with labels, Re-check, Mark done, Dismiss); Overview
  `ImpactPanel`; new Portfolio tab (company / unassigned / all).

### Phase 19 slice 5: discovery, claims, alerts, costs, scheduler, AI Ops (2026-09-12, 757 tests)
- Migration f5a6b7c8d9e1: `ai_entity_decisions`, `ai_claims`,
  `ai_visibility_alerts`, `ai_run_schedule`, `ai_schedule_decisions`;
  `ai_discovered_entities` + response_count, evidence_response_ids,
  sample_context. Models in `app/models/ai_intelligence.py`.
- Deviation from the plan (existing contract wins): `Competitor` stays
  operator-named, so `competitors` got NO status column. Discovered names live
  in `ai_discovered_entities`; a per-property `AIEntityDecision` (confirmed |
  ignored) is the only path to a Competitor row. Ignoring is per property.
- `discovery.py`: deterministic Title Case + multifamily-suffix / "X at Y" /
  bold extraction, strips lead verbs ("Try"), rejects generic leads
  ("Luxury Apartments"), domains ("Apartments.com"), continued names ("Sky
  Ridge Medical Center"), names already known in the market. Shown once 2+
  distinct answers name it; confidence MODELED = responses / 5.
- `claims.py`: sentences naming the property -> property_type (Property
  Context + ai_visibility.json synonyms), state (full names), pets
  (`attributes.pet_policy`), amenities (`attributes.amenities`, then site
  content topics = likely_accurate), rent (`attributes.rent_range` {min,max}:
  +/-10% likely_accurate, >25% outside conflict). Absence from a list is
  unable_to_verify, never conflict. Upsert by (property, claim_hash), counts
  occurrences, keeps last 20 response ids; verification recomputed each time.
  Hooked into `execute_observation` (claims + discovery after derivation,
  failures logged, never lose the observation).
- `alerts.py` (thresholds `reference_data/ai_alert_thresholds.json`):
  visibility_drop, citation_lost, competitor_surge over 7-day windows, both
  windows >= 5 responses; claim_conflict per open conflict claim. Dedupe key
  includes window end. `escalate` puts high-severity property schedules on the
  watchlist tier for 21 days.
- `costs.py`: totals/by provider-model/scope/day; cost coverage none ->
  UNAVAILABLE, partial -> "lower bound" note, full -> MODELED; tokens
  OBSERVED; cost per observation MODELED.
- `scheduler.py` (config `reference_data/ai_scheduler.json`): `sync_schedule`
  one row per representative approved prompt x live platform (shared prompts
  only if someone is subscribed); `priority` stores components; `plan_runs`
  reserves budget for queued/leased/running run jobs, logs every decision,
  dry_run mutates nothing. `BEACON_AI_SCHEDULER_ENABLED` defaults OFF;
  `start_observatory_daily` queues `detect_alerts` daily (free) and
  `schedule_ai_runs` only when enabled (after `BEACON_AI_SCHEDULER_HOUR_UTC`).
  Local dry run for DCHP: 32 due prompts would run on day one.
- Jobs: discover_competitors, verify_claims, detect_alerts, schedule_ai_runs.
- Endpoints (`/api/ai-observatory`): competitors/discovered (+ decision,
  discover), claims (+ dismiss, verify), alerts (+ status, detect), costs,
  schedule (+ sync, plan?dry_run=true default, decisions). Admin:
  `GET /api/admin/ai-ops`, `POST /api/admin/jobs/{id}/retry`.
- UI: Competitors tab candidates (Track with optional website / Ignore),
  Accuracy tab claims with status counts and evidence, Overview alerts
  (acknowledge/resolve), Markets tab Monitoring usage + scheduler dry-run
  preview, admin AI Ops panel. `asUtc` in `lib/observatory.ts` renders naive
  UTC timestamps correctly.
- Rollup deletes now `synchronize_session="fetch"` (SQLite id reuse warning);
  new code uses `jobs.queue.utcnow` instead of deprecated `datetime.utcnow`.
- Property delete also removes claims, entity decisions, alerts, schedules.

### Phase 19 slice 4: Observatory UI (2026-09-12, 747 tests)
- `/ai-visibility` is now a tabbed section (`app/ai-visibility/layout.tsx`)
  with `ObservatoryProvider` (`components/observatory/ObservatoryContext.tsx`):
  property in the URL (`?property_id`, last choice remembered in
  localStorage), 7/30/90 day range, metric definitions from
  `GET /api/ai-observatory/meta`. Tabs: Overview (root), prompts, citations,
  competitors, sources, markets, recommendations, accuracy, trends.
- `lib/observatory.ts` holds the types and fetchers; `components/observatory/ui.tsx`
  holds `DataLabelBadge`, `FormulaNote` ("How is this calculated?"),
  `ObsMetricCard` (value + "X of Y" sample + point change, or the
  insufficient-sample state; Share of Voice gating text uses the response
  sample), `ShareBar`, `Panel`, `useLoad`, `LoadState`, `NeedsProperty`.
  New code has no `set-state-in-effect` lint errors (state only set from
  promise callbacks).
- Legacy page moved verbatim into `components/observatory/legacy/`
  (`RunQueriesPanel` on Prompts, `StandingPanel` on Trends, `AnalysisPanel`
  with an `only` section filter on Recommendations and Accuracy); the em
  dashes in its copy were replaced.
- Prompts tab: clusters grouped by scope with importance, variants and
  subscription state; expanding a cluster lists its prompts (representative
  marked), "Run for market" on representative market/feature prompts
  (enqueues `execute_market_run`, idempotent per prompt/platform/day), and
  the Opportunity Score breakdown.
- Opportunity Score is now withheld (score null, UNAVAILABLE) until the
  cluster has monitored answers for the property: importance and search
  demand alone describe a topic, not the property's position.
- Competitors and Accuracy tabs state plainly that AI-discovered
  competitors and per-claim statuses arrive with slice 5; nothing inferred.
- Property dashboard: `AiVisibilityBlock` (AI Visibility + Citation Rate,
  30 days) next to the Share of Voice card.

### Phase 19 slice 3: shared market scoring, metrics, rollups (2026-09-12, 747 tests)
- THE cost lever: a market/feature prompt runs once
  (`observe.execute_market_prompt`, job `execute_market_run`, API
  `POST /api/ai-observatory/prompts/{id}/run` enqueues) and
  `derivation.derive_observations` writes one `ai_property_observations`
  row per eligible property from the stored Mention + AICitation rows. No
  provider re-run, ever. Eligibility: property run -> that property;
  market run -> properties assigned to the prompt's cluster, else every
  active market member. Migration e4f5a6b7c8d0 (5 new tables + 6 plain
  columns on `mentions`).
- Market answers have no owning property, so they never appear in legacy
  per-property readers (property_id NULL on the response). Market mentions
  are detected against every eligible property + their tracked competitors
  (`entities.py`, same whole-word matcher; names of 4 chars or fewer get
  confidence 0.5). Property runs keep the legacy `persist_mentions_for_query`.
- Market runs have no per-property daily cap; the org monthly budget is the
  stop (`RateLimitExceeded` when exhausted).
- `recommendation.py` rule_v1 (MODELED): named among the first 3 entities,
  or a recommendation cue in the SAME sentence as the mention; a negated cue
  in that sentence forces False; None when not mentioned. `sentiment.py`
  (MODELED): semantic-layer clause sentiment in a window around the
  mention, neutral by default.
- Rollups (`rollups.py`): `ai_visibility_daily` (per property x day x
  platform incl "all"), `ai_cluster_visibility_daily`, `ai_market_daily`;
  delete-then-insert per key, dirty keys = observations with
  rolled_up=false, watermark in app_state
  `rollup_watermark_observation_id`, `rebuild_rollups` for a full rebuild.
  Inline after each run for fan-outs of 50 or fewer properties, otherwise an
  `update_property_rollups` job.
- `metrics.py` reads rollups only; every value is {value, numerator,
  denominator, minimum_sample, state, formula, data_label}; formulas in
  `METRIC_DEFINITIONS` (served by `GET /api/ai-observatory/meta`). Share of
  Voice uses the Phase 18 gating exactly (response sample >= 3, null when
  nobody mentioned) and a test asserts it equals `build_sov_report`.
- `opportunity_score.py`: Beacon Prompt Opportunity Score 0-100, MODELED,
  weights in `reference_data/ai_opportunity_weights.json` (overridable),
  contributors competitor_presence / visibility_gap / topic_importance /
  search_demand (GSC impressions on topic terms; UNAVAILABLE without GSC) /
  momentum; unavailable weights are redistributed and listed. Not volume.
- Endpoints (`/api/ai-observatory`): meta, overview, trends, sources,
  citations (paginated, max 200), observations, clusters/{id}/opportunity,
  markets/{id}/summary, prompts/{id}/run, rollups/rebuild.
- Backfill: `python -m app.cli.backfill_observations` (or `--rederive`);
  re-detects mentions for history that has none, then rebuilds rollups.
  `rederive_response` recomputes mentions + observations after alias,
  domain, competitor or subscription edits.
- Property delete also removes its observations, rollups, assignments,
  property clusters, prompt embeddings and its entities' Mention rows inside
  shared market answers.

### Phase 19 slice 2: prompt library + clustering (2026-09-11, 728 tests)
- Prompt scopes on `ai_visibility_prompts`: market | feature | brand |
  sentinel, plus organization_id, market_id, cluster_id, importance (1-5),
  funnel_stage, topic_key, provenance (generated_from JSON,
  generation_method template | manual, approved), repeat_count,
  prompt_hash, is_representative, variant_group. property_id is NULLABLE:
  market/feature prompts belong to a Market and are created ONCE per market
  (`generate_market_prompts`), never per property. Migration d3e4f5a6b7c9
  (batch). Legacy operator prompts backfilled as scope brand.
- Reference data: `ai_topic_taxonomy.json` (28 multifamily topics with
  terms, funnel stage, importance, `core` flag, and a `semantic_topic` link
  to the 17 semantic-layer keys) and `ai_prompt_templates.json` (5 market,
  22 feature, 6 multifamily brand + 5 housing-authority brand templates,
  one competitor-comparison template; each with wording variants).
  Placeholders {city} {state} {name} {competitor}; a template with a missing
  value is never emitted half-filled.
- `services/observatory/prompt_library.py`: `generate_market_prompts`,
  `generate_property_prompts` (brand + up to 3 competitor comparisons +
  the market universe), `property_signal_topics` (attributes, site content
  topics, Search Console queries as a TOPIC signal only - keyword strings
  are never turned into fabricated questions), `upsert_prompt` idempotent
  by (hash, scope, market, property) so re-generation keeps operator edits.
- `clustering.py`: embeddings via the registry provider (deterministic in
  demo/tests), cached in `ai_prompt_embeddings` by text hash + model;
  buckets by (market|property, scope, topic, intent), greedy cosine
  agglomeration in id order (BEACON_AI_CLUSTER_THRESHOLD=0.82), one
  representative per cluster (highest importance, then lowest id),
  `rotate_variant(cluster, period_index)` for wording rotation. Clusters in
  `ai_prompt_clusters` (label, topic, centroid, variant_count).
- `assignments.py`: `subscribe_property` assigns a property to its market's
  market clusters, the feature clusters whose topic it has a signal for or
  that are core, and its own brand clusters (`ai_prompt_assignments`,
  unique assignment_key; losing a signal deactivates the auto assignment).
  `properties_for_cluster` is the fan-out list Phase 3 scores a shared
  market run against.
- API `app/routers/ai_observatory.py` (`/api/ai-observatory`): GET
  taxonomy, markets, markets/{id}, prompts (property_id | market_id,
  scope, include_variants), POST prompts (manual, any scope), PATCH
  prompts/{id} (active, approved, importance, repeat_count, scope,
  topic_key), POST prompts/generate?property_id (generate + cluster +
  subscribe, idempotent), POST prompts/cluster, GET clusters. Jobs
  `generate_market_prompts`, `generate_property_prompts`, `cluster_prompts`.
- Plumbing: scheduled runs now pass prompt_id into the ledger; SoV `_rows`
  joins on prompt_id first and falls back to the text join for older rows.
- No UI yet (Phase 4). Market/feature prompts are not executed yet: the
  scheduler that runs a market prompt once and scores every subscribed
  property is Phase 3/5; today only property-scope standing prompts run.

### Phase 19 slice 1b: foundation - organizations, markets, jobs runner (2026-09-11, 714 tests)
- Tenancy-READY, not multi-tenant: `organizations` (one default row, slug
  "default"; settings JSON reserved for budgets / rotation / white-label),
  `companies.organization_id` (backfilled to the default org; new companies
  join it automatically). `services/observatory/tenancy.py` is the ONLY
  place that resolves property -> company -> organization; a future
  principal plugs in there. No user model, no auth change.
- Geography: `markets` (shared, slug city-state e.g. `lone-tree-co`, created
  automatically from property city/state on create/update) and
  `submarkets`. `properties` gained market_id, submarket_id, address_line1,
  zip, lat, lng, domain (derived from website_url; owned-domain matching),
  attributes JSON (amenities, pet_policy, floor_plans, rent_range, segment;
  operator-asserted), management_company, ownership,
  known_competitor_domains. All optional; PropertyCreate/Update/Out expose
  them. Migration b1c2d3e4f5a7 (batch).
- Content change detection: `property_content.content_hash` (sha256 of the
  whitespace/case-normalized body), hashed_at, topics (semantic topic keys
  from enrich_text), content_changed_at. Refreshed on every content save;
  `changed_topics()` says which topics moved. First hash is not a change.
- Durable jobs: `jobs` table (idempotency_key unique, priority, run_after,
  lease_owner/lease_expires_at, attempts/max_attempts, backoff
  min(30*2^n, 3600)+jitter, dead after max), `app_state` (runner heartbeat
  under key `jobs_runner`), `ai_budgets` (monthly per scope; default org =
  300 runs/month via BEACON_AI_ORG_MONTHLY_RUN_DEFAULT; every run attempt is
  charged, enforcement is Phase 5). Migration c2d3e4f5a6b8.
  `services/jobs/{queue,runner,handlers}.py`; `claim_next` is one
  conditional UPDATE so a job is leased exactly once. Handlers: `noop`,
  `execute_ai_run` (final outcomes like a discarded non-browsing run do NOT
  retry; rate limits / 5xx do). Runner: in-process startup loop
  (BEACON_JOBS_RUNNER, default ON, tick BEACON_JOBS_TICK_SECONDS=15, drains
  in a thread under a lock) or `python -m app.cli.jobs_worker [--loop]`.
- SQLite: `app/db.py` now sets WAL + synchronous=NORMAL + busy_timeout=5000
  on connect (foreign_keys still OFF); admin restore checkpoints the WAL
  before backing up. `properties` DELETE now also clears the AI Visibility
  / Observatory family (queries, runs, citations, search queries, mentions,
  prompts, topics, snapshots, score history, competitors, property budget).
- Local vs hosted: the local dev DB was migrated to head; Render migrates
  itself on deploy (start command). Backups of the local file pre-19 live in
  the session scratchpad only.

### Phase 19 AI Visibility Observatory, slice 1a: provider evidence capture (2026-09-11, 689 tests)
- Plan of record for the whole Observatory (7 phases; markets, shared
  observations, prompt clusters, rollups, competitor discovery, claims,
  scheduler, portfolio intelligence) lives in the approved plan file; this
  slice is the first deployable piece and changes no existing behavior.
- Provider seam: `AIVisibilityQueryProvider.execute()` returns a
  `ProviderResult` (text, provider-reported citations with offsets, retrieval
  queries, usage, model as reported, latency, raw payload). `execute_query`
  stays as a string shim so every existing fake keeps working. Per-platform
  capability flags (`supports_*`) now live in `ai_visibility.json`; a false
  flag means UNAVAILABLE, never synthesized.
- OpenAI capture (`parse_openai_response`): `url_citation` annotations ->
  citations, `web_search_call.action.query/queries` -> retrieval queries,
  `usage` -> tokens (input/output/reasoning/cached), `response.model`/`id`,
  `model_dump()` -> zlib-compressed raw payload. A non-browsing answer still
  raises BrowsingUnavailableError, but the exception now carries `.result`
  so the spend is recorded, and the router returns 409 (was a 500).
- Ledger: new `ai_runs` (every attempt: success | failed | discarded, tokens,
  search_operations, latency, error_class, response_hash,
  duplicate_of_run_id, MODELED estimated_cost + pricing_version), plus
  `ai_citations` (normalized_url, domain, root_domain, source_type via the
  source classifier, capture_method provider_annotation | prose_regex |
  demo) and `ai_search_queries` (OBSERVED provider retrieval queries, never
  consumer volume). `ai_visibility_queries` gained run_id, prompt_id,
  organization_id/market_id (plain ints until 1b), run_scope, provider,
  model, response_hash, normalized_response, raw_provider_payload;
  property_id is now NULLABLE for future market-scoped runs. Legacy rows
  were backfilled (prompt_id by text match, response_hash). Migration
  a9b8c7d6e5f4 (batch mode).
- Pricing: `reference_data/ai_provider_pricing.json` ships with NULL rates
  (Tina's decision), so cost reads UNAVAILABLE until real prices are pasted
  there or into `BEACON_AI_PRICING_OVERRIDES_JSON`. Tokens are recorded
  regardless. Demo provider is priced at zero and returns structured,
  labeled fake citations.
- UI: each stored query on AI Visibility > Run & Queries now expands into a
  labeled evidence block (Provider-reported citations OBSERVED, Observed
  retrieval queries OBSERVED, run line with tokens OBSERVED and cost
  MODELED/UNAVAILABLE). Rows stored before this slice read UNAVAILABLE.
  `GET /api/ai-visibility/meta` returns `capability_keys` and `data_labels`.
- Verified live: one ChatGPT run captured a realtor.com url_citation
  (position 474, classified directory), three retrieval queries, 8494/377
  tokens, and a second attempt that did not browse was stored as
  `discarded` with its 4476 input tokens - spend that was invisible before.
- Next slices: 1b foundation (Organization, Market, jobs table + runner,
  WAL pragmas), 2 prompt library + clustering, 3 shared market scoring +
  metrics + rollups, 4 Observatory UI, 5 discovery/claims/alerts/scheduler,
  6 portfolio + content gaps + Google correlation, 7 Gemini/Claude/Perplexity.

### Phase 18 AI Share of Voice (2026-08-13, 659 tests)
- Mention (per-response entity rows with the alias that matched), AITopic,
  AIShareOfVoiceSnapshot; Property.aliases; prompt filter fields (topic_id,
  audience, persona, location_market, priority, tags). Migrations
  d1e2f3a4b5c6 + f4a5b6c7d8e9.
- `reporting_share_of_voice.py`: Mention-backed SoV (property mentions /
  property + competitor mentions), by platform/topic, topic -> prompt ->
  response drilldown, competitive ranking with explicit ties, winners/
  losers, percentage-POINT comparisons (`reporting.pct_point_change`,
  `compare_points`), portfolio average gated to 2+ sibling properties.
  Reports tab `share-of-voice` + CSV, dashboard `SovKpiCard` (first
  dashboard-to-report link), Nora SoV gate (Supported Diagnosis only when a
  dominant topic contributor is code-verified), RAG chunk `share_of_voice`,
  Opportunity Engine Protect / High Priority buckets on the competitors
  source.

### DCHP question-set import (2026-08-01, 600 tests)
- Tina supplied dchp-beacon-queries.json (12 questions: 4 weekly + 8
  monthly, budget ~$3-5/mo, citation watchlist, must_contain criteria).
  Migration c3e4f5a6b7d8 adds prompt metadata (cadence, runs_per_cycle,
  intent, owning_url, volatile, must_contain JSON, notes, last_run_at).
- Import: POST /api/ai-visibility/{pid}/import-question-set (+ "Import
  question set" button on Standing & Trend). Upserts by prompt TEXT so
  re-importing a revised file updates rather than duplicates. Org
  competitors only (douglasco.gov/chfainfo.com/coloradohousingconnects.org
  -> Competitor rows); hud.gov/ILS domains stay with the source classifier
  (marking them competitor would override the more accurate
  government/directory categories). publichousing.com, lowincomehousing.us,
  apartmentfinder, aplaceformom, after55 added to directory list.
- WEB SEARCH now on visibility runs (settings ai_visibility_web_search +
  ai_visibility_require_search, both default ON): the OpenAI provider
  passes the web_search tool, caps output at 400 tokens, reasoning effort
  low; a response with NO web_search_call raises BrowsingUnavailableError
  and the run is NOT stored (recall-only answers are false misses).
- Cadence scheduler: run_due_prompts() - weeklies due every ~6.5 days,
  monthlies on the 1st and 15th (runs_per_cycle=2) or 1st only; idempotent
  within a day; last_run_at stamped on every run (manual run-all too). The
  autorun loop is now a DAILY tick calling run_due_prompts; still gated
  behind BEACON_AI_VISIBILITY_AUTORUN (OFF). The imported budget design
  assumes scheduled runs - Tina must flip the flag to activate ~33/mo.
- must_contain: deterministic containment at read time (never an LLM
  judge, matching the file's llm_judge:false); evidence drawer now shows
  required_components present/missing + owning_url + volatile.
- NOT implemented from the file (advisory for the operator): service_tier
  flex, per-run cost tracking, alert rules (weekly-miss/answer_current
  flags), source_position. answer_current needs manual judgment.
- Tina decisions pending: flip autorun flag on Render; optionally set
  BEACON_AI_VISIBILITY_MODEL (file wants consumer-mirroring "chat-latest";
  default stays gpt-5-mini until she chooses).


### Visual polish pass (2026-07-18; AMPLIFIED same day)
- v1 was too timid ("I don't see much of a change"). v2: aurora roughly
  doubled (0.20/0.13/0.08, larger radii), hairline brightened
  (0.95/0.8/0.45) + soft violet outer glow on hero cards, and BeaconSweep
  added to the sidebar foot (clipped by its own wrapper, NOT the aside -
  the floating collapse handle must stay un-clipped). Original notes:
- Tina approved 3 of 5 pitched ingredients (mockup artifact:
  claude.ai/code/artifact/20aefc0e-...): aurora wash, gradient hairline,
  beacon sweep. REJECTED: grain texture, gradient text - do not add them.
- Aurora: three low-opacity violet/cyan radial-gradients on body
  (globals.css), background-attachment fixed; print guard strips it
  (client deliverables stay black-on-white).
- .gradient-hairline (doubled selector to beat utility cascade): 1px
  violet-to-cyan border via padding-box/border-box double background.
  Applied to exactly ONE hero card per page: the briefing hero and the
  dashboard Sessions card (MetricCard gained an optional className).
  Keep the one-per-page restraint.
- BeaconSweep (components/BeaconSweep.tsx): decorative radiating-arcs SVG
  (aria-hidden) behind EmptyState and the AccessGate form; parents need
  relative + overflow-hidden.
- No local visual verify possible (Node 18 blocks new Next dev servers);
  the hosted ACCESS GATE shows aurora + sweep publicly, so post-deploy
  screenshot of the gate verifies the pass without the key.


### Data-accuracy audit (2026-07-18, 591 tests)
- Tina asked "make sure all the other numbers are accurate" after the
  conversion-rate catch. Full audit: sync request dimensions -> every
  aggregation -> cross-surface equality.
- VERIFIED CORRECT: CTR (ratio of sums), avg position (impressions-
  weighted), organic filter (lower(medium)=="organic", AI/referral rows
  excluded), GA4 sessions/engaged/keyEvents sums (session-scoped dims,
  exact), events-table user caveat, movers thresholds, landing joins.
- FIXED 1 - GSC anonymized-query undercount now DISCLOSED: the sync pulls
  dimensions [date, query, page]; Google omits some anonymized queries from
  query-level exports, so every GSC total can understate Search Console UI
  totals. New fixed constant GSC_IMPORTED_QUERIES_DISCLOSURE (same posture
  as AI_TRAFFIC_DISCLOSURE) rendered under the SEO summary cards
  (summary.gsc_note) + appended to the four GSC CSV definitions. Proper fix
  (a second date-only totals request stored distinctly) deliberately NOT
  rushed: it would touch ~10 consumers with double-count risk; planned
  follow-up.
- FIXED 2 - Audience "Users" REMOVED: total_users summed across
  date x source x medium x landing x city rows counts the same user many
  times; uniques cannot be derived from stored aggregates, so the number is
  gone from the audience payload, table, and CSV (sessions are exact and
  remain). GA4SessionsDaily.total_users still stored + raw-exported.
- tests/test_data_accuracy.py locks the invariants permanently: ratio-of-
  sums CTR, weighted position, organic exclusions, dashboard == SEO report
  == executive == briefing KPI equality on one seeded window, audience
  sessions == dashboard, no users fields anywhere in the audience payload,
  GSC disclosure present in report + CSV.


### Key-events "conversion rate" honesty fix (2026-07-18, 583 tests)
- Found by Tina in production: the SEO report showed "Organic conversion
  rate 72% - 713 of 984 sessions converting". The numerator is a COUNT of
  GA4 key events (which can fire more than once per session and reflect
  whatever the GA4 property marks as key), not a count of converting
  sessions - the stored aggregates cannot support that claim at all.
- Fix: card relabeled "Organic key events per session", value is a ratio
  (0.72, never a percent), sub-line reads "713 key events across 984
  sessions" with the can-fire-more-than-once note; the generic "sessions
  converting" sample phrasing is gone; landing-pages column is now
  "Events / session" (ratio); CSV definition spells out the semantics.
  16B test now locks label/unit and asserts "converting" never appears.
- Exec report / briefing / prints unaffected (they never used this card).
- Also from today: comparison gate on the hosted SEO report correctly
  refuses May-Jun comparison (prior window predates the Google sync);
  it self-resolves as the rolling window passes the sync start (~early
  August). No change needed - working as designed.


### SEO Performance RAG chunk (2026-07-13, 583 tests)
- Gap found by Tina in production: the briefing's Ask-Nora question about
  striking-distance queries was honestly unanswerable - the SEO quadrant
  computes the query list, but it was never indexed, so Nora could only
  retrieve chunks that MENTION striking distance. Nora refusing to fabricate
  was correct; the handoff wrote checks the index couldn't cash.
- Fix, following the opportunity_engine/competitor summary-chunk pattern:
  `seo_performance_summary_text()` in reporting_seo builds a deterministic
  bounded summary (top 15 striking-distance queries BY NAME with position/
  impressions/clicks, low-CTR queries, top movers, honest scope note);
  `_seo_performance_chunks` in the chunker indexes it (source
  "seo_performance", one chunk per property, absent without query data).
- Freshness: the GA4 and GSC widen lists in rag_sync_service now include
  seo_performance, so the chunk rebuilds whenever query data syncs. On the
  hosted instance the next daily Google autosync builds it automatically
  (or Rebuild RAG Index on /admin does it immediately).
- End-to-end test proves the briefing's exact question retrieves the chunk
  naming the queries through the hybrid retriever, citation resolving to
  seo_performance.


### Phase 17E — Auto-snapshot + printable briefing (2026-07-13, 578 tests)
- **Month-end auto-snapshot**: `autosnapshot_closed_months()` in
  reporting_briefing + a daily startup loop in main.py (same pattern as the
  Google autosync). For each ACTIVE property: if the PREVIOUS calendar month
  has GA4/GSC data but no snapshot, compose + freeze one
  (generated_by="autosnapshot"). Manual saves always win (existing rows are
  never overwritten); months with no data are skipped, never frozen empty;
  idempotent; January correctly rolls to December. Flag
  BEACON_BRIEFING_AUTOSNAPSHOT defaults ON (deterministic + zero API cost,
  unlike the AI Visibility autorun which stays OFF).
- **Print-friendly briefing**: /briefing/print?property_id=&year=&month=
  reuses the 16C .print-doc pattern (black-on-white, auto window.print, "Save
  as PDF" = real client deliverable): health table, cited summary, KPIs,
  story, cross-system insights, priorities, questions, methodology note
  restating the no-composite-score and co-occurrence-not-causation rules.
  "Print / PDF" button next to Save snapshot on /briefing.
- Reports History now fills itself: the flagship is a monthly artifact
  without anyone remembering to click Save.


### Phase 17D — Strategist synthesis + tokenized Share (2026-07-13, 571 tests)
- **If I Were Your Strategist** (`app/services/strategist.py`): the briefing's
  one sanctioned LLM step, held to Nora's discipline. The model sees ONLY
  numbered deterministic facts from the composed briefing; grounding is
  enforced IN CODE (a rec citing no valid fact is dropped; citations are
  assembled from OUR fact list, never trusted from output); below
  MIN_FACTS_FOR_SYNTHESIS a fixed template returns and the LLM is NEVER
  called; demo mode is deterministic (templates the top priorities); no key
  -> honest unavailable. MANUAL button only (spends OpenAI budget). Endpoint:
  POST /api/briefing/strategist. Verified end-to-end with a real OpenAI call:
  grounded recs each citing Fact N with source links.
- **Share** (migration `b2d3f4a5c6e7`: share_token on monthly_briefings):
  POST /api/briefing/{id}/share mints/rotates an unguessable token (rotation
  kills old links), DELETE revokes. GET /api/briefing/shared/{token} is the
  ONE new key-exempt route (GET only; share/revoke stay keyed) - declared
  BEFORE /{briefing_id} (path ordering). Public page
  /shared/briefing/[token]: bare layout (AccessGate + AppShell bypass
  /shared/*), "Shared read-only report" badge, Ask Nora hidden via
  SharedModeContext. Payload = frozen snapshot verbatim (client-safe,
  test-proven keyless-while-rest-stays-keyed).
- Browser-verified end to end this time (ports were free): populated
  briefing, live strategist generation, snapshot save, share mint, public
  page render. NB: only Node 18 is installed; newer Next hard-blocks it for
  NEW dev servers (a stale dev process can outlive this - kill with
  pattern "next dev --port", the cmdline normalizes -p to --port).
- Phase 17 (Monthly Strategic Briefing) is COMPLETE per the agreed scope.
  Still deferred: forecast (needs real history), semantic clustering (15c).


### Phase 17C — Cross-System Insights + Strategic Questions (2026-07-13, 560 tests)
- `_cross_system()`: the signature feature built the careful way. An insight
  is either (a) co-movement: story wins/risks from 2+ DISTINCT modules in the
  same month (one observation per module), or (b) a corroborated action: an
  Opportunity Engine top action with supporting_signal_count >= 2 AND 2+
  source modules. Fixed framing: "Co-occurrence is not causation" - no
  arrows, no causal chains, ever. Capped at 4; honest empty_reason.
- `_strategic_questions()`: the briefing ends with questions, not
  conclusions. Each question is generated ONLY when its detectable
  precondition holds: clicks-up-while-key-events-flat tension,
  striking-distance count, top declining query, AI-sample-gate-with-
  measurable-demand, top review complaint theme vs website coverage. Each
  carries why + evidence + module link + a nora_question for the Ask Nora
  handoff. Capped at 5.
- DCHP live: 3 corroborated-action insights (Content IQ + SEO Performance
  agreeing on maintenance/recertification content + striking-distance) and
  2 real precondition-generated questions.
- Frontend: CrossSystemSection + QuestionsSection (each question launches
  Nora with its context). Snapshots freeze both (test-proven).
- Remaining: 17D (grounded "If I Were Your Strategist" via Nora + Share
  security design). Forecast still deferred until real history exists.


### Phase 17B — This Month's Story + Intelligence Cards + Ask Nora (2026-07-13, 550 tests)
- `_story()` in reporting_briefing: deterministic wins/risks/trends from
  exec-card movements, SEO movers (NB: the movers key is `losses`, not
  `declines` - a real bug the tests caught), review trend metrics/complaint
  themes, and AI visibility score history. Every item carries evidence + a
  module link; groups cap at 5; no causal verbs (note disclaims causation);
  a month without comparable coverage yields honestly EMPTY groups (the 16A
  comparability gate refuses sparse months - test fixtures must cover day 1
  through within the 14-day manual tolerance of month end to compare).
- `_intel_cards()`: per-module what-happened + biggest-opportunity cards
  (seo/ai_visibility/content/reviews) with honest ok/no_data/not_connected
  states; content card carries Content IQ's top recommendation.
- Ask Nora handoff: briefing sections link to `/nora?property_id=&q=` with a
  section-aware question; the Nora page prefills question + property from
  window.location.search on mount (no Suspense needed, no backend change).
- Snapshots freeze story + cards along with everything else (test-proven).
- DCHP live: story groups empty (honest - no comparable prior month locally),
  cards populated. Same browser-verify caveat as 17A (other session's dev
  servers hold the default ports).


### Phase 17A — Monthly Strategic Briefing foundation (2026-07-13, 541 tests)
- Phase 17 = Tina's approved "Monthly Strategic Briefing" flagship, with the
  agreed cuts: NO opaque composite health score (per-module explainable
  statuses + a modules-healthy COUNT), forecast DEFERRED until real history,
  cross-system causal chains and strategist synthesis pushed to 17C/17D built
  carefully. Remaining: 17B (This Month's Story wins/risks/trends +
  Intelligence Cards + per-section Ask Nora), 17C (cross-system insights as
  co-occurrence-with-evidence, never causation), 17D (grounded "If I Were
  Your Strategist" via Nora + Share security design).
- **/briefing** nav flagship (top of Overview). Frozen snapshots: migration
  `a1c2e3f4b5d6` adds `monthly_briefings`; POST /api/briefing/generate
  upserts one snapshot per property+month (test proves later data does NOT
  change a frozen snapshot); GET /api/briefing/history + /api/briefing/{id}.
- Calendar-month windows threaded through the REUSED engines:
  `build_seo_report`/`build_executive_report` accept optional
  window/prev_window overrides (internals already took tuples). Default
  briefing month anchors to the newest GSC month (the laggard source), not a
  partial current month.
- `app/services/reporting_briefing.py` composes exec report + Review IQ +
  source_status into: hero, per-module health (seo/ai_visibility/content/
  reviews/website; each with band rule + one-sentence reason + details link;
  not_connected / not_enough_data are EXCLUDED from the assessable count,
  never banded as 0), executive summary (existing cited narrative), KPI
  snapshot, top-5 priorities, adaptive connect-me cards (CRM/competitors).
- Verify caveat: backend verified over live HTTP + nav/page shell rendered;
  populated-body screenshot blocked by another session's dev servers sharing
  .next on the default ports (infra collision, not a code issue).


### Phase 16I — GA4 city/region in the live sync + events breakdown (2026-07-13, 524 tests)
- **City/region now flow from the live GA4 sync**: `gapi.ga4_run_report` now
  requests `city` + `region` dimensions (normalized via `_geo_value`, "(not
  set)" -> NULL) and `_write_ga4` writes them. The Audience report was already
  built (Phase 16G) but only the CSV path carried geography; the auto-sync never
  requested it, which is why DCHP showed "no location data." After deploy + one
  re-sync, cities populate. NB: adding city multiplies row cardinality
  (city x source x medium x landing x date); the single-request 100k row cap is
  unchanged, fine at Beacon's single-property scale but a known ceiling.
- **GA4 events are a new data type**: `ga4_events_daily` (migration
  e2f3a4b5c6d7) stores event-name counts. Two ingest paths: the live GA4 sync
  runs a second report (`gapi.ga4_events_report`, dims date+eventName) written
  by `_write_ga4_events` under the same sync job; and a CSV import
  (`POST /api/uploads/ga4_events`, `ingestion/ga4_events.py`). The events export
  is usually range-aggregated with no Date column, so the parser falls back to
  the `# Start/End date` preamble and stamps all rows at the range end date
  (disclosed in a warning); a Date column is used when present.
- **Surfaced on Dashboard + SEO report**: `reporting_events.build_events_section`
  (shared) aggregates by event name over the window. Event count is exact and
  additive; user counts sum active-users-per-day and can exceed uniques, stated
  in `note`. `build_dashboard` gets an `events` section (local import to dodge a
  cycle) and `build_seo_report` gets `events`. Frontend `EventsPanel.tsx` renders
  on both; Uploads page gains a "GA4 events" source.
- Frontend unverified in-browser (Node 18 < Next 20.9); types pass, backend
  verified live via curl.

### Phase 16H — Google Business Profile reviews (2026-07-13, 516 tests)
- **Manual review import (works today, no external dependency)**: tolerant CSV
  parser `ingestion/reviews.py` + `POST /api/reviews/{property_id}/import`
  (Form `provider`, default "google"). Upserts by (provider, external_review_id)
  so re-imports update, not duplicate; skips rows with no review text; parses
  numeric/worded/glyph ratings. Triggers one "reviews" RAG sync for the batch.
  Frontend: `components/ReviewImport.tsx` on the Review Intelligence page.
- **Live GBP connector (flag-gated, ready but dark)**: `google_gbp_enabled`
  (env `BEACON_GOOGLE_GBP_ENABLED`, default False). When off, NOTHING about the
  live GA4/GSC flow changes - this is deliberate: the GBP reviews API is
  access-restricted (Google must allowlist the Cloud project) and needs the
  restricted `business.manage` scope, which would break the shared consent
  screen if added before approval. When on: the scope joins `current_scopes()`,
  GBP joins `_google_sources()` (so `/google/callback` provisions a GBP
  connection and `/google/status` returns `gbp_enabled`), `list_resources`
  lists GBP locations, and `run_google_sync` pulls reviews via new
  `gapi.list_gbp_locations` / `gapi.gbp_reviews` (v4 reviews API; starRating +
  reviewReply + createTime normalized) and upserts PropertyReview rows through
  the SAME `upsert_reviews` the manual import uses. No schema migration:
  PropertyReview / DataConnection / SyncJob already existed and GBP was already
  a SourceType. `GoogleConnections.tsx` labels GBP and reports "N reviews" (no
  date range) on sync.
- **To go live**: (1) request Business Profile API access for the Cloud project
  and get it allowlisted; (2) add the `business.manage` scope to the OAuth
  consent screen; (3) set `BEACON_GOOGLE_GBP_ENABLED=true`; (4) reconnect Google
  on Uploads, pick the location, Sync now.
- NOTE: frontend unverified in-browser (local Node 18 < Next's 20.9); types pass
  and the import API was verified live via curl.

### Phase 16G — Audience geography report (2026-07-13, 509 tests)
- **Schema**: `c1a2d3e4f5b6_ga4_city_region.py` adds nullable `city` / `region`
  to `ga4_sessions_daily` (+ `ix_ga4_property_city`). Both nullable because
  historical uploads never carried the dimension and GA4 emits "(not set)" when
  it cannot resolve a location. NB: the local `beacon-backend` launch command
  runs uvicorn directly and does NOT `alembic upgrade` first (only the Render
  start command does) - run `alembic upgrade head` by hand after pulling.
- **Parser** (`ingestion/ga4.py`): recognizes GA4 City / Region dimensions,
  normalizes "(not set)"/"(not provided)"/"(other)" to NULL (`_geo`), and adds
  city+region to the event-collapse grouping key so distinct locations are not
  merged. Fully tolerant of exports without geography (all existing fixtures
  still parse).
- **Report** (`app/services/reporting_audience.py`, `GET /api/reports/audience`):
  sessions/users by city and region over a scoped, latest-data-anchored window,
  with the AI-referral split reusing the stored `is_ai_referral` fact. Valid at
  every scope (property/company/unassigned/portfolio). Sessions GA4 could not
  place collapse into a single "Unknown" bucket and the report always states the
  located share. When GA4 rows exist but none carry a city, `geography_available`
  is false with a "re-export with the City dimension" message rather than an
  empty map. Every AI figure carries `AI_TRAFFIC_DISCLOSURE`. `aggregate_geography`
  is shared with the Executive report's `top_cities` panel (per-property, its own
  window). CSV export `GET /api/reports/audience/export.csv` (self-describing,
  full city list). Audience tab -> available, inserted after Executive.
- **Frontend**: `components/reports/AudienceReport.tsx` (summary tiles, city
  table with share bars + engagement + AI, region rollup, geography/undercount
  notes), `app/reports/audience/page.tsx`, and a `TopCitiesPanel` on the
  Executive report. ExportMenu/ReportControls know the `audience` section.
  NOTE: unverified in-browser - local Node is 18 and Next needs >=20.9, so the
  frontend dev server would not start; types pass `tsc --noEmit` and the API was
  verified live via curl (property + upload + all endpoints).

### Phase 16F — Content Impact + RAG Index Health (2026-07-12, 500 tests)
- **First Phase-16 migration**: `f3b1c2d4e5a6_content_changes.py` creates the
  `content_changes` table (plain create_table; batch mode is only for ALTER).
  New model `app/models/content_change.py` (ChangeType enum). Registered in
  `models/__init__.py` and the `test_phase1_schema.py` expected-tables set.
- **Content change log CRUD**: `app/routers/content_changes.py` ->
  `/api/content-changes/{property_id}` (GET/POST/PUT/DELETE). Operator-recorded
  website changes; company_id auto-denormalized from the property. Change
  scoped to its property (cross-property update/delete 404s).
- **Content Impact report** (`app/services/reporting_content_impact.py`,
  `GET /api/reports/content-impact`): per change, compares equal windows
  (14/30/60 days) before vs after the change date over GSC clicks/impressions/
  CTR/position and GA4-organic sessions/key-events. This is OBSERVATIONAL, not
  causal: the fixed `EXTERNAL_FACTORS_CAVEAT` ("...Beacon does not claim the
  content change caused the result.") rides on the report and every change; no
  causal narrative is generated. An after-window that has not fully elapsed is
  disclosed ("still accumulating N/M days") and its after value is null, never
  0. Missing before-window data shows n/a, not 0. CSV export + timeline for
  annotating other charts. Content Impact tab -> available (5 of 6 report tabs
  now live; only Semantic Intelligence deferred with 15c).
- **RAG Index Health** (`GET /api/admin/rag-health`, admin-only): registry/
  vector parity, orphans (both directions), duplicate content hashes, stale
  pre-enrichment chunks, properties with content not indexed, configured
  sources not indexed, embedding model + index version, failed/queued jobs.
  Resilient to an unconfigured embedder (never 500s the panel). Rendered as a
  new panel on `/admin`. Live it correctly flags the local drift (4 vectors vs
  10 registry rows) — exactly what it is for.
- **Retrieval transparency polish**: `/api/admin/retrieval-debug` now also
  returns `retrieval_latency_ms`, `index_version`, `embedding_model`. Stays
  admin-only and is never in any client report/export.
- Role note (unchanged from the plan): Beacon has no user accounts, so
  "administrator-only" = the `/admin` surface, and "client-facing exclusion" =
  the report CSV/print exports (which never carry chunk ids, vectors,
  similarity, latency; test-enforced across every CSV).

### Phase 16E — AEO Readiness report (2026-07-12, 487 tests)
- `GET /api/reports/aeo` (`app/services/reporting_aeo.py`), per-property,
  reuses Content IQ's `_question_coverage` and `_freshness` (no recompute):
  - Explainable weighted score. Seven deterministic components
    (question_coverage .30, answer_completeness .20, specificity .15,
    local_relevance .10, discoverability .10, freshness .05,
    citation_readiness .10). Each publishes weight, rule, raw 0-100 value,
    evidence, source pages, explanation. A component with NO signal
    (freshness with no dates, etc.) is EXCLUDED and its weight renormalized
    away, never scored as 0. No opaque model number.
  - Question coverage heatmap: rows = renter questions (property-type aware),
    cols = ingested pages. Cell state by deterministic term match only
    (fully_answered = concept+detail on the page, partially = concept only,
    mentioned_only = stray detail, missing = neither); stale-page overlay
    from freshness. Every cell carries its matched_terms (inspectable). NOT
    vector-driven.
  - Citation readiness: per-page signals (clear heading, specific answer,
    named property, updated date, crawlable text >=200 chars), averaged, with
    the FIXED disclaimer "Citation readiness does not guarantee that an AI
    platform will cite the page." (also at report root).
  - Structured data: NOT ingested. Contract + UI empty state built behind
    `STRUCTURED_DATA_ENABLED=False`; reports not_configured, never fabricates.
- CSV `GET /api/reports/aeo/export.csv` (client-safe: score, components,
  heatmap-per-page, citation readiness + disclaimer). AEO tab -> available.
- Frontend `components/reports/AeoReport.tsx`: score dial + expandable
  component rows (rule/evidence/pages on click), heatmap with glyph+color+
  legend + stale dot + click-to-inspect matched terms, citation-readiness
  signal table, structured-data empty state.
- Verified live on DCHP: 85/A, all 7 components scored, 16-question x 2-page
  heatmap (13 answered / 1 partial / 2 missing), citation readiness 100,
  structured data not_configured, cell evidence showing matched terms.
- Scope: per-property (portfolio -> scope_required). The spec's broader
  Semantic Intelligence / cross-source-gap pieces remain deferred with 15c.

### Phase 16D — GEO Visibility report (2026-07-12, 472 tests)
- `GET /api/reports/geo` (`app/services/reporting_geo.py`), per-property,
  reads ONLY stored AIVisibilityQuery rows (never calls a platform):
  - Summary: queries completed, platforms tested, mention count, citation
    count, mention/citation rate (each carries numerator+denominator, withheld
    below the 3-query `MIN_QUERIES_FOR_VISIBILITY` gate as insufficient, never
    0), owned-domain citations, competitor appearances, AI referral sessions
    (GA4). These are DISTINCT metrics, never fused.
  - Sufficiency panel: completed vs minimum, failed=0/not-run=0 stated
    explicitly (Beacon stores only completed runs), date span, platforms.
  - Prompt visibility matrix: rows = distinct prompts, cols = platforms, most
    recent run per (prompt, platform). Cell states property_cited /
    property_mentioned / property_and_competitor / competitor_mentioned /
    not_present / not_tested. Click a cell -> `GET /api/reports/geo/evidence`
    (`matrix_cell_evidence`) returns the stored response excerpt, cited
    domains, owned-domains-cited, detected competitors. Cross-property query
    ids are rejected.
  - Source landscape: each cited domain classified by the new deterministic
    `app/services/source_classifier.py` (+ `reference_data/source_categories.json`):
    owned (property website) and competitor (configured competitor domains)
    take precedence, then government (.gov/.mil + list), directory, review
    platform, media; anything else stays UNKNOWN (never guessed). Host match
    is exact-or-subdomain so lookalikes don't match.
  - Competitor share: reuses `analyze_share_of_voice`, labeled
    "Share of tested AI answers" (NEVER market share; test-enforced in CSV
    too). Alias-aware, operator-configured only.
  - Trends: from `ai_visibility_score_history`; null score points below the
    sample gate shown as gaps.
- CSV: `GET /api/reports/geo/export.csv` (client-safe, rates as
  value+num/denom, "Share of tested AI answers" label). GEO tab -> available.
- Frontend `components/reports/GeoReport.tsx`: matrix with glyph+color+legend
  (color never the only signal), slide-in evidence drawer, source-landscape
  bars colored by category, competitor share bars. Export menu handles "geo".
- Semantic explanation layer (RAG-per-query readiness) from the 16D spec was
  NOT built: it needs live OpenAI embeddings (untestable offline) and is
  lower-value than the deterministic core. Deferred, documented here.
- Local DCHP has 1 AI Visibility query, so the report correctly shows the
  sufficiency gate + insufficient rates; verified live including the evidence
  drawer (real ChatGPT Section 8 response) and .gov -> Government classification.

### Phase 16C — Executive report + CSV + print (2026-07-12, 455 tests)
- `GET /api/reports/executive` (`app/services/reporting_executive.py`):
  per-property synthesis that COMPOSES other modules, never recomputes.
  Cards: organic clicks/impressions/sessions/key-events (from the SEO
  report's own summary cards), AI referral sessions + AI share (direct GA4
  query over the SEO report's exact window, so every metric shares one
  period), AI mention rate (AI Visibility, sample-gated), Content IQ score,
  actionable-opportunity count. AEO/semantic cards render an honest
  "arrives with a later phase" not_configured state, never zero.
- Deterministic cited narrative (`_narrative`): sentences for largest
  NONZERO movement, strongest SEO signal, GEO (sample-gated), and the top
  opportunity. Each carries evidence + a link to the source page. No LLM, no
  causal verbs (test-enforced list), no em dashes, and it omits any sentence
  it cannot support. Portfolio/company scope returns scope_required instead
  of blending properties.
- CSV export (`reporting_csv.py`): `GET /api/reports/{seo,executive}/export.csv`
  — self-describing (metric definitions, source, freshness, sample,
  data-status note), missing values written as the state name not 0, and
  client-safe by construction (test asserts no chunk/vector/similarity/
  latency strings). Separate from the existing raw-data ZIP export
  (`/api/export`).
- Print layout: `/reports/executive/print` is a standalone route (the
  reports layout bypasses its chrome when the path ends in `/print`) that
  fetches by URL params and auto-calls window.print(); `@media print` in
  globals.css hides the sidebar and renders a black-on-white document with
  branding, cited summary, metrics table, top actions, methodology +
  no-causation note, and footer. This is the PDF path for now; server-side
  PDF deferred (documented, not faked). Export menu (`ExportMenu.tsx`)
  replaces the old disabled button: CSV download + Print, section derived
  from the route.
- Executive + SEO tabs both `status: "available"` in the meta. Bug caught
  during live verification and fixed: the AI-referral previous period was a
  doubled-window total compared against itself, producing a bogus
  "decreased 0.0 percent from 28 to 28" sentence; now uses the adjacent
  previous window and flat movements are suppressed from the narrative.

### Phase 16B — SEO Performance report (2026-07-12, 435 tests)
- `GET /api/reports/seo` (`app/services/reporting_seo.py`): summary cards
  (GSC clicks/impressions/CTR/position + GA4-organic sessions/engaged/key
  events/conversion rate; organic = session_medium == "organic"), daily
  trends (gaps stay gaps, never zero-filled), ranking distribution (buckets
  1-3/4-10/11-20/21-50/51+, labeled "imported queries, not a rank tracker"),
  opportunity quadrant (deterministic flags with published rules; branded =
  property name/slug/two-word-name-prefix substring), gains/losses (floors:
  10 impressions, 3 clicks or 1.0 position change), landing-page join via
  the existing `_norm_path` from ai_query_signals (matched/ga4_only/gsc_only
  counts, unmatched sides are null). Query categorization reuses
  `semantic.enrichment.enrich_text` (shared taxonomy, no new dictionary).
- Comparisons refuse to render when previous-window coverage is incompatible
  (reporting.comparable) — amber warning instead of a fake percentage.
  Verified live: DCHP's previous period predates its data, so compare mode
  shows the warning. All caps report dropped-row counts (no silent caps).
- Opportunity Engine gained a sixth source: "seo" (SOURCE_LABELS +
  lazy-imported `seo_recommendations` in build_opportunities; findings need
  3+ affected queries). Existing corroboration/gating/ranking applies.
- Frontend: `components/reports/SeoReport.tsx` + `SeoCharts.tsx` (Recharts
  metric-selectable trend chart with reversed axis for position; scatter
  quadrant, bubble=clicks, click-to-inspect drawer). SEO tab meta flipped to
  "available". Fixtures `gsc_queries.csv` / `ga4_organic_landing.csv` cover
  two 14-day windows for comparison tests.
- Local DCHP note: its 678 GSC rows are a query-level snapshot without a
  page column, so Landing Pages honestly shows "no page-level rows" locally;
  the hosted instance's daily Google sync stores date+query+page and will
  populate it.

### Phase 16A — Reports foundation (2026-07-12, 418 tests)
- Phase 16 = Tina's approved "Reporting, Visual Intelligence" spec (she called
  it Phase 12; renumbered since 15b was already done). Approved order:
  16A foundation → 16B SEO report → 16C executive+print/CSV → 16D GEO →
  16E AEO/question coverage → 16F RAG-health polish + content change log.
  Semantic clustering pieces deferred with 15c (not enough data volume).
  Role-gating reinterpreted as export hygiene (Beacon has no user accounts).
- **Reports** nav entry under Overview; `/reports/{executive,seo,geo,aeo,
  semantic,content-impact}` route tabs, all honest placeholders (tab metadata
  served by `GET /api/reports/meta`, flip `status` to "available" per phase).
- `app/services/reporting.py`: DataState enum (8 states — missing data is a
  named state, NEVER zero), `previous_window`, `compare`/`pct_change` (null on
  missing/zero baseline), `rate` (always carries numerator/denominator,
  insufficient-sample gate), `coverage_state` (complete/delayed/partial rules),
  `comparable` (incompatible-coverage warning), `source_status` (per-source
  freshness, scope-isolated via metrics.py `_resolve_scope`).
- `GET /api/reports/status` powers the control-bar Data status chip + the
  Executive tab source panel. Router is `app/routers/reports_v2.py` (named to
  avoid colliding with the existing generated-report model).
- Frontend shared kit in `components/reports/`: ReportContext (scope synced
  with SCOPE_STORAGE_KEY, 7/30/90 days, compare toggle), ReportControls,
  DataStates (StateBadge/SampleBadge/SourceBadge/FreshnessFooter/Empty/Error),
  ReportMetricCard (comparison-aware, state-aware), PlannedReport.
- Export button is a disabled placeholder until 16C. No em dashes in any new
  user-facing copy (tests assert this).
- **Admin self-check**: `GET /api/admin/healthcheck` — ok/warn/fail per item
  (DB, search-index parity between Chroma and the `rag_chunks` registry,
  providers, RAG sync queue depth, Google-connection freshness <48h, disk
  space). Rendered as a panel on `/admin`.
- **Dashboard stale banner**: amber banner on a property's dashboard if its
  Google sync hasn't succeeded in 48h+.
- **AI Visibility standing prompts + scheduling**: `ai_visibility_prompts` +
  `ai_visibility_score_history` tables. Save a reusable prompt set (type-aware
  suggestions in `ai_visibility_prompt_suggestions.json`, e.g. housing-authority
  vs multifamily language), run them all with one click or on a weekly
  schedule (`BEACON_AI_VISIBILITY_AUTORUN`, **currently OFF** — costs OpenAI
  budget, Tina said leave it manual for now), and watch a score trend build in
  the new "Standing & Trend" tab on `/ai-visibility`. Score points below the
  3-query minimum are stored as `null` (honest), never fabricated.
- Service: `app/services/ai_visibility/schedule.py`. Router additions on
  `app/routers/ai_visibility.py` (registered BEFORE the
  `/{property_id}/{query_id}` catch-all — path ordering matters here).

### Google GA4 + Search Console auto-sync (2026-07-12)
- OAuth connect flow implemented directly over httpx (no Google SDK).
  `app/services/google_sync/` — `oauth.py` (HMAC-signed state, 15-min TTL),
  `gapi.py` (GA4 Data API `runReport` incl. `landingPagePlusQueryString` so AI
  Query Signals can join to GSC pages; Search Console `searchAnalytics.query`),
  `sync.py` (replace-on-overlap by date window, `sync_job_id` provenance,
  reuses the same AI-referral classifier as CSV uploads, triggers RAG sync).
- `data_connections` table extended with `property_id`, `refresh_token`,
  `resource_id`, `resource_name` (migration `d0e1f2a3b4c5`, batch mode — see
  gotcha above).
- `/api/google/callback` is the ONE endpoint exempt from the access-key
  middleware (protected by the signed state instead).
- Frontend: `components/GoogleConnections.tsx` on the Uploads page — Connect,
  pick GA4 property / GSC site, Sync now, Disconnect (keeps already-synced
  data).
- **Google Cloud project is Tina's**, in Testing/External OAuth consent mode
  with her own email added as a test user (100-user cap, no verification
  needed for personal use). Three APIs enabled: Analytics Data API, Analytics
  Admin API, Search Console API. If a NEW Google API 403s with "has not been
  used in project X", the fix is always: open the exact URL in the error,
  Enable, wait 2-5 min for propagation, retry — this is normal and not a bug.
- Daily autosync loop in `app/main.py` startup, gated by
  `BEACON_GOOGLE_AUTOSYNC` (currently **ON** in render.yaml).

### DB restore endpoint (2026-07-12, one-time migration tool)
- `POST /api/admin/restore-db` (multipart file upload) — validates the
  uploaded SQLite file is a real Beacon DB at the current schema head, backs
  up the live DB with a timestamp, swaps atomically, rebuilds the RAG index.
  Used ONCE already to copy Tina's local DCHP data (194 GA4 rows, 678 GSC
  rows, content, Nora history) up to the empty hosted Render DB. Don't run it
  again casually — check which direction data should flow.

### Render deployment (2026-07-12)
- `render.yaml` blueprint, `BEACON_ACCESS_KEY` shared-key middleware +
  `components/AccessGate.tsx`, `.gitignore` fixed (repo had an embedded
  `frontend/.git` from create-next-app that would have silently excluded all
  frontend files from commits — already fixed, don't recreate it).

### Phase 15b — Hybrid retrieval (2026-07-12)
- Vector search proposes a candidate pool; deterministic reranker scores on
  semantic similarity (`1/(1+distance)`, NOT `1-distance` — Chroma's default
  L2 space means distances exceed 1, so `1-d` collapses to 0; this was a real
  bug caught during live verification), keyword overlap, phrase match
  (stopword-filtered bigrams both sides), topic overlap (from 15a enrichment),
  entity overlap, and data-relative recency (anchored to the newest candidate,
  never wall-clock). Weights in `rag_retrieval.json`. Dev-only debug view:
  `GET /api/admin/retrieval-debug`.

### Phase 15a — Semantic Intelligence (2026-07-08)
- Shared `app/services/semantic/` enrichment layer: topics, entities, intents,
  clause-scoped per-topic sentiment, normalized terms — all deterministic, no
  model calls, every assertion carries a `matched_rules` explanation (rejected
  the original spec's fabricated `confidence: 0.97` field on principle).
- Negation rules (conservative — miss some, never invent): "not very clean" →
  complaint; "did not have a maintenance issue" → not a mention; "no
  maintenance issues" excluded but "no parking" stays a complaint; "never
  fixed my broken heater" stays a complaint (plain cues never cancel negative
  terms). Fixed the Phase 11 Review Intelligence literal-matching limitation.
- Stamped on every RAG chunk (`rag_chunks.enrichment` JSON + Chroma metadata
  `topic_<key>` booleans) at index time.

### Property client/site type (2026-07-06/07)
- `Property.property_type` (multifamily_apartment | housing_authority),
  drives terminology, Content Intelligence question sets, allowed upload
  connectors (HA has no CRM/paid), all via `reference_data/property_types.json`
  — no code change to add a new type. DCHP is `housing_authority`.

### Everything earlier (Phases 1-14)
Full build history in `docs/beacon-build-plan-v1.md` and the git log. Summary:
GA4/GSC/GBP/paid/CRM manual upload ingestion with an AI-referral classifier,
RAG pipeline (Chroma + citations), Nora chat, Content/Review/AI Query
Signals/AI Visibility/Competitor Intelligence modules, Opportunity Engine
(unified cross-module recommendations), Companies, property context/gating for
regulated properties.

## Known gaps / deliberately deferred

- **15c** (similarity clustering, KB consolidation onto the shared taxonomy) —
  still deferred until there's more data volume to cluster meaningfully. Note
  the Semantic Intelligence REPORT no longer waits on this: it runs on the
  fixed taxonomy. What 15c would add is grouping near-duplicate phrasings.
- **GBP (Google Business Profile) API** — discussed, decided NOT to build
  (requires Google approval process, lower strategic fit than GA4/GSC, manual
  CSV upload already works). Revisit only if a client leans heavily on Maps
  presence.
- **AI Visibility weekly autorun** — built but OFF. Tina said leave manual for
  now (2026-07-12). She can run "Run all now" from Standing & Trend tab
  herself, or ask to flip `BEACON_AI_VISIBILITY_AUTORUN=1`.
- **Competitor Intelligence** — no competitors added yet for DCHP. Needs Tina
  to name 1-2 real competitors before share-of-voice becomes a real metric
  instead of "insufficient data."
- **CRM API** — no CRM API access exists; Yardi adapter is a documented
  placeholder with obviously-fake column names (guard test locks this).

## Test count discipline

`TEST_COUNT` in `backend/app/constants.py` is manually bumped after each
change (shown on `/admin`). Current: **827**, all passing. Always run the full
suite (`.venv/bin/python -m pytest -q` from `backend/`) before considering a
change done — do not eyeball a subset and call it clean.

## Hard rules (from CLAUDE.md, still binding)

No fabricated data — operator-asserted fields (regulatory status, property
type) are never inferred from content. No em dashes in user-facing copy. The
AI-traffic undercount disclosure is a fixed constant, never paraphrased. Every
intelligence module states its own limitations rather than overclaiming
("insufficient data" beats a fake number, every time). Citations are always
assembled in code from the `rag_chunks` registry, never trusted from model
output. Nora's correlation-claim gate is hard-coded (30+ AI sessions, 5+
leases, |r|≥0.5, 2+ periods) — below threshold, a fixed template is returned
and the LLM is never called.
