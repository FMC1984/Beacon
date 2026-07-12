# Beacon

Internal, single-user AI performance intelligence dashboard for multifamily
marketing. Tracks AI referral traffic, ties it to CRM/lease outcomes, and
surfaces Nora, a retrieval-grounded analyst that answers only from ingested,
cited data.

Read `CLAUDE.md` (build rules), `docs/beacon-prd-v2.md` (product decisions),
and `docs/beacon-build-plan-v1.md` (schema/architecture) before changing code.

## 1. Starting the app locally

Backend (FastAPI, port 8600):

```
cd backend
.venv/bin/uvicorn app.main:app --reload --port 8600
```

Frontend (Next.js, port 3100; 3000 is usually taken by other local apps):

```
cd frontend
npm run dev -- --port 3100
```

Open http://localhost:3100. Claude Code users: launch configs `beacon-backend`
and `beacon-frontend` exist in `~/Builder/.claude/launch.json`.

First-time setup: `python3 -m venv backend/.venv`, then
`backend/.venv/bin/pip install -r backend/requirements.txt`,
`cd backend && .venv/bin/alembic upgrade head`, and `npm install` in
`frontend/`.

## 2. Environment variables

`backend/.env` (gitignored, chmod 600). Prefix everything with `BEACON_`:

- `BEACON_OPENAI_API_KEY` - OpenAI key for embeddings + Nora generation
- `BEACON_DEMO_MODE` - `1` for keyless demo mode (currently ON)
- `BEACON_NORA_MODEL` - generation model, default `gpt-5-mini`
- `BEACON_DATABASE_URL`, `BEACON_CHROMA_DIR`, `BEACON_DATA_DIR` - defaults fine

## 3. OpenAI billing (LIVE as of 2026-07-05)

Beacon is running LIVE: `BEACON_DEMO_MODE=0`, OpenAI quota passes, both
providers are `openai`, the RAG index is built with real `text-embedding-3-small`
embeddings, and Nora generates real answers through the Responses API. Verified
end to end: the correlation gate blocks thin-data claims, content and review
answers are grounded with per-source citations, and honest "not enough data"
responses hold.

To return to keyless demo mode at any time: set `BEACON_DEMO_MODE=1` in
`backend/.env`, restart, and rebuild the index (the provider change forces a
full rebuild automatically). To stay live, keep a monthly usage limit set at
platform.openai.com (embeddings cost fractions of a cent; Nora answers a few
cents each).

## 4. Running the indexer

From `backend/`:

```
.venv/bin/python -m app.cli.index_rag
```

Or click "Rebuild RAG Index" on the /admin page. Incremental: unchanged
chunks are skipped (tracked via `rag_chunks.text_hash`). Run it after any
upload so Nora sees new data. Chunks are one per property x month x source,
templated from real numbers; no model writes chunk text.

Also useful: `.venv/bin/python -m app.cli.backfill_ai` restamps AI referral
classification after editing `app/reference_data/ai_referrer_domains.json`.

### GA4 upload tolerance

The GA4 parser (`app/services/ingestion/ga4.py`) adapts to the many shapes a
GA4 CSV can take instead of rejecting on formatting: preamble comment lines, a
segment header row above the real header, duplicate metric columns (one set per
segment), extra dimensions it does not need (Event name, Search term), combined
"Session source / medium", "Landing page + query string", a trailing Grand
total row, and "Date + hour (YYYYMMDDHH)" (the date is the leading 8 digits).

The one thing it will not do is silently report wrong numbers. A GA4 export
broken down by **Event name** repeats each session across many event rows, so
summing its Sessions column overcounts several-fold. Beacon detects that shape
and collapses to true sessions using the once-per-session `session_start` event
(this reproduces GA4's own Grand Total exactly), then returns a `warnings` entry
saying it did so. If such a file has no `session_start` rows at all, it is
rejected with a clear instruction (re-export without the Event name dimension)
rather than guessed at. Files with a relative "Nth day" dimension (no real
dates) are likewise rejected with guidance. Uploads remain replace-on-overlap:
re-uploading a file replaces existing rows for the dates it covers.

## 5. Using Nora

Open /nora, pick a scope (portfolio or one property), ask questions. Nora:

- answers only from indexed chunks, with citations (source, property, dates)
- attaches the AI undercount disclosure whenever grounded in GA4 AI data
- is hard-gated in code from claiming AI-traffic-to-lease correlation until
  thresholds are met (30+ AI sessions, 5+ leases, |r| >= 0.5, 2+ shared
  periods); below that she returns a fixed template listing what is missing
- says plainly when the data does not cover a question

In demo mode, answers are labeled deterministic local summaries; citations,
gates, and disclosures behave identically to live mode.

Chats are saved automatically. The /nora sidebar lists saved chats for the
current scope (a selected property shows that property's chats; "All
properties" shows the portfolio-wide ones). Click one to reopen its full
transcript, "New" to start fresh, or the delete control (with confirm) to
remove one. API: `GET /api/nora/conversations?property_id=` (or
`?scope=portfolio`), `GET /api/nora/conversations/{id}`, and
`DELETE /api/nora/conversations/{id}`.

## 5b. Exporting data

Every dashboard has an "Export data" button. It downloads a ZIP of CSVs - one
per data type (properties, GA4 sessions, Search Console, Business Profile, paid
media, CRM leads) - plus a `manifest.txt` that records the scope, row counts,
and the AI-traffic undercount disclosure (the GA4 CSV carries the
`is_ai_referral`/`ai_platform` columns). The export is a straight dump of the
real ingested rows, with no derived or estimated metrics. Scope follows the
dashboard: a single property, a company's properties, the unassigned bucket, or
the whole portfolio. API: `GET /api/export` with optional `property_id`,
`company_id`, or `unassigned=true` (omit all for the whole portfolio).

## 5c. Companies

Properties are grouped under companies (a management company or owner). A
property may belong to one company or none (`company_id` is nullable; no company
= the "Unassigned" bucket). The main dashboard asks for a company first and
shows no data until one is chosen, then aggregates just that company's
properties; you can drill into a single property from there. The company filter
also appears on Nora, Content IQ, Review IQ, and Context (it narrows the
property picker). Manage companies on the Properties page. API:
`GET/POST /api/companies`, `PATCH/DELETE /api/companies/{id}` - deleting a
company unassigns its properties (sets `company_id` NULL) rather than deleting
them. The dashboard and export accept `company_id=` (or `unassigned=true`).

## 6. Running tests

```
cd backend
.venv/bin/python -m pytest tests/
```

125 tests as of 2026-07-05, all passing, no network calls (fake embedder and
fake LLM; ChromaDB runs locally). After a release checkpoint, update
`TEST_COUNT` in `app/constants.py` so the admin page stays honest.

## 6d. Review Intelligence (Phase 11)

A deterministic review-reasoning engine (no external AI, no sentiment model).

- **Storage** (`property_reviews`): rating (nullable, half-stars), title, body,
  review_date, response, provider, external_review_id, source_url. Partial
  unique index on (property_id, provider, external_review_id) applies only when
  external_review_id is not null (works on SQLite + Postgres), so any number of
  manually entered null-id reviews coexist.
- **Connector**: uses the existing `ReviewProvider` seam (signature unchanged);
  `ReviewRecord` was extended additively. `DevelopmentDataProvider.get_reviews`
  reads the table.
- **CRUD API**: `GET/POST /api/reviews/{property_id}` (filters: provider,
  min/max rating, date range, limit/offset), `PUT`/`DELETE
  /api/reviews/{property_id}/{review_id}`. Any write enqueues a `reviews` RAG
  sync.
- **Engine** (`app/services/review_intelligence/`): `analyze_property_reviews()`
  produces Overview + sentiment, per-theme sentiment, strengths, prioritized
  operational opportunities, review trends, marketing insights, and a composite
  Review Health Score (Critical/Needs Attention/Basic/Healthy/Excellent). All
  fixed rules, echoed in the API output. Matching notes: a theme is a mention
  counted once per review; positive vs negative term counts classify it;
  matching is literal (negation not detected: "not very clean" matches "very
  clean" — a documented limitation).
- **Trends** anchor to the most recent review date (not today), use 90-day
  windows with a 6-month fallback, require >= 3 reviews per period applied
  per-metric and per-theme, and say "cannot determine" otherwise.
- **Property-context gating**: every marketing insight passes through the Phase
  10.5 `gate()` utility; unknown status withholds compliance-sensitive insights;
  regulated properties suppress restricted framing; property type/status is
  never inferred from reviews.
- **Configurable JSON**: `review_themes.json`, `review_sentiment_terms.json`
  (strong flags), `review_operational_categories.json` (effort + severity +
  suggested actions), `review_marketing_themes.json` (with context gating links).
- **RAG**: one chunk per review (citation fidelity) + one derived
  `review_intelligence` chunk stating the score, complaints, praise, trends,
  and verbatim insufficient-data/compliance text. Replace-on-write; deleting a
  review removes its chunk. Nora answers review questions with citations.
- **Dashboard** at `/review-intelligence` ("Review IQ" in the nav) with all six
  sections and honest empty/insufficient states.

## 6c. Property Context (Phase 10.5)

A thin, reusable operator-context layer that keeps recommendations from being
wrong-by-default (e.g. "highlight exclusivity" on regulated affordable housing).

- **Model** (`property_profile`, 1:1 with Property): property_type,
  target_audience, `is_regulated` (nullable — null means UNKNOWN, never "not
  regulated"), regulatory_programs, marketing restriction flags/notes.
- **Program-status integrity (hard rule)**: regulatory/program/type status is
  ALWAYS operator-asserted and NEVER inferred from reviews, names, amenities, or
  content. Unknown status withholds compliance-sensitive guidance with the exact
  message "Program status not specified; compliance-sensitive guidance withheld."
  Fail-safe: an empty `is_regulated` with a manually set program is treated as
  regulated (more restrictive).
- **Vocabulary + gating rules** in `app/reference_data/property_context.json`
  (property types, programs, restriction flags, themes, gating rules, the exact
  unknown message). Editable without a migration.
- **Deterministic gating utility** (`app/services/property_context.py`):
  `gate(context, theme) -> allowed | suppressed | caution-only` with a stated
  reason. Identical input always yields identical output. Both Content
  Intelligence and (Phase 11) Review Intelligence call it. Examples: regulated
  suppresses exclusivity / demographic-targeting / young-professional framing;
  senior and active_adult suppress nightlife / young-professional; student
  treats "quiet community" as caution-only; unknown withholds compliance-
  sensitive themes.
- **RAG**: a property-scoped `property_context` chunk states type, audience,
  regulatory status (or explicit "unknown"), and restrictions verbatim, so Nora
  grounds context answers in retrieved text. Replace-on-write (one chunk per
  property) via the existing sync; the Content Intelligence chunk references it.
- **API**: `GET /api/property-context/vocabulary`, `GET/PUT
  /api/property-context/{property_id}` (validates against the JSON vocabulary).
  Editor at `/property-context` ("Context" in the nav) with an explicit three-
  state regulatory selector defaulting to Unspecified and honest "unspecified"
  displays.

## 6i. Opportunity Engine (Phase 14)

The capstone: one prioritized, context-gated, deduplicated to-do list unified
across every intelligence module. Deterministic - it aggregates the
already-computed recommendations, it does not invent new ones.

- **Aggregator** (`app/services/opportunity_engine.py`): `build_opportunities()`
  calls the five deterministic analyzers (Content Intelligence, Review
  Intelligence, AI Query Signals, AI Visibility, Competitor Intelligence, each
  guarded so an empty module contributes nothing), normalizes their differing
  recommendation shapes into one, applies a UNIFORM Property Context `gate()`
  pass (so gating is consistent even for sources that did not attach a state),
  boosts opportunities that more than one independent module points at
  (corroboration on shared renter topics), and ranks by state -> impact ->
  corroboration -> effort. Identical inputs always produce the identical ranked
  list.
- **Honest buckets**: the main list is Actionable / Monitor / Requires
  confirmation; **Suppressed** (blocked by property context) and **Insufficient
  data** items are surfaced in their own sections, never hidden.
- **RAG + Nora**: an `opportunity_engine` chunk (rebuilt whenever any feeding
  source changes) summarizes the top ranked opportunities, so Nora answers "what
  should we do first?" from the unified list through the existing path.
- **API**: `GET /api/opportunities/{id}`, `POST /{id}/analyze`. **Frontend**:
  `/opportunities` ("Opportunities" nav) - the numbered prioritized list with
  source + state chips, impact/effort, corroboration badges, and the separate
  suppressed / awaiting-data sections.

## 6j. Property type / client type

Not every client is an apartment community. A `Property` now carries a REQUIRED
`property_type` (client/site type) that adapts the whole product without adding
an Organization/Website layer - the `Company -> Property` hierarchy is unchanged
and the backend term stays `Property` for every client type.

- **Config, not enums** (`app/reference_data/property_types.json`,
  `app/services/property_types.py`): each type declares its `label`,
  `terminology` (site / audience / unit / unit-count label), which Content
  Intelligence knowledge bases it uses, and its `allowed_connectors`. Add a type
  (plus its KB files) with no migration. Initial types: `multifamily_apartment`
  (the default) and `housing_authority`.
- **Backward compatible**: a NOT NULL column with
  `server_default "multifamily_apartment"` (migration
  `b8c9d0e1f2a3_property_type`) means every existing property is a multifamily
  apartment automatically. Invalid values are rejected (422).
- **Distinct from `PropertyProfile.property_type`**: that field is the
  operator-asserted regulatory/marketing type (affordable / senior / student).
  The new `Property.property_type` is the client/site type; Nora context exposes
  it under the separate key `site_type`.
- **Type-driven behavior**: Content Intelligence swaps the question set and
  required page TOPICS per type (a housing authority scores against applicant
  questions - how to apply, eligibility, vouchers, waitlist - not pet policy or
  floor plans), the page storage keys stay fixed but the UI relabels them
  (Amenities -> Programs & Services, Floor Plans -> Eligibility & Application,
  Neighborhood -> Service Area & Resources), terminology adapts (units ->
  developments), and the `property_context` chunk carries the site type so Nora
  frames answers correctly. A housing authority offers fewer connectors
  (`ga4`, `gsc`, `gbp`; no CRM/paid) - the Uploads page hides the data-source
  buttons a property's type does not support and explains why, and the upload
  endpoints reject a disallowed source server-side (422) as a backstop.
- **A housing authority is a Property**: e.g. Company "Douglas County Housing
  Partnership" -> Property "DCHP" with `property_type = housing_authority`.
- **API**: `GET /api/properties/types/config` returns the full type config;
  create/update accept `property_type`. **Frontend**: `/properties` has a type
  selector (create + edit), a type badge on each card, and adaptive unit labels;
  `/uploads` filters its data-source buttons by the selected property's
  `allowed_connectors`.

## 6k. Semantic Intelligence (Phase 15a)

A shared, deterministic NLP enrichment layer under every intelligence module
and the RAG index. No model calls: everything derives from versioned reference
JSONs (`semantic_topics/intents/entities/normalization/negation.json`) plus
database-known names, and every assertion carries the matched rule that
produced it - never a fabricated confidence score.

- **Enrichment** (`app/services/semantic/`): each indexed chunk is stamped with
  topics, entities (static vocab + the property's own name/city/competitors
  from the DB), intents, clause-scoped per-topic sentiment, and normalized
  terms (HVAC / A/C / air conditioning -> `air_conditioning`). Stored in
  `rag_chunks.enrichment` (migration `c9d0e1f2a3b4`) and as filterable Chroma
  metadata (`topic_<key>: true`); enrichment is recomputed on every sync so a
  taxonomy edit refreshes metadata without re-embedding, and chunk text is
  never replaced.
- **Negation** (conservative by design - missed negations are acceptable,
  invented ones are not): a plain cue before a positive term flips it ("not
  very clean" is a cleanliness complaint); an absence phrase excludes the
  mention ("did not have a maintenance issue" is not a maintenance mention);
  bare "no"/"zero"/"without" excludes only in a problem-noun span ("no
  maintenance issues"), so "no parking" stays a complaint; plain cues never
  cancel negative terms, so "never fixed my broken heater" stays a complaint;
  a cue inside a KB phrase like "not fixed" never negates it; "not only" is
  not a negation and clause breakers end a cue's scope.
- **Review Intelligence integration**: theme classification and overall
  sentiment run their term lists through the negation layer, fixing the
  documented literal-matching limitation from Phase 11.
- **Hybrid retrieval (15b)**: vector search now PROPOSES a candidate pool
  (optionally pre-filtered by property / source / topic metadata); a
  deterministic reranker SELECTS and ORDERS the final results using
  transparent weighted components from `rag_retrieval.json` - semantic
  similarity, keyword overlap, phrase match (stopword-filtered bigrams, so
  "washer dryer" matches "washer and dryer"), topic overlap, entity overlap,
  and data-relative recency (anchored to the newest candidate, never
  wall-clock). No LLM influences ranking; ties break on chroma_id. Nora
  inherits automatically through the existing `retrieve()` - same signature,
  citations unchanged. Every result carries `match_explanation` (component
  scores + matched keywords/phrases/topics/entities);
  `GET /api/admin/retrieval-debug?q=...` is the developer-only "matched
  because" view, not surfaced to end users.
- **Deferred to 15c**: similarity clustering and consolidating the older
  module KBs onto the shared taxonomy (waiting on data volume).

## 6h. Competitor Intelligence (Phase 13)

The one competitive question Beacon can answer HONESTLY today: AI-answer **share
of voice**. Across the AI Visibility responses already collected for a property,
how often does an AI platform mention the property versus each operator-named
competitor? Deterministic, sample-gated, no scraping, no guessing.

- **Operator-asserted competitors** (`competitors` table, migration
  `a7b8c9d0e1f2`): the operator names competitors (with optional aliases the AI
  might use); Beacon never discovers, infers, or scrapes them - the same posture
  as Property Context. CRUD at `/api/competitors/{property_id}`.
- **Share-of-voice analyzer**
  (`app/services/competitor_intelligence/analyzer.py`): counts per-query mention
  PRESENCE (each entity counted once per response it appears in, matching the
  `brand_mentioned` semantics) for the property and each competitor, using the
  same literal, negation-unaware matching as brand detection. Share =
  entity mentions / total mentions. Every share figure is gated below
  `MIN_QUERIES_FOR_VISIBILITY` (reports "insufficient", never a misleading
  number). Recommendations are gated through the Property Context `gate()`.
- **Deliberately deferred** (declared in the output, not silently skipped; each
  needs data Beacon does not hold): automated competitor discovery, competitive
  pricing / occupancy, and positioning / unit-mix comparison against competitor
  properties.
- **RAG + Nora**: a `competitor_intelligence` chunk (rebuilt when competitors
  change or new AI Visibility data lands) summarizes share of voice with
  directional / insufficient-data language; Nora answers "who shows up more than
  us in ChatGPT" through the existing retrieval path.
- **API**: `GET /api/competitor-intelligence/{id}`, `POST /{id}/analyze`.
  **Frontend**: `/competitors` ("Competitor IQ" nav) - manage the competitor
  list and see the share-of-voice bars with honest empty / insufficient states,
  gated recommendations, and the declared deferrals.

## 6g. AI Visibility Scanner (Phase 12)

Deterministic analysis + scoring on top of the Phase 11.5 stored queries -
built to the Content/Review Intelligence standard (no LLM, every judgment
explainable), and gated hard against overclaiming from a thin query sample.

- **Analyzer** (`app/services/ai_visibility/analyzer.py`): `analyze_ai_visibility()`
  produces per-platform mention rates (each platform gated - "insufficient"
  below the minimum, never a misleading rate), a source landscape (which
  domains the AI leans on and how often, plus whether the property's own site is
  cited), an interpreted set of hallucination findings (the Phase 11.5 hook is
  detection; this turns its flags into findings), and an explainable AI
  Visibility **score** - computed ONLY when the sample clears the minimum
  (`MIN_QUERIES_FOR_VISIBILITY`), otherwise `None` with an honest "not enough
  data" state. The score shows its component breakdown (mention rate + fact
  consistency) and is always labeled directional.
- **Recommendations** are evidence-backed and pass the Property Context
  `gate()`: states Actionable / Monitor / Requires confirmation / Suppressed /
  Insufficient data. Price/eligibility/audience-positioning topics require
  confirmation on a regulated or unknown-status property; restricted positioning
  themes are suppressed - identical treatment to Review Intelligence's marketing
  insights.
- **Deliberately deferred** (declared in the output, not silently skipped; each
  needs external data Beacon does not hold): prompt-volume / demand estimation,
  source-authority cross-referencing against Google rankings, and competitor
  share-of-voice (the last belongs to a future Competitor Intelligence phase).
- **RAG + Nora**: the `ai_visibility` chunk now summarizes the analysis (score,
  mention rate, sources, fact-checks, top recommendations) with the same
  directional / insufficient-data language; Nora cites it through the existing
  path.
- **API**: `GET /api/ai-visibility/{id}/analysis`, `POST /{id}/analyze`
  (triggers a sync). **Frontend**: an "Analysis" tab on `/ai-visibility` (score
  or honest not-enough-data state, per-platform mention rates, source landscape,
  fact-check findings, gated recommendations, and the declared deferrals),
  alongside the Phase 11.5 "Run & Queries" tab.

## 6f. AI Visibility Foundation (Phase 11.5)

The external-query layer. Unlike every other module (deterministic analysis of
data Beacon owns), knowing what an AI platform says about a property requires
actually querying that platform. This phase settles the infrastructure and the
determinism boundary once, before the analysis module (Phase 12) is built on it.

- **Determinism boundary (hard rule)**: `execute_query` against an external AI
  platform is the ONLY non-deterministic step in Beacon. Everything downstream
  of the stored `raw_response_text` - mention detection, source extraction, the
  hallucination hook, the RAG summary - is deterministic: identical stored text
  always yields identical output. No re-querying the AI to "confirm" a parse.
- **Provider seam** (`AIVisibilityQueryProvider` in `app/connectors/base.py`,
  same pattern as `ReviewProvider`): `execute_query(prompt, platform) -> str`
  plus a deterministic property-scoped `get_queries`. Concrete impls in
  `app/services/ai_visibility/providers.py`: `OpenAIVisibilityProvider`
  (live, API-based) and `DemoVisibilityProvider` (deterministic, keyless).
  Designed for multiple platform connectors from the start; only ChatGPT is
  live. Empty state stays stable when no queries have been run.
- **Query methodology (documented, not implicit)**: Beacon calls AI-platform
  APIs directly, NOT a simulated consumer UI. Stated in
  `app/reference_data/ai_visibility.json`, echoed by `GET /api/ai-visibility/meta`,
  and shown in the product. Known limitation: API responses may differ from what
  a real user sees in the consumer app.
- **Storage** (`ai_visibility_queries`): one row per executed query with the
  verbatim response preserved permanently (the citation source, as review text
  is in Phase 11). `platform` is a JSON-vocabulary string (no DB enum);
  `brand_mentioned` and `sources_cited` are deterministically parsed. Migration
  `f6a7b8c9d0e1`.
- **Deterministic parsing** (`app/services/ai_visibility/parsing.py`): literal,
  case-insensitive, whole-word/phrase, negation-UNAWARE mention detection
  (same standard as Phase 11, limitation documented); URL/domain source
  extraction, de-duplicated and sorted.
- **Cost / rate controls**: a fixed per-property daily budget
  (`BEACON_AI_VISIBILITY_DAILY_LIMIT`, default 20). Exceeding it raises and the
  API returns 429 with an honest message; every execution is logged for cost
  audit. Stored-result reads are never limited.
- **Hallucination-check hook** (`app/services/ai_visibility/hallucination.py`):
  deterministic detection MECHANISM only (a flag with a reason; interpretation
  is Phase 12). Compares response claims against data Beacon holds with
  confidence - name/city (presence), state (contradiction via a US-state
  vocabulary), property type (contradiction via `ai_visibility.json` synonyms,
  only when Property Context supplies the type). A missing fact returns
  `cannot_verify`, never a silent skip or an assumption; Beacon never infers a
  fact to enable a check.
- **RAG + Nora**: a property-scoped `ai_visibility` chunk (replace-on-write,
  stale cleanup, rebuilt on a query or a property-context change) summarizes
  platform / mention rate / sources with directional, sample-size-aware
  language and explicit insufficient-data wording (mirrors Phase 11 trend
  gating - never a precise visibility percentage). Nora retrieves and cites it
  through the existing path; verified live that it answers "how do we show up in
  ChatGPT" with "insufficient queries... treat as anecdotal".
- **API**: `GET /api/ai-visibility/meta` (platforms + methodology + provider),
  `POST /{id}/query` (rate-controlled execution), `GET /{id}` (list, filter by
  platform/date, with budget), `GET /{id}/{query_id}` (single + the fact-check
  hook output). Frontend `/ai-visibility` ("AI Visibility" nav): run a query,
  see raw results / mention / sources, honest empty and budget-reached states.
  No scoring, trends, competitor comparison, or recommendations - those are
  Phase 12.

## 6e. AI Query Signals

An evidence-first view of AI-referred traffic. Its whole reason for existing is
honesty about a hard limit: **referral analytics never carry the exact prompt a
person typed into an LLM.** So the feature separates what is known into three
tiers and never blurs them. No external AI, no scraping, no fabricated queries.

- **Analyzer** (`app/services/ai_query_signals.py`): `analyze_ai_query_signals()`
  returns three clearly separated evidence tiers:
  - **Observed** - GA4 AI-referred sessions, platform mix, landing pages,
    engagement, conversions, dates (real ingested rows). Engagement is compared
    with non-AI traffic only when both sides clear a volume bar.
  - **Search-Adjacent** - Google Search Console queries observed for the *same*
    landing page (page/query association required; low-confidence associations
    are excluded, never invented). Shown with a fixed disclosure that these are
    Google searches, **not** LLM prompts. When GSC is absent or has no matching
    page/query rows for the period, an honest unavailable state is returned.
  - **Inferred** - likely topics and renter-question signals derived
    deterministically from landing-page paths, Content Intelligence topic
    coverage, stored content, and search-adjacent queries. Confidence is the
    count of independent corroborating signal types (Strong/Supported/Limited).
    Every inferred item carries the label "Inferred from landing-page and
    content signals. This is not an actual AI prompt." No embeddings, no LLM.
- **Recommendations** are evidence-backed only, with explicit states
  (Actionable / Monitor / Requires confirmation / Suppressed; withheld entirely
  below a volume bar). Each is gated through the Property Context `gate()`:
  positioning themes can be suppressed, and any price/eligibility/affordability
  topic requires confirmation when regulatory status is regulated or unknown.
- **GSC is optional.** The page works without it; DCHP's real data (a GSC
  Queries export with no page column) correctly shows the search-adjacent
  unavailable state.
- **API**: `GET /api/ai-query-signals/{property_id}` with optional `start`,
  `end`, `platform`, and `landing_page` filters; `POST /{id}/analyze` refreshes
  the RAG chunk. Output tags every finding as observed / search-adjacent /
  inferred, with confidence/evidence levels, citations, and disclaimers.
- **RAG + Nora**: a derived `ai_query_signals` chunk (rebuilt whenever GA4, GSC,
  or content changes) summarizes the signals and embeds the exact-prompt
  limitation, so Nora answers "what pages are AI visitors landing on?" and "do
  we know what people asked ChatGPT?" with citations and the limitation stated,
  using the existing retrieval path (no separate Nora code).
- **Frontend**: `/ai-query-signals` ("AI Signals" in the nav) with Overview,
  Landing Pages, Search-Adjacent Queries, Inferred Topics, and Limitations tabs,
  evidence chips, a persistent prompt-limitation note, and no invented prompts.
- **Terminology is enforced**: never "user asked ChatGPT", "actual AI query",
  "LLM search term", or "prompt used [was X]"; always "AI-referred traffic",
  "related Google Search query", "inferred topic", and "cannot determine exact
  LLM prompt". A test scans the full API response for the forbidden claims.

## 6b. Content Intelligence (Phase 10)

A deterministic content-reasoning engine. No external AI is called for analysis.

- **Content storage** (`property_content`): website pages (homepage, amenities,
  floor_plans, neighborhood, faq) with a mapped keyword and an updated_at
  freshness signal. Enter content manually via `PUT /api/content/{property_id}`,
  or pull it live from the page's own URL via
  `POST /api/content/{property_id}/{page}/fetch` (a plain HTTP fetch + HTML
  text extraction, no external AI - see `app/services/content_fetch.py`).
  Fetch has no JavaScript rendering (SPA pages may return little or no text)
  and no crawling/auto-discovery; the operator supplies each canonical page's
  URL explicitly. Saving either way enqueues a RAG sync.
- **Analyzer** (`app/services/content_intelligence/`): `analyze_property()`
  produces keyword intent (topic coverage, not keyword frequency), renter
  question coverage (answered/partial/missing), neighborhood rating (Poor/Basic/
  Good/Excellent), content freshness (flags outdated promos and stale pages;
  says "cannot determine" honestly when there is no date signal), a prioritized
  opportunity list, and an explainable composite score. Every judgment is a
  fixed term/topic rule, so results are reproducible; every score shows its
  component breakdown with weights.
- **Configurable knowledge bases** (`app/reference_data/`): `renter_questions.json`,
  `neighborhood_topics.json`, `content_intent.json`. Add a question, topic, or
  term by editing JSON; no code change.
- **API**: `GET /api/content-intelligence/{property_id}` (live analysis),
  `POST /api/content-intelligence/{property_id}/analyze` (recompute + refresh
  Nora's chunk). Dashboard at `/content-intelligence` ("Content IQ" in the nav).
- **Nora integration**: the analysis is indexed as a `content_intelligence` RAG
  chunk, so Nora answers "what content should we improve first?", "what renter
  questions are missing?", etc. with citations, reusing the existing pipeline.

## 6a. Platform architecture (Phase 9)

Beacon is provider-agnostic and keeps its knowledge base current automatically.

- **Providers** (`app/providers/`): `EmbeddingProvider` (embed/dimension) and
  `LLMProvider` (generate/stream) interfaces. Concrete: `OpenAIProvider`,
  `OpenAIEmbeddingProvider`, and keyless `DeterministicEmbeddingProvider` /
  `DemoLLMProvider`. `registry.py` picks one from settings. Add a provider
  (Gemini, Claude, Cohere, local) by implementing the interface and extending
  the registry; no business-logic change.
- **Connectors** (`app/connectors/`): `TrafficProvider`, `LeadProvider`,
  `LeaseProvider`, `ReviewProvider`, `ContentProvider` return normalized
  records. `DevelopmentDataProvider` reads the local ingested data today;
  reviews/content are empty extension points. Consumers never know the origin.
- **Automatic RAG sync** (`app/services/rag_sync_service.py`): uploads enqueue a
  `RagSyncJob` instead of embedding inline (the UI never waits). A worker drains
  the queue and re-embeds only changed chunks. Drain it three ways: set
  `BEACON_RAG_AUTOSYNC=1` (background task after upload), run
  `python -m app.cli.rag_worker [--loop]`, or click "Process Queue" on /admin.
  A full rebuild happens only when the embedding provider or version changes.
- **Registry** (`rag_chunks`): each chunk records source, page, hash, provider,
  embedding version, and updated/created timestamps for debugging and future
  AI validation.
- **Future hooks** (`app/extensions/hooks.py`): `trigger_rag_sync(...)` and the
  `IntelligenceModule` base let a future module (AI Visibility Scanner, Content/
  Competitor/Review Intelligence, Opportunity Engine) request a sync without
  touching any existing service. None are implemented.

## 7. Troubleshooting quota errors

- Symptom: 429 `insufficient_quota` in logs, "OpenAI request failed" in Nora,
  or "failed: ..." quota check on /admin.
- Cause: the OpenAI account has no billing/credits, or the usage limit is hit.
- Check: /admin runs a live quota check whenever a key is configured and demo
  mode is off.
- Workaround: set `BEACON_DEMO_MODE=1` and rebuild the index; everything works
  keylessly, clearly labeled as demo.
- The app never crashes on quota errors: uploads/dashboards never touch
  OpenAI; Nora and reindex fail with readable messages.

## 8. What is complete

- Phase 11 Review Intelligence: review storage (partial-unique dedup),
  ReviewProvider implementation, review CRUD, a deterministic review-reasoning
  engine (sentiment, themes, severity-weighted opportunities, anchored trends,
  gated marketing insights, explainable Review Health Score), per-review +
  derived RAG chunks with stale-chunk cleanup, and Nora review answers with
  citations. See section 6d.
- Phase 10.5 Property Context: operator-asserted property-context layer
  (`property_profile`), configurable vocabulary + gating rules in JSON, a
  reusable deterministic recommendation-gating utility, the program-status
  integrity rule (never inferred; unknown withholds compliance-sensitive
  guidance), a `property_context` RAG chunk Nora cites, CRUD + a three-state
  editor, and Content Intelligence consuming it from day one. See section 6c.
- Phase 10 Content Intelligence: deterministic content-reasoning engine
  (keyword intent, renter question coverage, neighborhood, freshness,
  opportunities, explainable score), content storage lighting up the Phase 9
  ContentProvider seam, configurable question/topic knowledge bases, CI API +
  dashboard, and Nora answering content questions with citations. See section 6b.
- Phase 9 platform architecture: provider abstraction (LLM + embedding),
  connector architecture (traffic/lead/lease/review/content), automatic RAG
  synchronization with a queue + worker, expanded chunk registry, admin
  synchronization dashboard with a Process Queue button, and future-module
  hooks. See section 6a.
- Phases 1-8 (see CLAUDE.md checklist): schema + migrations (Alembic);
  manual CSV ingestion for GA4, GSC, GBP, paid media, CRM with raw-file
  retention and citation-grade provenance; Tier 1 AI referral classifier
  (reference JSON) with backfill CLI; transport-agnostic CRMAdapter with a
  deliberately fake Yardi placeholder mapping; portfolio + property dashboards
  (provenance/freshness envelope on every metric, shared disclosure component
  on every AI figure); RAG pipeline (deterministic chunks, incremental index,
  ChromaDB, cited retriever); Nora with the in-code correlation gate; demo
  mode; admin health page with reindex button.
- Dev database is seeded with 4 demo properties covering all dashboard states
  (AI present/absent, fresh/stale, missing CRM, empty property, multi-AI).

## 9. What is NOT complete

- OpenAI billing (section 3): until enabled, live embeddings and live Nora
  generation are untested end to end. Everything else about those paths is
  unit-tested. First action after billing: rebuild index, ask Nora the three
  demo questions on /nora, confirm citations/disclosure/gate.
- Classifier validation against a real source-level GA4 export (needs an
  export with Date + Session source/medium dimensions; the only real export
  seen so far was channel-group grain and is correctly rejected). See
  `backend/app/services/classifier.py`.
- Yardi field mapping is a placeholder by design (CLAUDE.md hard rule 4). Do
  not replace it without real Yardi export samples; a guard test
  (`test_yardi_mapping_is_loudly_fake`) will fail on any realistic-looking
  mapping.
- Phase 9 (weekly/monthly/quarterly/executive reports) not started; reuse the
  Nora pipeline (retrieve -> gate -> generate -> cite) and the `reports` table
  which already exists in the schema.
- Phase 10 (polish: light mode, chart quality, filtering speed) not started.
- Nora model default is `gpt-5-mini` (config `BEACON_NORA_MODEL`); not yet
  validated against the live API because of the billing blocker.

## Future Roadmap

Recommended order. Provider abstraction, connector architecture, and automatic
RAG sync are DONE (Phase 9); the roadmap below is what remains.

1. **Enable billing + live E2E pass** (hours, do first). Then flip
   `BEACON_DEMO_MODE` off; the live OpenAI provider is selected automatically.
2. **Reports (was Phase 9 in the old plan) + Phase 10 polish** - reuse the Nora
   retrieve/gate/generate/cite pipeline and the `reports` table.
3. **Migrate metric chunk-building onto the connectors** - the chunker's GA4/
   GSC/GBP/paid/CRM builders still query models directly; move them behind
   `TrafficProvider`/`LeadProvider`/etc. (the seam and `DevelopmentDataProvider`
   already exist and are tested). Content already flows through `ContentProvider`.
4. **Google OAuth connections** - GA4 Data API, Search Console API, Business
   Profile APIs, Google Ads API, as `*Provider` connector implementations.
   Schema is ready (`data_connections`, `sync_jobs`, dual provenance). Requires
   explicit go per CLAUDE.md; keep the product-language rules ("Auto-sync",
   "Near real-time where supported", never "real-time" unless the API supports
   it).
5. **Additional providers** - `GeminiProvider`, `ClaudeProvider`,
   `CohereEmbeddingProvider`, `LocalEmbeddingProvider`: implement the interface,
   extend `providers/registry.py`. A provider/version change auto-triggers a
   full rebuild.
6. **Marketing IQ / HubSpot / Salesforce connectors** - implement the connector
   interfaces; the rest of Beacon is unaffected.
7. **Intelligence modules** - Content Intelligence (Phase 10) and Review
   Intelligence (Phase 11) are built. Remaining: AI Visibility Scanner (does the
   property appear in AI assistant answers), Competitor Intelligence (which owns
   the deferred property-class / physical-type / positioning / unit-mix fields
   from Phase 10.5), and an Opportunity Engine that unifies Content + Review
   recommendations. Each subclasses `IntelligenceModule`, reads property context,
   gates recommendations via `gate()`, and calls `request_reindex(...)`.

Known limitations of Content Intelligence (Phase 10):
- Analysis is term/topic matching, not semantic understanding. It is
  deterministic and explainable by design, but a page can phrase a topic in
  words not in the knowledge base and be scored as missing. Mitigate by adding
  terms to the JSON knowledge bases (no code change).
- Content can be entered manually or pulled live from a URL
  (`POST /{property_id}/{page}/fetch`), but that fetch is a single-page plain
  HTTP GET + text extraction: no JavaScript rendering (SPA-built pages may
  yield little or no text), no crawling or automatic subpage discovery, and no
  CMS sync. The operator supplies each canonical page's URL explicitly, and
  re-running fetch is how content gets refreshed - there is no scheduled or
  automatic re-crawl.
- Freshness uses update timestamps and past-year promo detection; without a
  date signal it reports "cannot determine" rather than guessing.

CRM API access remains a documented placeholder (no API available); if
granted, it uses `data_connections` with `source_type=crm` plus the existing
CRMAdapter, no schema changes.
