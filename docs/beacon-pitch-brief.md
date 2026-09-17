# Beacon: Pitch Brief

Source material for a pitch deck. Everything under "What Beacon does today" is built, tested and deployed as of September 17, 2026. Everything under "Planned" is not built yet and is labeled that way. Figures marked **[sample]** come from Beacon's fictional Sample Portfolio and must be presented as demo data, never as client results. Items marked **[you supply]** are numbers or decisions only you can provide.

---

## 1. The one-liner

**Beacon shows apartment marketers whether AI assistants recommend their community, why or why not, and what to fix first.**

Alternate phrasings to test:

- "Search Console for AI answers, built for multifamily."
- "When a renter asks ChatGPT where to live, Beacon tells you if you were in the answer."
- "AI visibility you can act on: measured, explained, and never made up."

## 2. The 30-second pitch

Renters now ask AI assistants the questions they used to type into Google: best pet-friendly apartments in a city, which community is near a given employer, whether a specific property is a good place to live. The assistant answers with a short list and a few cited sources. Properties that are not named in that answer are invisible at the moment of decision, and nothing in a marketer's current toolset (GA4, Search Console, the ILS dashboards) reports it.

Beacon asks those questions on a schedule, reads the answers, and turns them into four numbers a regional manager understands, the evidence behind each number, and a ranked list of actions. It is built specifically for multifamily and housing authorities, and it is strict about honesty: every number is labeled as observed, measured, modeled or unavailable, and Beacon never invents "AI search volume."

## 3. The problem

Use these as slide talking points. Add market statistics from sources you trust. **[you supply: current stats on renter use of AI assistants, and on AI answers reducing clicks to websites]**

1. **The shortlist moved.** An AI answer names three to five communities. Being number eight in organic search used to still earn a click. Being absent from an AI answer earns nothing.
2. **It is invisible to existing reporting.** GA4 shows only the AI visits that passed a referrer. Search Console does not report AI answer impressions through its API. ILS reporting covers the ILS. No standard report says "you were named in 40 percent of relevant AI answers."
3. **AI answers lean on third parties.** In Beacon's monitoring, the most-cited sources for apartment questions are directories and listing sites, not property websites. If the listing page an AI cites does not mention your community, the AI cannot recommend you from it.
4. **AI gets facts wrong.** Pet policies, pricing language, amenities and eligibility are stated confidently and sometimes incorrectly. For regulated and affordable housing this is a compliance exposure, not just a marketing problem.
5. **Generic AI visibility tools are not built for housing.** They track brand keywords for software and consumer brands, price per prompt, and present estimated "prompt volumes" that nobody can verify. Multifamily needs market-level questions, per-property scoring, fair housing awareness, and portfolio economics.

## 4. Who it is for

| Audience | What they get |
|---|---|
| Marketing specialists and agencies serving multifamily | A repeatable way to audit, explain and improve AI visibility per property, with client-ready reporting |
| Regional and corporate marketing at owner/operators | Portfolio view: which communities are visible, which are not, and where the same gap repeats |
| Housing authorities and affordable operators | Monitoring of how AI describes programs, eligibility and how to apply, with context-aware guardrails |
| Owners and asset managers | A monthly briefing in plain language with a shareable link |

## 5. What Beacon does today

Beacon is organized as the six questions a property team asks, in order. The sidebar follows the same flow.

### Stage 1. Set up: "Is this property ready to be scored?"

- A per-property **setup checklist** with six steps (identity, data, facts, competitors, prompts, monitoring). Each step says what is missing, what it unlocks, and links to where to do it. Pages that depend on a missing step show a "finish setup" banner instead of an empty screen.
- **Google Analytics 4 and Search Console auto-sync**, plus CSV import for GA4, GA4 events, Search Console, Google Business Profile, CRM leads and reviews.
- **Property Context**: property type (conventional, luxury, student, senior, active adult, affordable, mixed income, military), target audience, regulatory status and marketing restrictions. This is always entered by a person and never guessed. It gates every recommendation Beacon makes.
- **Tracked competitors**, confirmed by a person. Beacon suggests names AI answers keep mentioning, and nothing counts as a competitor until someone confirms it.

### Stage 2. Watch: "Are we visible in AI answers?"

- A **prompt library generated for each market and property**: market questions ("best apartments in {city}"), feature questions (pets, parking, pool, EV charging, schools, transit and more), brand questions ("is {property} a good place to live?"), competitor comparisons, and segment questions chosen by property type (for example "is {property} a 55+ community?" for senior housing).
- **Regions and audiences**: a neighborhood entered on the property adds neighborhood-level questions; five renter personas (relocating professional, family, retiree, voucher holder, student) add audience-specific questions.
- **Shared market scoring**: one AI answer about a market is scored for every subscribed property in that market with no second API call. This is the core cost advantage for portfolios.
- **Four headline numbers**, each with its formula, its sample size and a data label:
  - **AI Visibility**: share of monitored answers that name the property
  - **Citation Rate**: share that cite the property's own website
  - **Share of Voice**: the property's mentions against tracked competitors
  - **Recommendation Rate**: share that place it among the top picks (rule-based, labeled MODELED)
- Also measured: citation share, prompt coverage, competitor win rate, average position among named brands, sentiment around each mention.
- **Benchmarks**: the property's numbers beside the average of other monitored properties, overall and for the same property type. Requires at least three comparable properties; otherwise it says unavailable and why. Peers are never named.

### Stage 3. Understand: "Why, and who wins instead?"

- **Click any number to see the answers behind it.** Every metric and every report card opens the exact rows it was computed from, and tests enforce that the rows add up to the number.
- **Source influence**: which domains AI answers cite for this property's questions.
- **Top citation pages with "mentioned on page"**: the specific pages AI cites, and whether each page actually names the property. Beacon fetches the page and checks. Four honest states: mentioned, not mentioned, unchecked, unreachable. A page Beacon could not read is never reported as silent.
- **Rankings by topic**: for each monitored question, who AI names first among the property and its tracked competitors, with "needs work" flags.
- **Query fanouts**: the web searches the AI provider reported running to build its answer.
- **Accuracy**: claims AI makes about the property (pets, amenities, affordability and more), checked against recorded facts. Beacon only calls something a conflict when it holds a contradicting fact.
- **Content Analysis, Review Analysis, Competitor Analysis, AI Query Signals**: how well the site answers renter questions, what residents praise and complain about, and which landing pages receive AI-referred traffic.

### Stage 4. Act: "What do we do about it?"

- The **Opportunity Engine**: one ranked list of actions across every module, each with evidence, impact, effort and a Property Context gate (suppressed, requires confirmation, or actionable).
- **"This week"**: the top three actions on the AI Visibility overview.
- Three action types unique to AI visibility:
  - **Listing gaps**: "this directory page is cited in 22 answers and does not mention you." Fix: claim or update the listing.
  - **Fact conflicts**: AI says one thing, your recorded facts say another. Fix the page AI cited.
  - **Content gaps**: questions where competitors are named and you are absent, matched against what your site already says.

### Stage 5. Prove: "Did it work?"

- Eight reports: Executive, SEO Performance, GEO Visibility, AEO Readiness, Content Impact, Audience, AI Share of Voice, Semantic Intelligence.
- **Content Impact** compares before and after a logged content change, with explicit no-causation wording.
- **AI referral sessions** from GA4 shown beside AI visibility for the same period, described as association only.
- CSV export and print layouts.

### Stage 6. Brief: "What changed this month?"

- A **Monthly Strategic Briefing**: executive summary, wins, risks, trends, cross-system insights, strategic questions, and a grounded "if I were your strategist" section. Saved monthly, with a revocable share link for owners.
- **Alerts** when visibility moves beyond a threshold with enough sample, with automatic escalation to closer monitoring.
- **Nora**, the built-in analyst. She answers only from ingested data, cites her excerpts, and is code-gated from claiming causes she cannot support. She reads the AI visibility data and can say which question drove a change, or say plainly that there is not enough data to explain it.

### Platform and operations

- Durable job queue, monthly run budgets, cost recorded for every AI call including failed ones, an adaptive scheduler (built, currently switched off), and an admin operations panel.
- A **Sample Portfolio**: eight fictional communities in two fictional markets with scripted AI answers and first-party data, badged as sample on every screen, removable in one click. Built for demos.
- 840 automated tests. Deployed on Render.

## 6. What makes Beacon different

1. **Built for housing.** Market-level questions, property types and segments, neighborhoods, renter personas, housing authority prompt sets, and fair-housing-aware gating of recommendations. Horizontal tools such as Profound offer none of this. Two multifamily-specific products exist (see "The competitive field" below), so this point alone is not the differentiator; points 2 to 6 are.
2. **Honest by construction.** Every figure carries one of four labels: OBSERVED (the provider reported it), MEASURED (Beacon counted it), MODELED (a stated rule produced it), UNAVAILABLE (Beacon will not guess). Rates are withheld below a minimum sample. Beacon never reports AI search volume, because nobody can measure it.
3. **Evidence one click away.** Any number opens the answers behind it. This is what makes it usable in a client conversation.
4. **Portfolio economics.** One market answer scores every property in that market. Monitoring 50 communities in one city does not cost 50 times one community.
5. **From measurement to action.** Listing gaps, fact conflicts and content gaps are concrete tasks with a URL to fix, not a score to stare at.
6. **Never pretends to know competitors or facts.** Competitors, property type, regulatory status and policies are entered or confirmed by a person. Beacon never calls an AI claim false without a recorded fact that contradicts it.

## 6a. The competitive field

Be ready for this slide. Everything here is from the vendors' public pages; their statistics are their own research and disagree with each other, so do not quote them as fact.

| Product | What it is | Strength | Where Beacon differs |
|---|---|---|---|
| **Profound** and similar (Peec, Scrunch, AthenaHQ, Otterly) | Horizontal AI visibility platforms for brands | Many AI platforms, AI crawler analytics, content agents, enterprise features | Not built for housing; priced per brand or prompt, which does not work for a portfolio of communities; estimated "prompt volumes" Beacon will not publish |
| **LeasingAI** | Multifamily AI visibility from a leasing-AI vendor | A clear progression (indexed, cited, optimized, recommended) and a three-layer view of listings, property content and reputation | Beacon is independent of any leasing product; every number opens its evidence; no predicted-lift figures |
| **Peek Discover** | Multifamily AI visibility from a leasing-AI vendor | Simple workflow (score, strengths, concerns, sources, fixes), source importance against competitive gap, JavaScript readability research | Beacon keeps formulas, samples and labels instead of a single score; portfolio pattern detection; agency workflow rules |

**Positioning line:** Beacon is the independent, evidence-first measurement layer. It has nothing else to sell, it shows the rows behind every number, and it is built to find the handful of systemic problems behind most of a portfolio's AI visibility gaps.

What Beacon already matches from the field: a source influence matrix with actions, market rank plus confirmed comp-set rank, per-platform structure, topic-level rankings, listing gaps. What is planned next: topic "areas of concern" with the competitor explanation, a property truth layer with fact provenance, a raw-HTML AI readability check, an action lifecycle with automatic retest, portfolio pattern detection, and an evidence-grounded content fix workspace.

## 7. How it works (one slide)

1. Beacon builds a question library for the market and the property.
2. On a schedule, it asks AI platforms those questions with web search on and stores the full answer, citations and the searches the AI ran.
3. Each answer is scored for every relevant property: named, cited, recommended, position, sentiment, competitors present.
4. Daily rollups feed the metrics, trends, alerts and benchmarks.
5. Evidence, first-party data (GA4, Search Console, reviews, leads) and Property Context combine into ranked, gated actions and a monthly briefing.

## 8. Status and proof points

| Item | Status |
|---|---|
| Product | Working software, deployed, 840 automated tests passing |
| AI platforms | ChatGPT live with web search. Gemini, Claude and Perplexity connectors built and dormant until API keys are added. Microsoft Copilot has no API and is shown as unavailable |
| Live usage | One live housing authority client with Google data syncing and standing prompts **[you supply: how you want to describe it]** |
| Demo | Sample Portfolio, clearly badged as fictional |
| Example from the demo **[sample]** | A sample community reads 74 percent AI Visibility against a 42 percent average for the other seven sample communities; two heavily cited directory pages for its market do not mention it |

## 9. Planned (not built yet)

### Next
| Item | What it adds | Why it matters |
|---|---|---|
| More AI platforms switched on | Gemini and Perplexity as monthly validation runs; platform-by-platform breakdown | Renters use Google's AI answers heavily for local search; one platform is a sample, not the picture |
| Client access | Organization login with two roles (agency admin, client viewer) scoped to their own properties | Today the whole instance sits behind one shared access key; clients cannot be given their own view |
| Housing authority mode | Facts per development (program, income limits, waitlist status, voucher acceptance), a question set for how residents actually ask, and accuracy rules per development | A housing authority has many developments with different policies; a single policy field is wrong for them |

### Later
| Item | What it adds |
|---|---|
| Demo data for segments and neighborhoods | The Sample Portfolio scripted to show segment, neighborhood and persona panels filled in |
| Evidence-only outreach view | For each listing gap: the page, the evidence and the fix, ready to hand to whoever owns the listing. No AI-written outreach emails |
| Bing and Copilot | Import of Bing Webmaster AI performance data when Microsoft's export stabilizes |
| Scale foundation | Move from SQLite to Postgres and an external worker for large portfolios. The schema is already tenant-ready |
| White-label briefing | Agency-branded monthly briefing for owners |

### Deliberately not planned
- **Prompt or AI search volume estimates.** Nobody can measure them. Beacon shows a MODELED Opportunity Score built from stated inputs instead.
- **AI-written outreach or auto-publishing.** Beacon shows evidence and the fix; people act.

## 10. Packaging and pricing (to decide)

Beacon already records the inputs a pricing model needs: runs per property, cost per run, and the share of runs that are shared across a market. The scheduler has five built-in monitoring tiers that map naturally to plans:

| Tier in the product | Cadence | Natural use |
|---|---|---|
| Portfolio market | Shared market questions weekly | Base plan for every property |
| Standard property | Brand questions monthly | Included with base |
| Advanced property | Weekly, important questions repeated | Premium plan |
| Watchlist | Every three days for three weeks after an alert | Automatic, included in premium |
| Investigation | On demand, all platforms, repeated | Add-on or agency tool |

**[you supply: price points, target margin, and whether this is sold per property, per market, or bundled into an existing service]**

## 11. Suggested slide outline

1. **Title.** Beacon: are you in the answer?
2. **The shift.** A renter's question, an AI answer with three communities, yours missing. **[you supply: one real screenshot of an AI answer for a market you know]**
3. **Why nobody sees it.** What GA4, Search Console and ILS reports do not show.
4. **What Beacon is.** The one-liner and the six-question flow.
5. **Are we visible?** The four numbers, with labels. Screenshot of the Overview.
6. **Why?** Top citation pages with "mentioned on page," and rankings by topic. Screenshots.
7. **What do we do?** "This week" and a listing-gap action with its evidence.
8. **Did it work?** Content Impact and the Monthly Briefing.
9. **Built for housing.** Segments, neighborhoods, personas, Property Context, housing authorities.
9a. **The competitive field.** The table from section 6a and the positioning line.
10. **Honest by construction.** The four labels, the sample gate, no invented volume. This is the trust slide.
11. **Portfolio economics.** One market answer scores every property.
12. **Where it stands.** Live, tested, one platform on, three ready.
13. **Roadmap.** Next and later, from section 9.
14. **The ask.** **[you supply: what you want from this audience: a pilot, feedback, sponsorship, a client introduction]**

## 12. Demo script (10 minutes, Sample Portfolio)

1. **Setup.** Open a sample property's dashboard and show the setup line. "This is the only data entry a property ever does."
2. **Visible?** AI Visibility overview at 90 days: the four numbers. Click one to open the answers behind it.
3. **Compared with others.** The benchmark panel: you, others, gap in points.
4. **Why?** Sources tab: two directory pages cited dozens of times that do not mention the property. Competitors tab: rankings by topic. Switch to the sample senior community to show "needs work."
5. **Act.** "This week" and the Opportunities list. Say what Beacon will not do: write the email or invent volume.
6. **Prove.** Content Impact for a logged page rewrite; Executive report with AI referral sessions.
7. **Brief.** Monthly Briefing and a share link.
8. **Ask Nora** why AI visibility changed and show her citing the data or declining to guess.

## 13. Questions you will get, with honest answers

- **"How many people actually see these AI answers?"** Nobody can measure that, including the AI companies' customers. Beacon measures whether you are in the answer when the question is asked, and shows GA4 AI-referred visits beside it as a separate, observed number.
- **"AI answers change every time. Is this reliable?"** That is why Beacon repeats important questions, withholds rates below a minimum sample, and reports trends over windows rather than single answers.
- **"Is this the same as SEO?"** It overlaps. AI answers lean on the web, so content and listings matter. But the sources AI cites and the way it shortlists are different from a ranked results page, and Beacon measures that directly.
- **"Which AI platforms?"** ChatGPT today. Gemini, Claude and Perplexity are built and switch on with API keys. Copilot has no API.
- **"What does it cost to run?"** Every AI call is recorded with its cost. Shared market questions are paid for once per market, not once per property. **[you supply: observed cost per property per month once you have a few weeks of live runs]**
- **"Can clients log in?"** Not yet. That is the next platform item.
- **"Does it handle fair housing?"** Recommendations pass through Property Context. Themes that would be inappropriate for a property's type or regulatory status are suppressed or held for confirmation, and Beacon never infers regulatory status.

## 14. Vocabulary for the deck

| Term | Plain meaning |
|---|---|
| Monitored answer | One AI response Beacon requested and stored |
| AI Visibility | Share of monitored answers that name the property |
| Citation | A web source the AI linked in its answer |
| Citation Rate | Share of answers that cite the property's own site |
| Share of Voice | The property's mentions against tracked competitors |
| Listing gap | A cited third-party page that does not mention the property |
| Fact conflict | An AI claim that contradicts a recorded property fact |
| OBSERVED / MEASURED / MODELED / UNAVAILABLE | Reported by the provider / counted by Beacon / produced by a stated rule / not knowable, so not shown |

## 15. Things to avoid saying in the pitch

- Do not present Sample Portfolio numbers as client results.
- Do not say Beacon measures "AI search volume," "AI impressions" or "AI market share." It measures presence in monitored answers.
- Do not say a change in AI visibility caused a change in leads or leases. Beacon shows them side by side and says association.
- Do not quote LeasingAI's or Peek's published statistics as fact. They are vendor research and they disagree with each other. Say what Beacon measures for this client instead.
- Do not use product names that echo other vendors' naming. Modules are Content Analysis, Review Analysis and Competitor Analysis.
