# CLAUDE.md — Beacon Build Instructions

This file is read automatically by Claude Code. It is the source of truth for how to build Beacon. Full context lives in `docs/beacon-prd-v2.md` (product decisions) and `docs/beacon-build-plan-v1.md` (schema, folder structure, architecture) — read both before writing code.

## What Beacon Is

Internal, single-user AI performance intelligence dashboard for multifamily marketing (built for Yardi/REACH workflow, not yet a packaged product). Tracks AI referral traffic, ties it to CRM/lease outcomes, and surfaces an analyst (Nora) that explains trends using only retrieved, cited data — never fabricated recommendations.

## Stack (do not deviate without asking)

* Backend: FastAPI (Python)
* DB: SQLite + SQLAlchemy + Alembic migrations
* Vector store: ChromaDB
* Frontend: Next.js (React, App Router), dark-mode first
* AI: OpenAI Responses API for both RAG and embeddings
* No authentication in this phase

## Hard Rules

1. Build in the phase order below. Do not skip ahead. Each phase should run and be testable before starting the next. A dashboard with real ingested data must exist before any Nora/RAG code is written.
2. Tier 1 AI detection only. Referrer/domain/UTM matching against `backend/app/reference_data/ai_referrer_domains.json`. Do not build server-log parsing (Tier 2) or behavioral/ML detection (Tier 3) — both are explicitly deferred per the PRD.
3. Every AI traffic number displayed anywhere must carry the undercount disclosure ("This reflects AI traffic that passed referrer data. Actual AI-influenced traffic is likely higher.") — this is not optional copy, wire it into the component/response layer so it can't be dropped.
4. The Yardi CRM field mapping in `yardi_adapter.py` is a placeholder. Write it with an obviously fake mapping (e.g. `"PLACEHOLDER_LEAD_SOURCE_COLUMN"`) and a loud comment block at the top of the file. Do not invent realistic-looking Yardi column names — that risks the placeholder being mistaken for real and shipped silently.
5. Nora's correlation rule is a hard gate, implemented as code, not a prompt instruction alone:

```python
def can_claim_correlation(ai_sessions, leases, r, periods_confirmed) -> bool:
    return ai_sessions >= 30 and leases >= 5 and abs(r) >= 0.5 and periods_confirmed >= 2
```

Nora's response generation must call this before producing any AI-traffic-to-lease language. If `False`, use the fixed "not enough data yet, here's what's missing" template — do not let the model free-generate around this gate.
6. Every Nora answer must cite what it retrieved (property, date range, source table/report ID) — implement this as part of the RAG response assembly, not as a prompt request.
7. No em dashes in any user-facing copy or generated report text. Calibri is a Word-doc-only convention and doesn't apply here.

## Google Account Connections (deferred — schema only for now)

* Beacon will eventually connect to Google accounts via OAuth 2.0: GA4 Data API, Google Search Console API, Google Business Profile APIs, Google Ads API. Manual CSV upload remains the ingestion method until then.
* Do not build Google OAuth before the manual CSV dashboards (Phase 6) are working, unless explicitly instructed.
* Schema support already exists so OAuth lands without rewrites: `data_connections` + `sync_jobs` tables, and dual provenance (`upload_id` / `sync_job_id`, at least one required) on every data table.
* Product language for synced data: "Auto-sync", "Scheduled sync", "Near real-time where supported", "Last updated" timestamp, data freshness status. Never describe Google-connected data as fully real-time unless the specific API supports it.
* Every dashboard component using synced data must display: source, date range, last updated timestamp, and a data freshness warning when applicable. Wire this like the undercount disclosure: in the response/component layer, not as optional copy.

## CRM API Connection (placeholder — no API available)

* There is currently no API access to the CRM. CRM data arrives only as manual exports through the CRMAdapter (Phase 5).
* If API access is ever granted, it connects through the same path as Google: a `data_connections` row with `source_type=crm`, sync runs recorded in `sync_jobs`, lead rows written with `sync_job_id` provenance, and the CRMAdapter doing the field mapping. No schema changes should be needed.
* The Phase 5 CRMAdapter interface must therefore be transport-agnostic: it maps normalized records regardless of whether they came from a file export or a future API feed.
* Do not build any CRM API client until explicitly instructed. Same placeholder discipline as the Yardi mapping applies: nothing that looks like a real endpoint, credential, or field name.

## RAG Readiness (no RAG code yet)

* Do not build RAG, embeddings, the vector store, Nora, or any AI-generated analysis until Phases 7-8. Beacon is currently structured ingestion, classification, and dashboards only.
* But every ingested or synced dataset must already carry citation-grade provenance so Phase 7 lands cleanly. Uploads preserve: source name, import method, source account, filename, covered date range, imported-at timestamp, property mapping, and the raw original file on disk (`data/uploads/`, kept even for failed ingests). Data rows carry their source file line number (`source_line`); CRM leads carry `external_lead_id`. Metric type is encoded by the table itself.
* Future Google syncs get the same treatment via `sync_jobs`: product source, account/property/location/customer ID (on the connection), report type, endpoint, date range, sync job ID, timestamps.
* Any new ingestion path added in later phases (GBP, paid media, CRM) must capture this same provenance set from day one.

## Phase Plan (from build-plan-v1.md, Section 6)

* [x] Phase 1: Schema + Alembic migrations
* [x] Phase 2: GA4 + GSC ingestion (manual CSV/export upload)
* [x] Phase 3: AI referral classifier (Tier 1) — built and tested; validation against a real source-level GA4 export still open (the only real export on hand is channel-group grain, no session source; correctly rejected by the parser)
* [x] Phase 4: GBP + paid media ingestion
* [x] Phase 5: CRMAdapter interface + Yardi adapter (placeholder mapping)
* [x] Phase 6: Core + property dashboards (frontend, read-only, no Nora yet)
* [x] Phase 7: RAG — chunking, embeddings, retriever (pipeline complete and tested with a local deterministic embedder; building the real index awaits BEACON_OPENAI_API_KEY in backend/.env, then `python -m app.cli.index_rag`)
* [x] Phase 8: Nora — wired to correlation engine + citation mechanism (fully built and tested with fake LLM/embedder; live embeddings + generation blocked on OpenAI billing: the saved key returns insufficient_quota until a payment method/credits are added, then run `python -m app.cli.index_rag` and Nora works)
* [x] Platform Architecture (inserted 2026-07-05, numbered "Phase 9" in that request; distinct from the Reports phase below): provider abstraction, connector architecture, automatic RAG synchronization queue, expanded chunk registry, sync dashboard, future-module hooks. See README section 6a.
* [x] Content Intelligence (2026-07-05, numbered "Phase 10" in that request): deterministic content-reasoning engine (keyword intent, renter question coverage, neighborhood, freshness, opportunities, explainable score), content storage on the ContentProvider seam, configurable JSON knowledge bases, CI API + dashboard, Nora integration. No external AI for analysis. See README section 6b.
* [x] Property Context (2026-07-05, "Phase 10.5"): operator-asserted property-context layer (property_profile) + configurable vocabulary/gating rules in property_context.json + reusable deterministic gating utility + property_context RAG chunk + CRUD/editor. HARD RULE: regulatory/program/type status is operator-asserted, NEVER inferred; is_regulated null = UNKNOWN (never "not regulated"); unknown withholds compliance-sensitive guidance with the fixed message. Content Intelligence consumes it. See README section 6c.
* [x] Review Intelligence (2026-07-05, "Phase 11"): property_reviews storage (partial-unique dedup on non-null external_review_id) + ReviewProvider impl (signature unchanged, ReviewRecord extended additively) + review CRUD API + deterministic review engine (app/services/review_intelligence/, no external AI) + 4 JSON knowledge bases + per-review and review_intelligence RAG chunks (replace-on-write, stale cleanup on delete) + Nora review Q&A + /review-intelligence dashboard. All recommendations/marketing insights gated via the Phase 10.5 gate(); property type/status never inferred from reviews. Matching is literal (negation not detected, documented). See README section 6d.
* [ ] Reports (weekly/monthly/quarterly/executive) — originally listed as Phase 9; still pending
* [ ] Polish — dark mode, chart quality, filtering speed
* [ ] Future (requires explicit go): Google OAuth connections — GA4 Data API, GSC API, GBP APIs, Google Ads API (now shaped as connector `*Provider` implementations)

## Working Style

* After finishing each phase, stop, summarize what was built, run/show tests, and wait for confirmation before starting the next phase.
* Flag any assumption made about data formats (especially anything Yardi-related) clearly rather than silently guessing.
* If a phase reveals that an earlier schema decision needs to change, say so explicitly rather than quietly patching around it.
