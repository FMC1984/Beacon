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
    | "prompt_coverage",
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
