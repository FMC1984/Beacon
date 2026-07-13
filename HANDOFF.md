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
