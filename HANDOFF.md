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
  deferred until there's more data volume to cluster meaningfully (currently
  ~1 property, ~10 RAG chunks).
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
change (shown on `/admin`). Current: **395**, all passing. Always run the full
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
