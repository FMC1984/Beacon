# Beacon PRD v2

> Status: Drafted 2026-07-04 by Claude from CLAUDE.md constraints, after the original
> beacon-prd-v2.md could not be located on this machine or in Drive. Tina approved
> drafting these docs fresh. If the original ever resurfaces, reconcile against it.

## 1. Problem

Multifamily marketing teams (Yardi/REACH workflow) are starting to receive meaningful traffic from AI assistants (ChatGPT, Perplexity, Copilot, Gemini, and others). None of the standard tooling answers three questions:

1. How much of a property's traffic is AI-referred, and how is it trending?
2. Does AI-referred traffic actually turn into leads, tours, and leases?
3. What should a marketer do about it, grounded in that property's real numbers rather than industry hand-waving?

GA4 sees only the fraction of AI traffic that passes a referrer or tagged URL. CRMs attribute lead source with their own taxonomy that never says "ChatGPT." Nobody joins the two.

## 2. What Beacon Is

An internal, single-user AI performance intelligence dashboard. One user (Tina), running locally. Not a packaged product, no billing, no tenants, no auth in this phase.

Beacon does three things:

1. **Measures AI referral traffic** from manually uploaded GA4/GSC/GBP/paid-media exports, using Tier 1 detection (referrer domain + UTM matching) only.
2. **Ties traffic to outcomes** by ingesting CRM lead/lease exports through a CRMAdapter interface (Yardi adapter ships with an explicitly fake placeholder field mapping until real export samples exist).
3. **Explains trends via Nora**, a retrieval-grounded analyst that answers questions and writes reports using only retrieved, cited data. Nora never fabricates recommendations and is hard-gated in code from claiming AI-traffic-to-lease correlation before statistical minimums are met.

## 3. Users

One: Tina, digital marketing manager working multifamily accounts on the Yardi/REACH stack. Comfortable with GA4 exports and CSVs. Wants defensible numbers she can put in front of clients and regional managers.

## 4. Core Product Decisions

### 4.1 AI traffic detection is Tier 1 only

Detection = matching session referrer domain, source, or UTM parameters against a maintained reference list (`backend/app/reference_data/ai_referrer_domains.json`) covering known AI platforms.

- **Tier 2 (server log parsing) and Tier 3 (behavioral/ML detection) are explicitly deferred.** Do not build them. Do not scaffold for them.
- Detection runs at ingestion time and stamps each traffic row with `is_ai_referral` and `ai_platform`, so dashboards and Nora query a stored fact, not a runtime heuristic.

### 4.2 The undercount disclosure is structural

Tier 1 detection systematically undercounts (AI assistants often strip referrers; dark traffic lands as direct). Every AI traffic number shown anywhere (dashboard, Nora answer, report) must carry this exact copy:

> This reflects AI traffic that passed referrer data. Actual AI-influenced traffic is likely higher.

This is wired into the API response layer and frontend components so it cannot be dropped by accident. It is a single constant in one place in the backend.

### 4.3 Nora is grounded or silent

- Nora answers only from retrieved chunks of Beacon's own ingested data (RAG over ChromaDB). No general-knowledge recommendations dressed up as analysis.
- Every answer carries citations: property, date range, and source table/report ID for each retrieved chunk. Citation assembly is part of the response pipeline, not a prompt request.
- **Correlation hard gate**: Nora may make any AI-traffic-to-lease correlation claim only when, computed in code:
  - AI sessions in the analysis window >= 30
  - Leases in the analysis window >= 5
  - |Pearson r| >= 0.5
  - Confirmed in >= 2 distinct periods
- If the gate fails, Nora returns a fixed template stating there is not enough data yet and listing exactly which thresholds are unmet. The model does not free-generate around this.

### 4.4 CRM integration is adapter-shaped, Yardi first

A `CRMAdapter` interface normalizes any CRM export into Beacon's lead/lease schema. The first implementation is `yardi_adapter.py`, whose field mapping is a **loudly fake placeholder** (`"PLACEHOLDER_LEAD_SOURCE_COLUMN"` style) until real Yardi export samples are in hand. Realistic-looking invented Yardi column names are forbidden; a placeholder that looks real could ship silently.

**CRM API (placeholder, no API available today):** there is currently no API access to the CRM, and none is assumed. If access is ever granted, it uses the same connection framework as Google (a `data_connections` row with `source_type=crm`, runs in `sync_jobs`, leads written with sync provenance) and the same CRMAdapter for field mapping, so nothing needs rearchitecting. The adapter interface is transport-agnostic for this reason. No CRM API code is written until Tina explicitly says so, and the synced-data display rules in 4.6 (source, date range, last updated, freshness) would apply to CRM data the same as Google data.

### 4.5 Ingestion is manual upload in this phase

GA4, GSC, GBP, paid media, and CRM data arrive as manually exported CSV/report files uploaded through the UI (or API). No live API integrations in this phase. Every upload is recorded with row counts and status so bad files are visible and re-ingestable. Re-uploads replace existing rows for the property on the dates the file covers, so corrected exports are safe and double-counting is impossible.

### 4.6 Google account connections (planned, deferred)

Beacon will eventually connect directly to Google accounts using OAuth 2.0: GA4 Data API, Google Search Console API, Google Business Profile APIs, and Google Ads API. Manual CSV upload remains the ingestion method until the manual-CSV dashboards work; no OAuth code is built before then unless explicitly instructed.

What exists now is schema support only, so the integration lands without rewrites: a `data_connections` table (account, OAuth status, sync frequency/status, last sync), a `sync_jobs` table (per-run outcomes), and dual provenance on every data table (each row references an upload or a sync job).

Product language for synced data, fixed:

- "Auto-sync" and "Scheduled sync" for the mechanisms
- "Near real-time where supported" - never describe Google-connected data as fully real-time unless the specific API supports it
- "Last updated" timestamp
- Data freshness status

Every dashboard component using synced data must display source, date range, last updated timestamp, and a data freshness warning when applicable. Like the undercount disclosure, this is wired into the response/component layer, not left as optional copy.

### 4.7 RAG-ready before RAG exists

No RAG, embeddings, vector store, Nora, or AI-generated analysis is built until Phases 7 and 8. However, every dataset entering Beacon is stored with citation-grade provenance from day one, so the retrieval layer can be added later without re-ingesting anything:

- Per upload: source name, import method (manual upload vs future sync), source account, filename, covered date range, imported-at timestamp, property mapping, and the raw original file retained on disk (even for failed ingests).
- Per data row: source file line number where available; CRM leads use their external lead ID. Metric type is encoded by which table the row lives in.
- Per future sync run: Google product source, account/property/location/customer ID, report type, endpoint, date range, sync job ID, and timestamps, so Nora can cite synced data as precisely as uploaded data.

## 5. Feature Summary by Area

- **Portfolio dashboard**: AI traffic share, trend, platform mix across all properties; undercount disclosure on every AI figure.
- **Property dashboard**: same cuts for one property, plus lead/lease funnel overlay once CRM data exists.
- **Uploads**: per-source upload screens with validation feedback and ingest history.
- **Nora**: chat panel scoped to portfolio or property; cited answers; gated correlation language.
- **Reports**: weekly, monthly, quarterly, and executive summaries generated from the same retrieval + gate + citation pipeline as Nora. No em dashes in any generated copy.

## 6. Non-Goals (this phase)

- Authentication, multi-user, multi-tenant anything
- Tier 2 / Tier 3 AI detection
- Live GA4/GSC/GBP/ads/CRM API connections (planned via OAuth, see 4.6; schema support exists, no OAuth code this phase)
- Real Yardi field mapping (placeholder only until real export samples exist)
- Packaging, deployment, billing

## 7. Copy Rules

- No em dashes in any user-facing copy or generated report text.
- The undercount disclosure copy in 4.2 is fixed; do not paraphrase it.
- Nora writes in plain, direct prose and never implies causation where the gate has only confirmed correlation.

## 8. Success Criteria

- Real GA4 exports classify correctly against the reference list (Phase 3 is tested against real exports, not synthetic fixtures alone).
- Dashboard loads with real ingested data before any Nora/RAG code exists.
- Every AI number on screen carries the disclosure; every Nora answer carries citations; the correlation gate is demonstrably unpassable with thin data.
