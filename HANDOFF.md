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

### Reliability + AI Visibility scheduling (2026-07-12, 395 tests)
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
