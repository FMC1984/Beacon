import { API_BASE } from "@/lib/api";

// Data states a report surface can be in. Mirrors DataState in
// backend/app/services/reporting.py; missing data is a named state here,
// never a numeric zero.
export type DataStateKey =
  | "complete"
  | "partial_period"
  | "awaiting_data"
  | "source_delayed"
  | "not_configured"
  | "insufficient_sample"
  | "failed_source"
  | "empty";

export type ReportTab = {
  key: string;
  label: string;
  status: "available" | "planned";
  planned_phase: string;
  summary: string;
};

export type SourceStatus = {
  key: string;
  label: string;
  state: DataStateKey;
  detail: string;
  first_data_date: string | null;
  last_data_date: string | null;
  connected: boolean;
};

export type ReportStatus = {
  checked_date: string;
  sources: SourceStatus[];
  worst_state: DataStateKey;
};

// Comparison envelope for a metric across two periods (see reporting.compare
// on the backend): null means "not comparable", never zero.
export type Comparison = {
  current: number | null;
  previous: number | null;
  change: number | null;
  pct_change: number | null;
  direction: "up" | "down" | "flat" | null;
};

export type ReportScope = {
  propertyId: number | null;
  companyId: number | null;
  unassigned: boolean;
};

function scopeParams(scope: ReportScope): URLSearchParams {
  const params = new URLSearchParams();
  if (scope.propertyId !== null) params.set("property_id", String(scope.propertyId));
  else if (scope.unassigned) params.set("unassigned", "true");
  else if (scope.companyId !== null) params.set("company_id", String(scope.companyId));
  return params;
}

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

export const fetchReportMeta = () =>
  getJSON<{ tabs: ReportTab[] }>("/reports/meta");

export const fetchReportStatus = (scope: ReportScope) =>
  getJSON<ReportStatus>(`/reports/status?${scopeParams(scope)}`);

// --- SEO Performance report (Phase 16B) ---

export type SeoCard = {
  key: string;
  label: string;
  source: string;
  state: DataStateKey;
  value: number | null;
  unit: "pct" | null;
  higher_is_better: boolean;
  comparison: Comparison | null;
  comparison_warning: string | null;
  last_data_date: string | null;
  sample: {
    value: number | null;
    numerator: number;
    denominator: number;
    state: DataStateKey;
  } | null;
};

export type SeoTrendPoint = {
  date: string;
  clicks: number;
  impressions: number;
  ctr: number | null;
  position: number | null;
};

export type SeoQuadrantPoint = {
  query: string;
  clicks: number;
  impressions: number;
  ctr: number | null;
  position: number | null;
  pages: string[];
  branded: boolean;
  topics: string[];
  flags: Record<string, boolean>;
};

export type SeoMover = {
  query: string;
  current_clicks: number | null;
  previous_clicks: number | null;
  click_change: number;
  current_impressions: number | null;
  previous_impressions: number | null;
  impression_change: number;
  current_position: number | null;
  previous_position: number | null;
  position_change: number | null;
};

export type SeoLandingRow = {
  page: string;
  canonical_page: string | null;
  matched: boolean;
  sessions: number | null;
  engaged_sessions: number | null;
  key_events: number | null;
  conversion_rate: number | null;
  clicks: number | null;
  impressions: number | null;
};

export type SeoReport = {
  window: { days: number; start: string; end: string; anchored_to_latest_data: boolean };
  previous_window: { start: string; end: string };
  compare_requested: boolean;
  summary: { cards: SeoCard[] };
  trends: { state: DataStateKey; series: SeoTrendPoint[] };
  ranking_distribution: {
    state: DataStateKey;
    detail?: string;
    buckets: { bucket: string; current: number; previous: number | null; change: number | null }[];
    total_queries?: { current: number; previous: number | null };
    note: string;
  };
  quadrant: {
    state: DataStateKey;
    detail?: string;
    points: SeoQuadrantPoint[];
    highlights?: Record<string, number>;
    dropped?: number;
    note: string;
    rules?: Record<string, string>;
  };
  movers: {
    state: DataStateKey;
    detail?: string;
    gains: SeoMover[];
    losses: SeoMover[];
    thresholds?: { min_impressions: number; min_click_change: number; min_position_change: number };
  };
  landing_pages: {
    state: DataStateKey;
    detail?: string;
    rows: SeoLandingRow[];
    dropped?: number;
    match_counts: { matched: number; ga4_only: number; gsc_only: number } | null;
    normalization: string;
  };
};

export const fetchSeoReport = (scope: ReportScope, days: number, compare: boolean) => {
  const params = scopeParams(scope);
  params.set("days", String(days));
  params.set("compare", String(compare));
  return getJSON<SeoReport>(`/reports/seo?${params}`);
};
