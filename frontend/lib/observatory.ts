/** AI Visibility Observatory (Phase 19) types and fetchers.
 *
 * Every number from the Observatory carries a data label:
 *   OBSERVED    exactly what a provider returned (citations, retrieval queries)
 *   MEASURED    counted by Beacon from observations (rates, shares)
 *   MODELED     a rule or weighted model (recommendation, sentiment, opportunity)
 *   UNAVAILABLE Beacon does not have it and shows no number
 * A null value is a named state, never a zero. */

import { API_BASE } from "@/lib/api";
import type { DataStateKey, PointComparison } from "@/lib/reports";

export type DataLabel = "OBSERVED" | "MEASURED" | "MODELED" | "UNAVAILABLE";

export type ObsMetric = {
  key: string;
  label: string;
  value: number | null;
  numerator: number;
  denominator: number;
  minimum_sample: number;
  sample_size?: number;
  state: DataStateKey;
  formula: string;
  data_label: DataLabel;
  note: string | null;
  comparison?: PointComparison;
  covered_cluster_ids?: number[];
  priority_cluster_ids?: number[];
};

export type MetricDefinition = {
  label: string;
  formula: string;
  data_label: DataLabel;
  note?: string;
};

export type ObservatoryMeta = {
  metrics: Record<string, MetricDefinition>;
  data_labels: DataLabel[];
  opportunity_score: { weights: Record<string, number>; note: string };
  limitations: string[];
};

export type SourceDomain = {
  domain: string;
  source_type: string | null;
  citations: number;
  responses: number;
  share: number | null;
};

export type SourceInfluence = {
  total_citations: number;
  domains: SourceDomain[];
  data_label: DataLabel;
  formula: string;
};

export type Overview = {
  property_id: number;
  property_name: string;
  market_id: number | null;
  window: { start: string; end: string; days: number };
  previous_window: { start: string; end: string };
  platform: string;
  metrics: Record<
    | "ai_visibility"
    | "citation_rate"
    | "citation_share"
    | "share_of_voice"
    | "recommendation_rate"
    | "competitor_win_rate"
    | "prompt_coverage"
    | "ai_sentiment",
    ObsMetric
  >;
  sentiment: { data_label: DataLabel; positive: number; neutral: number; negative: number };
  sample: { eligible_responses: number; observations: number };
  top_sources: SourceInfluence;
};

export type TrendPoint = {
  day: string;
  value: number | null;
  numerator: number;
  denominator: number;
  sufficient: boolean;
};

export type Trend = {
  metric: string;
  label: string;
  data_label: DataLabel;
  window: { start: string; end: string; days: number };
  previous_window: { start: string; end: string };
  current: ObsMetric;
  previous: ObsMetric;
  comparison: PointComparison;
  series: TrendPoint[];
  note: string;
};

export type CitationRow = {
  citation_id: number;
  response_id: number;
  run_id: number | null;
  url: string;
  domain: string;
  title: string | null;
  order: number;
  source_type: string | null;
  capture_method: string;
  owned: boolean;
  platform: string;
  observed_at: string;
  prompt_id: number | null;
  cluster_id: number | null;
};

export type Page<T> = { total: number; limit: number; offset: number; items: T[] };

export type ObsPrompt = {
  id: number;
  prompt_text: string;
  scope: "market" | "feature" | "brand" | "sentinel";
  platform: string;
  property_id: number | null;
  market_id: number | null;
  cluster_id: number | null;
  topic_key: string | null;
  intent: string | null;
  importance: number;
  funnel_stage: string | null;
  active: boolean;
  approved: boolean;
  is_representative: boolean;
  variant_group: string | null;
  repeat_count: number | null;
  cadence: string | null;
  generation_method: string | null;
  generated_from: Record<string, unknown> | null;
  last_run_at: string | null;
  created_at: string | null;
};

export type ObsCluster = {
  id: number;
  scope: string;
  label: string;
  topic_key: string | null;
  intent: string | null;
  funnel_stage: string | null;
  importance: number;
  market_id: number | null;
  property_id: number | null;
  representative_prompt_id: number | null;
  variant_count: number;
  embedding_model: string | null;
  assigned?: boolean;
};

export type OpportunityContributor = { value: number | null; available: boolean; detail: string };

export type Opportunity = {
  cluster_id: number;
  property_id: number;
  score: number | null;
  data_label: DataLabel;
  window: { start: string; end: string; days: number };
  weights: Record<string, number>;
  effective_weights: Record<string, number>;
  contributors: Record<string, OpportunityContributor>;
  explanation: string;
};

export type MarketRow = {
  id: number;
  slug: string;
  name: string;
  city: string;
  state: string;
  organization_id: number | null;
  is_active: boolean;
  property_count: number;
};

export type MarketSummary = {
  market: { id: number; slug: string; name: string };
  window: { start: string; end: string; days: number };
  runs: number;
  responses: number;
  properties_scored: number;
  citations: number;
  data_label: DataLabel;
  note: string;
  leaderboard: {
    property_id: number;
    name: string;
    ai_visibility: number | null;
    citation_rate: number | null;
    share_of_voice: number | null;
    eligible_responses: number;
  }[];
};

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(await errorText(res));
  return res.json();
}

async function postJSON<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await errorText(res));
  return res.json();
}

async function errorText(res: Response): Promise<string> {
  try {
    const body = await res.json();
    return typeof body.detail === "string" ? body.detail : `Request failed (${res.status}).`;
  } catch {
    return `Request failed (${res.status}).`;
  }
}

const qs = (params: Record<string, string | number | null | undefined>) => {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== null && v !== undefined && v !== "") p.set(k, String(v));
  return p.toString();
};

const BASE = "/ai-observatory";

export const fetchObservatoryMeta = () => getJSON<ObservatoryMeta>(`${BASE}/meta`);

export const fetchOverview = (propertyId: number, days: number) =>
  getJSON<Overview>(`${BASE}/overview?${qs({ property_id: propertyId, days })}`);

export const fetchTrend = (propertyId: number, metric: string, days: number) =>
  getJSON<Trend>(`${BASE}/trends?${qs({ property_id: propertyId, metric, days })}`);

export const fetchSources = (propertyId: number, days: number, limit = 50) =>
  getJSON<SourceInfluence>(`${BASE}/sources?${qs({ property_id: propertyId, days, limit })}`);

export const fetchCitations = (
  propertyId: number,
  days: number,
  opts: { domain?: string; sourceType?: string; limit?: number; offset?: number } = {}
) =>
  getJSON<Page<CitationRow> & { data_label: DataLabel }>(
    `${BASE}/citations?${qs({
      property_id: propertyId,
      days,
      domain: opts.domain,
      source_type: opts.sourceType,
      limit: opts.limit ?? 50,
      offset: opts.offset ?? 0,
    })}`
  );

export const fetchPrompts = (propertyId: number) =>
  getJSON<{ prompts: ObsPrompt[]; total: number }>(`${BASE}/prompts?${qs({ property_id: propertyId })}`);

export const fetchClusters = (propertyId: number) =>
  getJSON<{ clusters: ObsCluster[]; total: number }>(`${BASE}/clusters?${qs({ property_id: propertyId })}`);

export const fetchOpportunity = (clusterId: number, propertyId: number, days: number) =>
  getJSON<Opportunity>(`${BASE}/clusters/${clusterId}/opportunity?${qs({ property_id: propertyId, days })}`);

export type GenerateResult = {
  property_id: number;
  market_id: number | null;
  brand_prompts: { total: number; created: number };
  market_prompts: { total: number; created: number };
  clusters: { brand: number; market: number; embedding_model: string | null };
};

export const generatePrompts = (propertyId: number) =>
  postJSON<GenerateResult>(`${BASE}/prompts/generate?${qs({ property_id: propertyId })}`);

export const runMarketPrompt = (promptId: number) =>
  postJSON<{ job_id: number; status: string; created: boolean }>(`${BASE}/prompts/${promptId}/run`);

export const fetchMarkets = () => getJSON<{ markets: MarketRow[] }>(`${BASE}/markets`);

export const fetchMarketSummary = (marketId: number, days: number) =>
  getJSON<MarketSummary>(`${BASE}/markets/${marketId}/summary?${qs({ days })}`);

/** Backend timestamps without an offset are naive UTC (SQLite convention). */
export const asUtc = (iso: string) => (/(?:[zZ]|[+-]\d\d:?\d\d)$/.test(iso) ? iso : `${iso}Z`);

export const fmtRate = (v: number | null | undefined) =>
  v === null || v === undefined ? "n/a" : `${Math.round(v * 100)}%`;

// --- Slice 5: discovery, claims, alerts, costs, schedule ---------------------

export type Candidate = {
  id: number;
  name: string;
  responses: number;
  first_seen: string | null;
  last_seen: string | null;
  evidence_response_ids: number[];
  sample_context: string | null;
  confidence: number;
  confidence_label: DataLabel;
  decision: "confirmed" | "ignored" | null;
  competitor_id: number | null;
};

export type ClaimStatus = "confirmed" | "likely_accurate" | "conflict_detected" | "unable_to_verify";

export type Claim = {
  id: number;
  property_id: number;
  claim_type: string;
  claim_topic: string | null;
  claim_value: string;
  claim_text: string;
  verification_status: ClaimStatus;
  verification_method: string;
  evidence: string;
  known_value: string | null;
  severity: "low" | "medium" | "high";
  occurrence_count: number;
  response_ids: number[];
  platforms: string[];
  status: string;
  first_seen: string | null;
  last_seen: string | null;
  data_label: DataLabel;
};

export type Alert = {
  id: number;
  property_id: number | null;
  market_id: number | null;
  alert_type: string;
  severity: "low" | "medium" | "high";
  title: string;
  detail: string;
  evidence: Record<string, unknown> | null;
  metric_before: number | null;
  metric_after: number | null;
  data_label: DataLabel;
  status: "open" | "acknowledged" | "resolved";
  escalated: boolean;
  created_at: string | null;
};

export type CostBlock = {
  estimated_usd: number | null;
  label: DataLabel;
  coverage: "no_runs" | "none" | "partial" | "full";
  priced_runs: number;
  runs: number;
  note?: string | null;
};

export type UsageSummary = {
  runs: number;
  by_status: Record<string, number>;
  tokens: { label: DataLabel; input: number; output: number; reasoning: number; cached: number };
  search_operations: number;
  cost: CostBlock;
};

export type CostReport = {
  window: { start: string; end: string; days: number };
  total: UsageSummary;
  by_provider_model: Record<string, UsageSummary>;
  by_scope: Record<string, UsageSummary>;
  observations_produced: number;
  cost_per_observation: { estimated_usd: number; label: DataLabel; note: string } | null;
  budget: { period: string; allowance_runs: number; spent_runs: number; remaining_runs: number; exhausted: boolean };
  note: string;
};

export type PlanDecision = {
  schedule_id: number;
  prompt_id: number;
  platform: string;
  tier: string;
  decision: string;
  reason: string;
  priority_score: number;
  components: Record<string, number>;
};

export type Plan = {
  plan_key: string;
  dry_run: boolean;
  due: number;
  selected: number;
  skipped_budget: number;
  pending_runs_reserved: number;
  budget_remaining_after: number;
  decisions: PlanDecision[];
};

export const fetchCandidates = (propertyId: number) =>
  getJSON<{ candidates: Candidate[]; minimum_responses: number; note: string }>(
    `${BASE}/competitors/discovered?${qs({ property_id: propertyId })}`
  );

export const decideCandidate = (entityId: number, propertyId: number, decision: "confirmed" | "ignored", domain?: string) =>
  postJSON<{ decision: string; competitor_id: number | null }>(`${BASE}/competitors/discovered/${entityId}/decision`, {
    property_id: propertyId,
    decision,
    domain: domain || null,
  });

export const fetchClaims = (propertyId: number) =>
  getJSON<{ counts: Record<ClaimStatus, number>; claims: Claim[] }>(`${BASE}/claims?${qs({ property_id: propertyId })}`);

export const dismissClaim = (claimId: number) => postJSON<Claim>(`${BASE}/claims/${claimId}/dismiss`);

export const fetchAlerts = (propertyId: number) =>
  getJSON<{ alerts: Alert[] }>(`${BASE}/alerts?${qs({ property_id: propertyId })}`);

export const setAlertStatus = (alertId: number, status: Alert["status"]) =>
  postJSON<Alert>(`${BASE}/alerts/${alertId}/status`, { status });

export const fetchCosts = (days: number, propertyId: number | null = null) =>
  getJSON<CostReport>(`${BASE}/costs?${qs({ days, property_id: propertyId })}`);

export const previewPlan = () => postJSON<Plan>(`${BASE}/schedule/plan?dry_run=true`);

// --- Slice 6: content gaps, impact, portfolio --------------------------------

export type ContentGap = {
  id: number;
  property_id: number;
  cluster_id: number;
  topic_key: string | null;
  question: string;
  target_page: string | null;
  page_exists: boolean;
  missing_terms: string[];
  covered_terms: string[];
  evidence: {
    absent_response_ids?: number[];
    absent_responses?: number;
    cited_domains?: { domain: string; source_type: string | null; citations: number }[];
    competitors_named?: { competitor_id: number; name: string; answers: number }[];
  };
  visibility: number | null;
  competitor_presence: number | null;
  title: string;
  recommendation: string;
  state: string;
  gate_reason: string | null;
  impact: string;
  effort: string;
  status: string;
  data_label: DataLabel;
  first_detected: string | null;
  last_evaluated: string | null;
};

export type ImpactStep = {
  step: string;
  label: DataLabel;
  current: number | null;
  previous: number | null;
  source: string;
  note?: string | null;
};

export type Impact = {
  property_id: number;
  mode: "ai_only" | "ai_plus_search";
  window: { start: string; end: string; days: number };
  previous_window: { start: string; end: string };
  chain: ImpactStep[];
  search_console: {
    label: DataLabel;
    current: { clicks: number; impressions: number } | null;
    previous: { clicks: number; impressions: number } | null;
    note: string;
  };
  ai_platform_mix: Record<string, number>;
  alignment: "same_direction" | "opposite_directions" | "not_comparable";
  alignment_text: string;
  note: string;
};

export type PortfolioAverage = { value: number | null; properties: number; label: DataLabel; note?: string };

export type Portfolio = {
  scope: { company_id: number | null; unassigned: boolean; properties: number };
  window: { start: string; end: string; days: number };
  averages: Record<"ai_visibility" | "citation_rate" | "share_of_voice" | "recommendation_rate", PortfolioAverage>;
  properties: {
    property_id: number;
    name: string;
    market_id: number | null;
    eligible_responses: number;
    ai_visibility: number | null;
    citation_rate: number | null;
    share_of_voice: number | null;
    recommendation_rate: number | null;
  }[];
  shared_gaps: { topic_key: string; properties: number; gaps: number; text: string }[];
  top_sources: { domain: string; citations: number; properties: number }[];
  note: string;
};

export const fetchGaps = (propertyId: number) =>
  getJSON<{ gaps: ContentGap[]; note: string }>(`${BASE}/recommendations?${qs({ property_id: propertyId })}`);

export const evaluateGaps = (propertyId: number, days: number) =>
  postJSON<{ gaps_open: number; auto_resolved: number }>(
    `${BASE}/recommendations/evaluate?${qs({ property_id: propertyId, days: Math.max(days, 7) })}`
  );

export const setGapStatus = (gapId: number, status: "open" | "dismissed" | "resolved") =>
  postJSON<ContentGap>(`${BASE}/recommendations/${gapId}/status`, { status });

export const fetchImpact = (propertyId: number, days: number) =>
  getJSON<Impact>(`${BASE}/impact?${qs({ property_id: propertyId, days: Math.max(days, 7) })}`);

export const fetchPortfolio = (scope: { companyId: number | null; unassigned: boolean }, days: number) =>
  getJSON<Portfolio>(
    `${BASE}/portfolio?${qs({ company_id: scope.companyId, unassigned: scope.unassigned ? "true" : null, days })}`
  );

// --- Drilldown: fanouts, position, sentiment reasons, evidence ---------------

export type FanoutVariation = { query: string; count: number; share: number | null };
export type FanoutPrompt = {
  cluster_id: number | null;
  prompt: string;
  executions: number;
  executions_with_queries: number;
  query_count: number;
  distinct_queries: number;
  avg_queries_per_execution: number | null;
  variations: FanoutVariation[];
};
export type Fanouts = {
  data_label: DataLabel;
  note: string;
  window_days: number;
  responses: number;
  responses_with_queries: number;
  coverage: number | null;
  prompts: FanoutPrompt[];
  state: DataStateKey;
};

export type PositionStats = {
  eligible: number;
  mentioned: number;
  ranked: number;
  average_position: number | null;
  first_named: number;
  first_named_rate: number | null;
  distribution: Record<string, number>;
};
export type Position = {
  data_label: DataLabel;
  note: string;
  window: { start: string; end: string; days: number };
  current: PositionStats;
  previous: PositionStats;
  change: number | null;
  lower_is_better: true;
  state: DataStateKey;
  minimum_sample: number;
  first_named_comparison: PointComparison;
  by_prompt: (PositionStats & { cluster_id: number | null; prompt: string; state: DataStateKey })[];
};

export type SentimentReason = { topic: string; label: string; answers: number; quotes: string[] };
export type SentimentReasons = {
  data_label: DataLabel;
  note: string;
  window_days: number;
  mentions: number;
  counts: { positive: number; neutral: number; negative: number };
  positive_share: number | null;
  neutral_share: number | null;
  positive_reasons: SentimentReason[];
  negative_reasons: SentimentReason[];
  state: DataStateKey;
  minimum_sample: number;
};

export type EvidenceItem = {
  observation_id: number;
  response_id: number;
  counts: boolean;
  observed_at: string;
  platform: string;
  prompt: string;
  cluster: string | null;
  mentioned: boolean;
  mention_rank: number | null;
  cited: boolean;
  recommended: boolean | null;
  sentiment: string | null;
  competitors_named: number;
  excerpt: string | null;
  answer: string;
  citations: { url: string; domain: string; source_type: string | null }[];
};
export type Evidence = {
  metric: string;
  description: string;
  window_days: number;
  numerator: number;
  denominator: number;
  showing: "counting" | "all";
  total: number;
  limit: number;
  offset: number;
  items: EvidenceItem[];
};

export const fetchFanouts = (propertyId: number, days: number) =>
  getJSON<Fanouts>(`${BASE}/fanouts?${qs({ property_id: propertyId, days })}`);
export const fetchPosition = (propertyId: number, days: number) =>
  getJSON<Position>(`${BASE}/position?${qs({ property_id: propertyId, days })}`);
export const fetchSentimentReasons = (propertyId: number, days: number) =>
  getJSON<SentimentReasons>(`${BASE}/sentiment?${qs({ property_id: propertyId, days })}`);
export const fetchEvidence = (
  propertyId: number,
  metric: string,
  days: number,
  opts: { clusterId?: number | null; onlyCounting?: boolean; limit?: number; offset?: number } = {}
) =>
  getJSON<Evidence>(
    `${BASE}/evidence?${qs({
      property_id: propertyId,
      metric,
      days,
      cluster_id: opts.clusterId ?? null,
      only_counting: opts.onlyCounting === false ? "false" : null,
      limit: opts.limit ?? 50,
      offset: opts.offset ?? 0,
    })}`
  );

// --- Top citation pages + topic rankings -----------------------------------

export type MentionOnPage = "mentioned" | "not_mentioned" | "unchecked" | "unreachable";

export type CitationPage = {
  url: string;
  normalized_url: string;
  domain: string;
  title: string | null;
  source_type: string | null;
  citations: number;
  responses: number;
  share: number | null;
  mentioned_on_page: MentionOnPage;
  mention_detail: string | null;
  checked_at: string | null;
};

export type CitationPages = {
  property_id: number;
  data_label: DataLabel;
  mention_check_label?: DataLabel;
  window_days?: number;
  total_citations: number;
  distinct_pages?: number;
  pages: CitationPage[];
  check: Record<MentionOnPage, number>;
  note?: string;
};

export type RankedEntity = {
  entity_id: number;
  name: string;
  is_property: boolean;
  mentions: number;
  share: number | null;
  rank: number;
};

export type TopicRanking = {
  cluster_id: number;
  prompt: string;
  topic_key: string | null;
  importance: number;
  answers: number;
  sufficient: boolean;
  state: DataStateKey;
  property_rank: number | null;
  property_mentions: number;
  needs_work: boolean;
  leader: string | null;
  ranked: RankedEntity[];
};

export type TopicRankings = {
  property_id: number;
  data_label: DataLabel;
  window: { start: string; end: string; days: number };
  minimum_sample: number;
  tracked_competitors: number;
  topics: TopicRanking[];
  summary: { topics: number; leading: number; needs_work: number };
  note: string;
};

export const fetchCitationPages = (propertyId: number, days: number, limit = 50) =>
  getJSON<CitationPages>(`${BASE}/citations/pages?${qs({ property_id: propertyId, days, limit })}`);

export const requestCitationPageCheck = (propertyId: number, days: number) =>
  postJSON<{ job_id: number; status: string; created: boolean }>(
    `${BASE}/citations/pages/check?${qs({ property_id: propertyId, days })}`
  );

export const fetchTopicRankings = (propertyId: number, days: number) =>
  getJSON<TopicRankings>(`${BASE}/rankings?${qs({ property_id: propertyId, days })}`);

// --- Opportunity Engine actions (the "This week" strip) ---------------------

export type ActionItem = {
  source: string;
  source_label: string;
  title: string;
  reason: string;
  state: string;
  impact: string | null;
  effort: string | null;
  evidence_level?: string | null;
  citations?: { page?: string | null; source_ref: string; evidence?: string[] }[];
  gate_reason?: string | null;
  corroborating_sources?: string[];
  priority?: number;
  priority_score?: number;
  action?: ActionRef;
};

export type ActionList = {
  property_id: number;
  property_name: string;
  generated_on: string;
  total: number;
  by_source: Record<string, number>;
  opportunities: ActionItem[];
  summary: string;
};

export const fetchActions = (propertyId: number) => getJSON<ActionList>(`/opportunities/${propertyId}`);

// --- Visibility by area and audience -------------------------------------

export type DimensionRow = {
  key: string;
  label: string;
  clusters: number;
  answers: number;
  ai_visibility: { value: number | null; numerator: number; denominator: number; minimum_sample: number; state: DataStateKey };
};

export type Dimensions = {
  property_id: number;
  data_label: DataLabel;
  window: { start: string; end: string; days: number };
  property_geography: string | null;
  property_personas: string[];
  regions: DimensionRow[];
  personas: DimensionRow[];
  note: string;
};

export const fetchDimensions = (propertyId: number, days: number) =>
  getJSON<Dimensions>(`${BASE}/dimensions?${qs({ property_id: propertyId, days })}`);

// --- Cross-property benchmarks -------------------------------------------

export type BenchmarkRow = {
  property_value: number | null;
  benchmark_value: number | null;
  properties: number;
  data_label: DataLabel;
  note: string | null;
  point_change: number | null;
};

export type BenchmarkPool = {
  pool: { properties: number; organizations: number };
  metrics: Record<"ai_visibility" | "citation_rate" | "share_of_voice" | "recommendation_rate", BenchmarkRow>;
};

export type Benchmark = {
  property_id: number;
  window: { start: string; end: string; days: number };
  is_sample: boolean;
  segment: string | null;
  minimum_pool: number;
  all: BenchmarkPool;
  segment_pool: BenchmarkPool;
  note: string;
};

export const fetchBenchmark = (propertyId: number, days: number) =>
  getJSON<Benchmark>(`${BASE}/benchmark?${qs({ property_id: propertyId, days })}`);

// --- Platform breakdown, Source Influence Matrix, standing -------------------

export type PlatformAvailability = { state: "live" | "needs_key" | "planned" | "no_api"; detail: string; env_var?: string };

export type PlatformRow = {
  platform: string;
  label: string;
  availability: PlatformAvailability;
  answers: number;
  ai_visibility: ObsMetric;
  citation_rate: ObsMetric;
  share_of_voice: ObsMetric;
  recommendation_rate: ObsMetric;
  top_sources: { domain: string; citations: number; share: number }[];
  total_citations: number;
};

export type PlatformBreakdown = { property_id: number; data_label: DataLabel; platforms: PlatformRow[]; live: number; note: string };

export type SourceAction = "expand" | "strengthen" | "study" | "fix" | "opportunity" | "maintain" | "monitor" | "check" | "verify";

export type SourceMatrixRow = {
  domain: string;
  source_type: string | null;
  citations: number;
  share: number;
  influence: "high" | "medium" | "low";
  presence: "owned" | "present" | "absent" | "unknown";
  pages: { cited: number; read: number; unreachable: number };
  competitors_named: string[];
  competitor_advantage: "high" | "shared" | "none" | "unknown";
  accuracy: null;
  by_platform: Record<string, number>;
  action: SourceAction;
  action_text: string;
};

export type SourceMatrix = {
  property_id: number;
  data_label: DataLabel;
  total_citations: number;
  distinct_sources?: number;
  sources: SourceMatrixRow[];
  platforms: string[];
  accuracy_note?: string;
  note?: string;
};

export type Standing = {
  property_id: number;
  data_label: DataLabel;
  market:
    | { available: false; reason: string; monitored?: number; also_named?: number }
    | { available: true; rank: number; size: number; monitored: number; tied: boolean; ai_visibility: number; also_named: number; only_one: boolean };
  comp_set:
    | { available: false; reason: string; answers?: number }
    | {
        available: true;
        answers: number;
        size: number;
        rank: number | null;
        tied: boolean;
        ranked: { name: string; is_property: boolean; mentions: number; rank: number }[];
        unranked: string[];
        beating: number;
        competitors: number;
        ahead_of_you: { name: string; winning_on: string[] }[];
      };
  note: string;
};

export const fetchPlatformBreakdown = (propertyId: number, days: number) =>
  getJSON<PlatformBreakdown>(`${BASE}/platforms?${qs({ property_id: propertyId, days })}`);

export const fetchSourceMatrix = (propertyId: number, days: number) =>
  getJSON<SourceMatrix>(`${BASE}/sources/matrix?${qs({ property_id: propertyId, days })}`);

export const fetchStanding = (propertyId: number, days: number) =>
  getJSON<Standing>(`${BASE}/standing?${qs({ property_id: propertyId, days })}`);

// --- Areas of concern -------------------------------------------------------------

export type ConcernLevel = "high" | "medium" | "monitor" | "maintain" | "insufficient";

export type ConcernTopic = {
  topic_key: string;
  label: string;
  answers: number;
  visibility: { value: number | null; numerator: number; denominator: number; minimum_sample: number };
  best_competitor: { name: string; rate: { value: number | null; numerator: number; denominator: number } } | null;
  gap_points: number | null;
  evidence: "strong" | "medium" | "weak";
  concern: ConcernLevel;
  absent: number;
};

export type Concerns = {
  property_id: number;
  data_label: DataLabel;
  tracked_competitors: number;
  topics: ConcernTopic[];
  summary: Record<ConcernLevel, number>;
  note: string;
};

export type ConcernDetail = {
  topic_key: string;
  label: string;
  answers: number;
  absent: number;
  questions: string[];
  competitors_winning: { name: string; answers: number }[];
  cited_sources: { domain: string; citations: number; source_type: string | null }[];
  cited_pages: { url: string; citations: number; read: boolean; names_you: boolean | null; names_competitors: string[] }[];
  own_content: { pages: number; target_page: string; target_exists: boolean; covered_terms: string[]; missing_terms: string[] };
  explanation: string[];
  recommended_action: { text: string; state: string; gate_reason: string | null; from_content_gap: boolean };
  note: string;
};

export const fetchConcerns = (propertyId: number, days: number) =>
  getJSON<Concerns>(`${BASE}/concerns?${qs({ property_id: propertyId, days })}`);

export const fetchConcernDetail = (propertyId: number, topicKey: string, days: number) =>
  getJSON<ConcernDetail>(`${BASE}/concerns/${encodeURIComponent(topicKey)}?${qs({ property_id: propertyId, days })}`);

// --- Truth layer ------------------------------------------------------------------

export type TruthCell = {
  state: "agrees" | "conflicts" | "mentions" | "not_stated" | "unread" | "unreachable" | "not_listed" | "volatile";
  values?: string[];
  evidence?: string;
  agree?: number;
  conflict?: number;
};

export type TruthFact = {
  fact_key: string;
  label: string;
  recorded_value: string;
  provenance: {
    source_of_truth: string | null;
    verified_at: string | null;
    verified_by: string | null;
    effective_date: string | null;
    freshness: "stable" | "seasonal" | "volatile";
    status: "verified" | "stale" | "unverified";
    stale_after_days: number;
    notes: string | null;
  };
  cells: Record<string, TruthCell>;
  conflicts: number;
  cited_sources_with_same_value: { domain: string; url: string; value: string; evidence: string }[];
};

export type TruthGrid = {
  property_id: number;
  data_label: DataLabel;
  columns: { key: string; label: string; kind: "owned" | "listing" | "ai"; citations?: number }[];
  facts: TruthFact[];
  summary: { facts: number; with_conflicts: number; unverified: number; stale: number };
  notes: string[];
  note: string;
};

export const fetchTruth = (propertyId: number, days: number) =>
  getJSON<TruthGrid>(`${BASE}/truth?${qs({ property_id: propertyId, days })}`);

// --- AI readability ----------------------------------------------------------------

type ReadabilityBase = {
  property_id: number;
  data_label: DataLabel;
  site_url: string | null;
  categories_spec: Record<string, { label: string; severity: "critical" | "high" | "medium" }>;
  agents: string[];
  note: string;
};

export type ReadabilityReport =
  | (ReadabilityBase & { checked: false; reason: string })
  | (ReadabilityBase & {
      checked: true;
      checked_at: string;
      status: "ok" | "error";
      error: string | null;
      is_sample: boolean;
      pages: { url: string; http_status: number | null; chars: number | null; scripts: number; found: Record<string, string>; error?: string }[];
      categories: Record<string, { present: boolean; page: string | null; evidence: string | null }>;
      robots: { reachable?: boolean; url?: string; present?: boolean; agents?: Record<string, "allowed" | "disallowed" | "unknown"> };
      structured_data: string[];
      findings: { severity: "critical" | "high" | "medium"; category: string; text: string }[];
      summary: { critical: number; high: number; medium: number; present: number; total: number };
    });

export const fetchReadability = (propertyId: number) =>
  getJSON<ReadabilityReport>(`${BASE}/readability?${qs({ property_id: propertyId })}`);

export const requestReadabilityCheck = (propertyId: number) =>
  postJSON<{ job_id: number; status: string; created: boolean }>(`${BASE}/readability/check?${qs({ property_id: propertyId })}`);

export async function saveFactProvenance(
  propertyId: number,
  factKey: string,
  body: { verified?: boolean; source_of_truth?: string; verified_by?: string; freshness?: string; notes?: string }
): Promise<TruthFact["provenance"]> {
  const res = await fetch(`${API_BASE}${BASE}/truth/facts/${encodeURIComponent(factKey)}?${qs({ property_id: propertyId })}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await errorText(res));
  return res.json();
}

// --- Tracked actions (lifecycle with retest) ----------------------------------------

export type ActionStatus = "open" | "in_progress" | "implemented" | "retested" | "done" | "dismissed";
export type ActionOutcome = "resolved" | "persists" | "improved" | "no_change" | "declined" | "inconclusive";
export type ActionRef = { id: number; status: ActionStatus; outcome: ActionOutcome | null } | null;

export type TrackedAction = {
  id: number;
  property_id: number;
  kind: "listing_gap" | "content_gap" | "topic" | "fact" | "general";
  target: Record<string, unknown>;
  source: string | null;
  source_label: string | null;
  title: string;
  reason: string | null;
  evidence: { page?: string | null; source_ref?: string; evidence?: string[] }[];
  status: ActionStatus;
  owner: string | null;
  notes: string | null;
  started_at: string | null;
  implemented_on: string | null;
  retest_after: string | null;
  retest_count: number;
  retested_at: string | null;
  baseline: Record<string, unknown> | null;
  result: ({ sentence?: string } & Record<string, unknown>) | null;
  outcome: ActionOutcome | null;
  content_change_id: number | null;
  automatic_retest: boolean;
  retest_rule: string;
  created?: boolean;
};

export type TrackedActions = {
  property_id: number;
  actions: TrackedAction[];
  by_status: Partial<Record<ActionStatus, number>>;
  by_outcome: Partial<Record<ActionOutcome, number>>;
  note: string;
};

export type TrackPayload = {
  property_id: number;
  title: string;
  source?: string | null;
  source_label?: string | null;
  reason?: string | null;
  citations?: unknown[] | null;
  kind?: TrackedAction["kind"];
  target?: Record<string, unknown>;
};

export const fetchTrackedActions = (propertyId: number) =>
  getJSON<TrackedActions>(`${BASE}/actions?${qs({ property_id: propertyId })}`);

export const trackAction = (payload: TrackPayload) => postJSON<TrackedAction>(`${BASE}/actions`, payload);

export async function updateTrackedAction(
  actionId: number,
  body: { status?: ActionStatus; owner?: string; notes?: string; implemented_on?: string; page_url?: string; change_type?: string }
): Promise<TrackedAction> {
  const res = await fetch(`${API_BASE}${BASE}/actions/${actionId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await errorText(res));
  return res.json();
}

export const retestTrackedAction = (actionId: number) => postJSON<TrackedAction>(`${BASE}/actions/${actionId}/retest`);
