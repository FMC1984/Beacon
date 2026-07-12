# Beacon Build Plan v1

> Status: Drafted 2026-07-04 by Claude from CLAUDE.md constraints (original doc not
> found on this machine or in Drive; Tina approved drafting fresh). Source of truth
> for schema, folder structure, and architecture. Product decisions live in
> `beacon-prd-v2.md`.

## 1. Architecture Overview

```
CSV/report exports (GA4, GSC, GBP, paid media, CRM)
        |  manual upload
        v
FastAPI backend ── ingestion services ── Tier 1 AI classifier (stamps rows at ingest)
        |                                      |
     SQLite  <── SQLAlchemy models / Alembic ──┘
        |
        ├── metrics API (every AI figure wrapped with disclosure)
        ├── correlation engine (hard gate lives here)
        ├── RAG: chunker -> OpenAI embeddings -> ChromaDB -> retriever
        └── Nora: retrieval + gate + citation assembly -> OpenAI Responses API
        |
     Next.js frontend (App Router, dark-mode first)
```

Single machine, single user. Backend serves JSON to the Next.js app; no auth.

**Stack note (flagged, not silently changed):** CLAUDE.md says "OpenAI Responses API for both RAG and embeddings." The Responses API does not produce embedding vectors; embeddings come from OpenAI's embeddings endpoint (`text-embedding-3-small`). Reading the intent as "OpenAI API for both jobs": generation goes through the Responses API, embeddings through the embeddings endpoint, both via the official `openai` Python SDK.

## 2. Folder Structure

```
Beacon/
  CLAUDE.md
  docs/
    beacon-prd-v2.md
    beacon-build-plan-v1.md
  backend/
    requirements.txt
    alembic.ini
    alembic/
      env.py
      versions/
    app/
      __init__.py
      main.py                 # FastAPI app factory + router registration
      config.py               # pydantic-settings; DATABASE_URL, OPENAI_API_KEY, CHROMA_DIR
      constants.py            # AI_TRAFFIC_DISCLOSURE and other fixed copy
      db.py                   # engine, session factory, Base
      models/                 # one module per domain, all imported in __init__.py
        __init__.py
        property.py
        uploads.py
        traffic.py            # GA4, GSC, GBP, paid media daily tables
        crm.py
        rag.py
        nora.py
        reports.py
      schemas/                # pydantic response/request models (grow per phase)
      routers/                # health (P1), uploads (P2+), metrics (P2+), nora (P8), reports (P9)
      services/
        ingestion/            # ga4.py, gsc.py (P2), gbp.py, paid.py (P4)
        classifier.py         # Tier 1 matcher (P3)
        correlation.py        # engine + can_claim_correlation gate (P8, gate signature fixed now)
        rag/                  # chunker.py, embedder.py, retriever.py (P7)
        nora.py               # response assembly: retrieve -> gate -> generate -> cite (P8)
        reports.py            # (P9)
      adapters/
        crm_base.py           # CRMAdapter interface (P5)
        yardi_adapter.py      # PLACEHOLDER mapping, loud warning block (P5)
      reference_data/
        ai_referrer_domains.json
    tests/
  frontend/                   # Next.js app, created in Phase 6
```

## 3. Database Schema

SQLite via SQLAlchemy 2.x declarative models; Alembic with `render_as_batch=True` (SQLite ALTER support). All tables created in the Phase 1 initial migration; later phases add migrations only if the schema must change (and any such change gets called out explicitly, per CLAUDE.md).

Conventions: integer autoincrement PKs; `created_at` UTC datetimes server-defaulted; string enums stored as plain VARCHAR with Python-side `Enum` validation (`native_enum=False`); money as `Numeric(12, 2)`.

**Dual provenance (added 2026-07-04):** every data table (`ga4_sessions_daily`, `gsc_performance_daily`, `gbp_metrics_daily`, `paid_media_daily`, `crm_leads`) carries nullable `upload_id` and nullable `sync_job_id` FKs with a CHECK that at least one is set. Manual uploads set `upload_id`; future Google OAuth syncs will set `sync_job_id`. This is what lets OAuth land later without schema rewrites.

**RAG readiness (added 2026-07-04):** no RAG/embeddings/vector store/Nora code exists yet by design, but ingestion already preserves everything a Phase 7 citation needs. The inventory, requirement to column:

| requirement | where it lives |
|---|---|
| source name | `uploads.source_type` / `sync_jobs.source_type` |
| import method | derivable: `upload_id` set = manual upload, `sync_job_id` set = API sync |
| source account | `uploads.source_account` / `data_connections.external_account_id` + `account_name` |
| file name or API endpoint | `uploads.filename` + `stored_path` / `sync_jobs.endpoint` |
| report type | table encodes it for uploads; `sync_jobs.report_type` for syncs |
| date range | `uploads.date_start/date_end` / `sync_jobs.date_start/date_end` |
| imported_at | `uploads.uploaded_at` / `sync_jobs.completed_at` |
| source row identifier | `source_line` on traffic tables; `crm_leads.external_lead_id` |
| property_id mapping | `property_id` on every data row and upload |
| metric type | the table the row lives in; carried into citations via `rag_chunks.source_table` |
| raw source payload | original file bytes at `uploads.stored_path` (kept even for failed ingests) |

The four traffic tables carry `source_line` (real file line number, preamble counted). GBP, paid media, and CRM ingesters added in Phases 4-5 must capture this same set.

### properties
| column | type | notes |
|---|---|---|
| id | int PK | |
| name | str, unique, required | display name |
| slug | str, unique, required | URL identifier |
| external_code | str, nullable | property code in external systems (CRM etc.) |
| city / state | str, nullable | |
| unit_count | int, nullable | |
| is_active | bool, default true | |
| created_at | datetime | |

### uploads
One row per uploaded export file; every ingested data row points back to its upload for provenance and re-ingest.
| column | type | notes |
|---|---|---|
| id | int PK | |
| source_type | enum: ga4, gsc, gbp, paid_media, crm | |
| property_id | FK properties, nullable | null when the file covers multiple properties |
| filename | str | |
| source_account | str, nullable | which account/property the export came from (user-supplied) |
| date_start / date_end | date, nullable | range the file covers; set at ingest |
| stored_path | str, nullable | raw original file retained under `data/uploads/` |
| status | enum: pending, processed, failed | |
| row_count | int, nullable | rows successfully ingested |
| error_message | text, nullable | |
| uploaded_at | datetime | |

### ga4_sessions_daily
Grain: property x date x source/medium/campaign.
| column | type | notes |
|---|---|---|
| id | int PK | |
| property_id | FK properties | indexed with date |
| upload_id | FK uploads | |
| date | date | |
| session_source | str | GA4 session source |
| session_medium | str | |
| session_campaign | str, nullable | |
| landing_page | str, nullable | |
| sessions | int | |
| engaged_sessions | int, default 0 | |
| total_users | int, default 0 | |
| key_events | int, default 0 | GA4 conversions |
| is_ai_referral | bool, default false, indexed | stamped by classifier at ingest |
| ai_platform | str, nullable | e.g. chatgpt, perplexity; from reference JSON |

Indexes: (property_id, date), (is_ai_referral, date).

### gsc_performance_daily
Grain: property x date x query x page (query/page nullable for aggregate exports).
Columns: id, property_id FK, upload_id FK, date, query (nullable), page (nullable), clicks int, impressions int, ctr float, position float. Index (property_id, date).

### gbp_metrics_daily
Grain: property x date. Columns: id, property_id FK, upload_id FK, date, search_impressions int, maps_impressions int, website_clicks int, calls int, direction_requests int. Unique (property_id, date). GBP export field names vary by export vintage; the Phase 4 ingester maps whatever the real export uses into these five metrics and flags anything it cannot place.

### paid_media_daily
Grain: property x date x platform x campaign. Columns: id, property_id FK, upload_id FK, date, platform str (google_ads, meta, other), campaign_name str, impressions int, clicks int, spend Numeric(12,2), conversions float. Index (property_id, date).

### crm_leads
One row per lead, populated through a CRMAdapter only. Grain and statuses normalized here regardless of source CRM.
| column | type | notes |
|---|---|---|
| id | int PK | |
| property_id | FK properties | |
| upload_id | FK uploads | |
| external_lead_id | str | ID in the source CRM; unique with property_id |
| lead_source_raw | str | exactly as the CRM export says |
| lead_source_normalized | str, nullable | beacon taxonomy, mapped by adapter |
| status | enum: lead, tour, application, lease, lost | furthest stage reached |
| first_contact_date | date | |
| tour_date / application_date / lease_signed_date / move_in_date | date, nullable | |

Indexes: (property_id, first_contact_date), (property_id, lease_signed_date).

### data_connections
Google account connections for future OAuth integrations (GA4 Data API, GSC API, GBP APIs, Google Ads API). Schema exists now; no OAuth code until after the manual-CSV dashboards work and Tina explicitly says go.
| column | type | notes |
|---|---|---|
| id | int PK | |
| source_type | enum: ga4, gsc, gbp, paid_media, crm | |
| account_name | str | human-readable account label |
| external_account_id | str | e.g. GA4 property ID, GSC site URL, Ads customer ID |
| oauth_status | enum: disconnected, connected, expired, revoked, error | |
| last_sync_at | datetime, nullable | |
| sync_frequency | enum: manual, hourly, daily, weekly | |
| sync_status | enum: idle, syncing, error, disabled | |
| error_message | text, nullable | |
| created_at | datetime | |

### sync_jobs
One row per sync run against a connection; synced data rows point here the way uploaded rows point at `uploads`.
| column | type | notes |
|---|---|---|
| id | int PK | |
| connection_id | FK data_connections | |
| source_type | enum, same values as uploads | |
| report_type | str, nullable | which report/dimension set was pulled |
| endpoint | str, nullable | API endpoint used |
| date_start / date_end | date, nullable | range the sync covered |
| started_at / completed_at | datetime (completed nullable) | |
| status | enum: running, completed, failed | |
| rows_imported / rows_updated | int | |
| error_message | text, nullable | |

### rag_chunks
Registry of what lives in ChromaDB so citations resolve to real rows (Phase 7 populates).
Columns: id, chroma_id str unique, property_id FK nullable (null = portfolio-level chunk), source_table str, source_ref str (IDs/range within that table), period_start date nullable, period_end date nullable, created_at. Chunk text and vectors live in ChromaDB; SQLite holds the provenance.

### nora_conversations / nora_messages
- nora_conversations: id, title nullable, property_id FK nullable (scope), created_at.
- nora_messages: id, conversation_id FK, role enum (user, assistant), content text, citations JSON nullable (list of {property, date_range, source_table, source_ref}), gate_passed bool nullable (set on assistant messages that touched correlation), created_at.

### reports
id, report_type enum (weekly, monthly, quarterly, executive), property_id FK nullable (null = portfolio), period_start date, period_end date, content_md text, citations JSON, created_at.

## 4. Reference Data Format

`backend/app/reference_data/ai_referrer_domains.json`:

```json
{
  "version": "2026-07-04",
  "platforms": [
    {
      "key": "chatgpt",
      "label": "ChatGPT",
      "referrer_domains": ["chat.openai.com", "chatgpt.com"],
      "utm_sources": ["chatgpt.com", "openai"]
    }
  ]
}
```

Matching rules (Tier 1, the only tier):
1. Referrer/source domain exact or subdomain-suffix match against `referrer_domains`.
2. Else `utm_source` (or GA4 `session_source`) case-insensitive match against `utm_sources`.
3. First platform match wins; stamp `is_ai_referral=true` and `ai_platform=key`.

Initial platform list (Phase 3, verified against real exports before shipping): ChatGPT, Perplexity, Microsoft Copilot, Google Gemini, Claude, Meta AI, You.com, Poe, Phind, DuckDuckGo AI. The JSON is the single source; no domain lists hardcoded in Python.

## 5. Cross-Cutting Mechanisms

### 5.1 Undercount disclosure
`app/constants.py` defines `AI_TRAFFIC_DISCLOSURE` (exact PRD copy). Every API schema that carries an AI traffic figure includes a `disclosure` field defaulted to it; the frontend metric components render it unconditionally. One constant, no copies.

### 5.2 Correlation hard gate
`services/correlation.py`, signature fixed by CLAUDE.md:

```python
def can_claim_correlation(ai_sessions, leases, r, periods_confirmed) -> bool:
    return ai_sessions >= 30 and leases >= 5 and abs(r) >= 0.5 and periods_confirmed >= 2
```

Nora's pipeline computes the inputs from SQLite, calls the gate, and on `False` returns the fixed insufficient-data template (which lists the unmet thresholds). The generation call never sees an ungated correlation prompt.

### 5.3 Data provenance and freshness envelope

Metrics API responses (Phase 6) carry a provenance envelope next to every dataset: source, date range covered, last updated timestamp (max upload/sync time for the rows shown), and a freshness warning flag when the data is stale for its expected cadence. Frontend metric components render all four unconditionally, exactly like the disclosure. Synced data uses the fixed product language: "Auto-sync", "Scheduled sync", "Near real-time where supported", "Last updated", freshness status. Google-connected data is never described as fully real-time unless the specific API supports it.

### 5.4 Citations
The retriever returns chunks joined to `rag_chunks` provenance. Response assembly builds the citations list from those rows and attaches it to the message/report record and API response. Generation is asked to reference them, but the citation data itself never depends on model output.

## 6. Phase Plan

Order is mandatory; each phase must run and be testable before the next starts. Stop after each phase, summarize, show tests, wait for confirmation.

1. **Schema + Alembic migrations.** All Section 3 tables, initial migration, `alembic upgrade head` works on a fresh DB, FastAPI app boots with a `/api/health` endpoint, pytest verifies tables exist and health responds. `constants.py` disclosure constant lands here.
2. **GA4 + GSC ingestion.** Upload endpoints + parsers for manual exports, upload provenance, validation errors surfaced. Tested with fixture files; ready for real exports.
3. **AI referral classifier (Tier 1).** Reference JSON + matcher, stamping at ingest, backfill command for already-ingested rows. Tested against real GA4 exports.
4. **GBP + paid media ingestion.** Same upload pattern.
5. **CRMAdapter + Yardi placeholder.** `crm_base.py` interface; `yardi_adapter.py` with PLACEHOLDER mapping and loud warning block; obviously fake column names only. The interface is transport-agnostic (normalized records in, `crm_leads` rows out) so a future CRM API feed reuses the same adapter unchanged.
6. **Dashboards.** Next.js app, portfolio + property views, read-only, disclosure wired into metric components. No Nora UI.
7. **RAG.** Chunker (per property x period x source summaries), embeddings, ChromaDB collections, retriever, `rag_chunks` registry.
8. **Nora.** Chat endpoint + panel: retrieve, compute gate inputs, gate, generate via Responses API, assemble citations.
9. **Reports.** Weekly/monthly/quarterly/executive, same pipeline as Nora, stored in `reports`.
10. **Polish.** Dark mode quality, charts, filtering speed.

### Phase 15 - Semantic Intelligence & Hybrid Retrieval (split approved 2026-07-08)

Tina's Semantic Intelligence spec (originally titled "Phase 12"; renumbered - 12
is the AI Visibility Scanner), split into three sub-phases so the accuracy wins
land first and the scale-dependent pieces wait for data volume. Standing
constraints: deterministic only, LLM never ranks or decides evidence, metadata
never replaces chunk text, no fabricated confidence scores (matched rules are
the explanation), all existing tests keep passing.

- **15a - Enrichment + taxonomy (COMPLETE 2026-07-08).** Shared
  `app/services/semantic/` layer + versioned reference JSONs
  (semantic_topics/intents/entities/normalization/negation). Negation-aware
  matching fixes the Phase 11 literal-matching limitation; every indexed chunk
  is stamped with topics/entities/intents/per-topic sentiment/normalized terms
  in `rag_chunks.enrichment` and filterable Chroma metadata. Review
  Intelligence consumes the negation layer.
- **15b - Hybrid retrieval + rerank + debug (COMPLETE 2026-07-12).** Metadata
  pre-filtering (property/source/topic) before vector search, keyword and
  stopword-filtered phrase matching alongside vector similarity, a
  configurable deterministic reranker (weights in `rag_retrieval.json`:
  semantic similarity 0.5, keyword 0.2, phrase 0.1, topic 0.1, entity 0.05,
  data-relative recency 0.05; ties break on chroma_id), and the
  developer-only `GET /api/admin/retrieval-debug` "matched because" view.
  Nora inherits through the existing retriever unchanged.
- **15c - Clustering + consolidation.** Deterministic similarity clustering
  (complaint clusters, repeated renter questions) once data volume justifies
  it; older module KBs consolidated onto the shared taxonomy.

**Future, outside the numbered phases (requires explicit go):** Google OAuth connections in `services/sync/` — GA4 Data API, Google Search Console API, Google Business Profile APIs, Google Ads API. Populates `data_connections`/`sync_jobs` and writes data rows with `sync_job_id` provenance. Not started before Phase 6 dashboards work, per CLAUDE.md.

**Further out, placeholder only (no API available):** CRM API connection. No CRM API access exists today. If ever granted, it rides the same rails: `data_connections` row with `source_type=crm`, runs in `sync_jobs`, `crm_leads` rows with `sync_job_id` provenance, field mapping through the same CRMAdapter as manual exports. Nothing is built for this until explicitly instructed; the schema and adapter interface are already shaped for it.

## 7. Dev Environment

- Python 3.12, venv at `backend/.venv`, deps in `backend/requirements.txt` (added per phase; Phase 1: fastapi, uvicorn, sqlalchemy, alembic, pydantic-settings, pytest, httpx).
- DB file `backend/beacon.db` (gitignored); tests use throwaway temp DBs.
- Run: `uvicorn app.main:app --reload --port 8600` from `backend/`; frontend `npm run dev -- --port 3100` from `frontend/` (3000 is often taken by other local apps; both origins are CORS-allowed). Launch configs `beacon-backend` / `beacon-frontend` exist in ~/Builder/.claude/launch.json.
- ChromaDB persistent dir `backend/.chroma` (Phase 7); `OPENAI_API_KEY` via `backend/.env` (never committed).
