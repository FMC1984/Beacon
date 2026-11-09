# CiteRoll: what is built, what is next, and why

Last written 2026-11-07. This is the orientation document: the shape of the
product, the state of the build, and the reasoning behind the choices that are
not obvious from the code. Operational detail lives in `README.md`, build rules
in `CLAUDE.md`, session-by-session history in `HANDOFF.md`, and product
decisions in `docs/citeroll-prd-v2.md`.

## The product in one paragraph

CiteRoll tells an apartment marketer whether AI assistants name their community
when a renter asks where to live, why or why not, what to fix first, and
whether the fix worked. It asks a library of renter questions on a schedule,
stores every answer with its citations, scores each answer for every property
in that market, and rolls the results into four headline numbers that open onto
the evidence behind them. It is built for multifamily and housing authorities,
and it is deliberately strict about what it will and will not claim.

## Why it exists

The shortlist moved. An AI answer names three to five communities, and a
property that is not named earns nothing. Being eighth in organic search still
earned a click; being absent from an AI answer does not. Nothing in a
marketer's existing toolset reports this: GA4 sees only AI visits that passed a
referrer, Search Console does not expose AI answer impressions through its API,
and ILS reporting covers the ILS.

Three secondary problems made the product worth building rather than just
measuring presence. AI states facts about pet policies, pricing and eligibility
confidently and sometimes wrongly, which for regulated and affordable housing
is a compliance exposure. Property websites often load pricing and floor plans
through scripts a plain crawler never runs, so the site is unreadable to the
thing doing the recommending. And teams change a page or a listing and never
learn whether anything moved.

## The architecture, and the reasoning

- **FastAPI + SQLite/Alembic + ChromaDB backend, Next.js App Router frontend.**
  Single-tenant-shaped data with a tenant-ready schema, so the Postgres move
  later is a migration and not a rewrite.
- **Deterministic first.** Every intelligence module (Content, Review, AI Query
  Signals, AI Visibility, Competitor, Opportunity Engine) is rule based and
  explainable. The only non-deterministic calls in the system are OpenAI
  embeddings, Nora's generation step, and asking an AI platform a question.
  Everything downstream of those is deterministic parsing. The reason is
  defensibility: a number a marketer has to defend to a regional manager cannot
  come from a model's judgment.
- **Provenance before retrieval.** Phases 1 through 6 captured citation-grade
  provenance on every ingested row (source name, import method, filename,
  covered date range, imported-at timestamp, property mapping, source line, and
  the raw original file kept on disk even for failed ingests) before any RAG
  code existed. That is why Phase 7 landed without a schema rewrite.
- **Honesty wired into the response layer, not the copy.** Four labels on every
  figure: OBSERVED (reported by the provider), MEASURED (counted by CiteRoll),
  MODELED (produced by a stated rule), UNAVAILABLE (not knowable, so not
  shown). Rates are withheld below a minimum sample. The AI traffic undercount
  disclosure is a fixed constant that cannot be paraphrased away.
- **Hard gates in code, not prompts.** Nora cannot claim a correlation between
  AI traffic and leases unless there are 30 or more AI sessions, 5 or more
  leases, an absolute r of at least 0.5, and 2 or more confirmed periods. Below
  that she returns a fixed template and the model is never called. Regulatory
  status and property type are operator asserted and never inferred; unknown
  withholds compliance-sensitive guidance rather than guessing.
- **Placeholders that cannot be mistaken for real.** The Yardi CRM field
  mapping uses obviously fake column names with a guard test
  (`test_yardi_mapping_is_loudly_fake`) that fails on anything realistic. There
  is no CRM API access, so inventing plausible field names would risk shipping
  a fake mapping silently.

## What is built

1049 automated tests, all passing as of 2026-11-08. Deployed on Render.
Organized the way the sidebar is, as the six questions a property team asks in
order.

**Set up.** Per-property setup checklist (identity, data, facts, competitors,
prompts, monitoring) that states what is missing and what each step unlocks.
The fact layer: typed values a person records (fees, pet rent, parking,
laundry, waitlist status, per-bedroom rent, and for regulated properties income
limits with their effective year, programs, voucher acceptance and how to
apply), each with provenance and a review-by date. A fact past its review date
is withheld from error reporting and from drafts until someone reconfirms it,
and going stale raises an alert, because a fact nobody has confirmed produces
silence rather than a wrong answer.
GA4 and Search Console auto-sync, plus CSV import for GA4, GA4 events, Search
Console, Business Profile, CRM leads and reviews. Property Context (type,
audience, regulatory status, marketing restrictions), always entered by a
person. Neighborhood. Tracked competitors, confirmed by a person.

**Watch.** A prompt library generated per market and per property: market,
feature, brand and comparison questions, plus segment questions chosen by
property type (55+, lease by the bedroom, income restricted) and five renter
personas. Shared market scoring, where one answer about a market scores every
property in it with no second API call. Four headline numbers with formula,
sample size and label: AI Visibility, Citation Rate, Share of Voice,
Recommendation Rate. Market rank and comp-set rank. Benchmarks against other
monitored properties, never named, minimum three comparables. A per-platform
table with honest status (live, ready without a key, planned, no API).

**Understand.** Every number opens the answers behind it, with tests enforcing
that the rows add up. Source Influence Matrix (each cited source, its share of
citations, whether the cited page names the property, whether a competitor is
named where the property is not, and a rule-based action). Top citation pages
with a mentioned-on-page check, where an unreadable page is reported as
unreachable and never as silent. Areas of concern per topic with the gap in
points and an explanation built from evidence. Property Truth, comparing each
recorded fact against the site, the listings AI cites, and the AI answers, with
provenance per fact. Rankings by topic, query fanouts, average position,
sentiment with reasons. Content Analysis, Review Analysis, Competitor Analysis,
AI Query Signals.

**Act.** Technical Fix briefs, listing correction briefs and structured data
generated from verified facts: deterministic, forwardable to a web team or a
listing vendor, with the evidence and the date the site was read, and a retest
that refuses to read a check taken before the change went live. Misinformation
incidents: statements in monitored answers that
contradict a fact the operator recorded and confirmed, with how often and on
which platforms, which cited pages state the same value (co-occurrence, never
proof of origin), and a lifecycle where a person can mark a correction sent and
a change live but only CiteRoll can mark it resolved, from a fresh sample of
answers showing the statement is gone. Statements it could not check sit in
their own list with the reason and are never counted as errors. A weekly check
of what a plain crawler reads from the property's own
site without running JavaScript: which renter facts appear, which AI crawlers
robots.txt admits, what structured data is declared. Housing authority sites
are checked on eligibility, how to apply, programs and developments instead.
The Opportunity Engine, one ranked list across every module with evidence,
impact, effort and a Property Context gate. Tracked actions with automatic
retest: after a stated wait CiteRoll re-measures the evidence the action came
from and reports resolved, improved, no change, still there, declined or
inconclusive. Nothing is marked resolved without the evidence moving.

**Prove.** Eight reports (Executive, SEO Performance, GEO Visibility, AEO
Readiness, Content Impact, Audience, AI Share of Voice, Semantic Intelligence).
One definition of AI visibility everywhere, so the GEO report shows the same
numbers as the AI Visibility tab. Content Impact compares before and after a
logged change. AI referral sessions sit beside AI visibility for the same
period, described as association.

**Record.** A compliance audit export per property and period: the questions
monitored, the facts relied on with who confirmed each one, the incidents with
their evidence, the statements CiteRoll could not check, the corrections sent
and what the retest found, and who did what. Stored as issued with a sha256 over
its records, so re-running a period and comparing digests shows whether anything
moved.

**Brief.** Monthly Strategic Briefing with a revocable share link. Alerts on
threshold moves with enough sample, escalating to closer monitoring. Nora, who
answers only from ingested data, cites her excerpts, and declines to name a
cause when the data does not support one.

**Platform and operations.** Provider abstraction and connector architecture
(traffic, lead, lease, review, content). Durable job queue, monthly run
budgets, cost recorded for every AI call including failed ones, adaptive
scheduler (built, switched off), admin operations panel. Automatic RAG
synchronization with a queue and worker. Sample Portfolio of eight fictional
communities in two fictional markets, driven through the real pipeline, badged
as sample on every screen and removable in one click.

**Accounts and billing (September 2026).** Per-user sign-in with opaque session
tokens stored hashed on a 30-day sliding expiry. Organizations with owner,
admin and viewer roles, platform admins who can act as any organization, and
cross-organization requests that answer 404 rather than 403. Stripe Checkout
and Customer Portal priced per monitored community per month with two tiers plus
a one-time audit, signed idempotent webhooks, and soft entitlement (over
quantity shows a banner, no subscription makes writes answer 402). Note that
`docs/citeroll-pitch-brief-v2.md` predates this and still lists client login as
not built.

**Rename (September and October 2026).** The product is CiteRoll, never Beacon,
in all new writing. The customer-visible rename went out in September; the
plumbing followed in October, carrying 32 environment variables to the
`CITEROLL_` prefix, both request headers, six browser storage keys, and 16
customer-visible export filenames. Three stores keep the old name on purpose
because renaming them would orphan live data: the SQLite file, the Render disk,
and the GitHub repository.

## What is next, and why that order

1. **The public landing page and the domain.** Both are open decisions. The
   app's `/` is the portfolio dashboard behind a login, and Render's free plan
   cold-starts by roughly 30 seconds, so the leading option is a separate
   static host. The domain is unresolved: citeroll.ai was chosen but may never
   have been purchased, and citeroll.com is held by a parked registration
   created 2026-02-27 with a drop window around April to May 2027 only if the
   holder lapses.
2. **Reposition the landing copy on method, not market.** The November 2026
   competitive research (`~/Builder/citeroll-competitive-brief.md`) found that
   multifamily is occupied, not open. At least four vendors sell AI visibility
   specifically for apartment communities, RealPage has shipped Agentic Search
   Optimization, and three competitors run near-identical hero copy to the
   current page. Vertical focus is no longer the wedge. What survives is
   method: auditable numbers against opaque scores, retests that report
   failure, and independence from the vendor who also sells the website. The
   two refusals (no AI search volume, no impressions) are strong against
   horizontal tools and answer an unasked question in multifamily, so they
   belong on the labels page rather than the hero.
3. **Portfolio pattern detection.** Group the same issue across properties, for
   example floor plans missing from raw HTML on 67 of 412 communities across
   four site templates, so an enterprise sees the handful of systemic problems
   behind most gaps.
4. **AI Misinformation Incidents: the approved set is built.** The plan is
   `docs/citeroll-incidents-plan-v1.md`, which absorbed the earlier Content Fix
   workspace plan: the briefs and the drafts are resolution tools hanging off
   an incident rather than standalone features. All four approved phases
   shipped on 2026-11-08: 1A (the fact layer), 1B (detection with source
   tracing and the incident lifecycle), 1C (the deterministic briefs,
   structured data from verified facts, and portfolio grouping) and 3.1 (the
   compliance audit export: one stored, checksummed document per property per
   period, framed as tamper-evident rather than tamper-proof). Deferred by
   decision: the drafting workspace, share links that let a vendor write back,
   lead source capture, the AI Influence report (no CRM data exists to read
   yet) and fair-housing review of stored answers. One open decision the export
   surfaced: the claim extractor and the incident extractor disagree about
   whether an incident needs a confirmed fact, and the export prints each
   incident's fact state rather than hiding it.

### Set aside for now

More AI platforms switched on (Gemini, Claude and Perplexity are built and need
keys; the platform rows already exist). Housing authority mode with facts per
development and accuracy rules per development. Similarity clustering and
knowledge-base consolidation onto the shared taxonomy, deferred until there is
enough data volume to cluster meaningfully; the Semantic Intelligence report no
longer waits on it.

### Later

Rendered versus raw readability through a headless browser. Operator-confirmed
listing facts, so a blocked listing site can still be recorded by hand.
Unit-level discoverability, with live inventory treated as volatile until a feed
exists. Bing Webmaster AI performance import when the export stabilizes.
Postgres and an external worker for scale.

### Decided against

Google Business Profile API: discussed and declined. It needs a Google approval
process, has lower strategic fit than GA4 and Search Console, and manual CSV
upload already works. Revisit only if a client leans heavily on Maps presence.

### Deliberately never

Prompt or AI search volume estimates, because nobody can measure them.
Predicted lift from a fix, because CiteRoll measures before and after instead.
Auto-publishing or AI-written outreach, because CiteRoll drafts and shows
evidence while people act.

## Open items worth clearing

- **Stripe keys are unset on purpose**, so billing is off. The default
  organization carries a `billing_override` from the migration, so the founding
  client is never gated.
- **Leftover `BEACON_*` environment variables on Render** should be deleted now
  that `config.py` reads the `CITEROLL_` prefix.
- **Local and hosted are separate databases** and do not sync. Render's daily
  Google auto-sync only touches Render's copy, so local drifts stale. Treat the
  hosted instance as the source of truth.
- **The `-s6yd` suffix on the Render backend URL is load bearing.**
  `beacon-backend.onrender.com` with no suffix is a stranger's Express app.
- **No competitors are added yet for the live client**, so Share of Voice
  reports insufficient data rather than a real number until one or two real
  competitors are named.
- **The AI Visibility weekly autorun is built but off**, left manual by
  decision. Run all now from the Standing and Trend tab, or set the autorun
  variable.
- **The classifier has not been validated against a real source-level GA4
  export.** The only real export seen so far was channel-group grain with no
  session source, and the parser correctly rejected it.
- **`README.md` sections 8 and 9 are stale.** They stop at Phase 11 and still
  describe reports as not started, which the eight shipped reports contradict.

## Hard rules that are still binding

No fabricated data. Operator-asserted fields are never inferred from content.
No em dashes in user-facing copy. The AI traffic undercount disclosure is a
fixed constant and never paraphrased. Every intelligence module states its own
limitations rather than overclaiming, because insufficient data beats a fake
number every time. Citations are assembled in code from the `rag_chunks`
registry and never trusted from model output. Nora's correlation gate is hard
coded. Module names stay plain and descriptive, with no suffix that reads as a
lookalike of another vendor's product naming. Tier 1 AI traffic detection only:
no server-log parsing, no behavioral or ML detection.
