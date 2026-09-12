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

export const fmtRate = (v: number | null | undefined) =>
  v === null || v === undefined ? "n/a" : `${Math.round(v * 100)}%`;
