import { API_BASE, type EventsSection } from "@/lib/api";

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
  summary: { cards: SeoCard[]; gsc_note?: string };
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
  events: EventsSection | null;
};

export const fetchSeoReport = (scope: ReportScope, days: number, compare: boolean) => {
  const params = scopeParams(scope);
  params.set("days", String(days));
  params.set("compare", String(compare));
  return getJSON<SeoReport>(`/reports/seo?${params}`);
};

// --- Executive report (Phase 16C) ---

export type ExecCard = {
  key: string;
  label: string;
  source: string;
  state: DataStateKey;
  value: number | null;
  unit: "pct" | null;
  comparison: Comparison | null;
  higher_is_better: boolean;
  detail: string | null;
  sample: { numerator: number; denominator: number } | null;
  last_data_date: string | null;
};

export type ExecNarrativeItem = {
  text: string;
  evidence: string[];
  link: { label: string; href: string };
};

export type ExecAction = {
  title: string;
  source_modules: string[];
  impact: string | null;
  effort: string | null;
  supporting_signal_count: number;
  explanation: string | null;
  citations: unknown[];
  state: string | null;
  priority: number | null;
};

export type ExecTopCities =
  | { available: false; reason: "no_ga4" | "no_geography" }
  | {
      available: true;
      reason: null;
      located_share: number | null;
      located_sessions: number;
      total_sessions: number;
      cities: {
        city: string;
        region: string | null;
        sessions: number;
        sessions_share: number | null;
      }[];
      disclosure: string;
    };

export type ExecutiveReport =
  | { scope_required: true; message: string }
  | {
      scope_required: false;
      property_id: number;
      property_name: string;
      window: { days: number; start: string; end: string; anchored_to_latest_data: boolean };
      previous_window: { start: string; end: string };
      compare_requested: boolean;
      cards: ExecCard[];
      narrative: ExecNarrativeItem[];
      top_actions: ExecAction[];
      top_cities: ExecTopCities;
      generated_on: string;
    };

export const fetchExecutiveReport = (
  propertyId: number | null,
  days: number,
  compare: boolean
) => {
  const params = new URLSearchParams();
  if (propertyId !== null) params.set("property_id", String(propertyId));
  params.set("days", String(days));
  params.set("compare", String(compare));
  return getJSON<ExecutiveReport>(`/reports/executive?${params}`);
};

// Download URL for a report section's CSV export (client-safe: no internal
// RAG metadata). Scope precedence matches the report endpoints.
export function reportCsvUrl(
  section: "seo" | "executive" | "geo" | "aeo" | "content-impact" | "audience",
  scope: ReportScope,
  days: number,
  compare: boolean
): string {
  const params = scopeParams(scope);
  if (section === "seo" || section === "executive") {
    params.set("days", String(days));
    params.set("compare", String(compare));
  } else if (section === "audience") {
    params.set("days", String(days));
  }
  return `${API_BASE}/reports/${section}/export.csv?${params}`;
}

// --- GEO Visibility report (Phase 16D) ---

export type RateBlock = {
  value: number | null;
  numerator: number;
  denominator: number;
  minimum_sample: number;
  state: DataStateKey;
};

export type GeoSummary = {
  queries_completed: number;
  platforms_tested: { key: string; label: string }[];
  mention_count: number;
  citation_count: number;
  mention_rate: RateBlock;
  citation_rate: RateBlock;
  owned_domain_citations: number;
  competitor_appearances: number;
  ai_referral_sessions: { sessions: number; last_data_date: string } | null;
  last_run: string | null;
  sufficient: boolean;
};

export type GeoSufficiency = {
  completed_queries: number;
  minimum_required: number;
  sufficient: boolean;
  failed_queries: number;
  not_run_queries: number;
  date_span: { start: string; end: string } | null;
  platforms_represented: string[];
};

export type MatrixCell = {
  platform: string;
  state: string;
  query_id?: number;
  run_date?: string;
};

export type GeoMatrix = {
  platforms: { key: string; label: string }[];
  rows: { prompt: string; cells: MatrixCell[] }[];
};

export type SourceLandscapeDomain = {
  domain: string;
  cited_in_responses: number;
  pct_of_completed: number | null;
  platforms: string[];
  category: string;
  category_label: string;
};

export type CompetitorShare = {
  label: string;
  has_competitors: boolean;
  share_of_voice:
    | {
        queries: number;
        sufficient: boolean;
        total_mentions: number;
        status: string;
        entities: {
          name: string;
          is_property: boolean;
          mentions: number;
          share: number | null;
        }[];
        explanation: string;
      }
    | [];
  limitations: string[];
};

export type GeoTrends = {
  state: DataStateKey;
  points: {
    date: string;
    score: number | null;
    mention_rate: number | null;
    sample_size: number;
    sufficient: boolean;
  }[];
  note: string;
};

export type GeoReport =
  | { scope_required: true; message: string }
  | {
      scope_required: false;
      property_id: number;
      property_name: string;
      has_queries: false;
      methodology: string;
      sufficiency: GeoSufficiency;
      message: string;
    }
  | {
      scope_required: false;
      property_id: number;
      property_name: string;
      has_queries: true;
      methodology: string;
      generated_on: string;
      summary: GeoSummary;
      sufficiency: GeoSufficiency;
      prompt_matrix: GeoMatrix;
      source_landscape: {
        completed_responses: number;
        domains: SourceLandscapeDomain[];
        categories: Record<string, string>;
      };
      competitor_share: CompetitorShare;
      trends: GeoTrends;
    };

export type GeoEvidence = {
  query_id: number;
  prompt: string;
  platform: string;
  platform_label: string;
  run_date: string;
  response_excerpt: string;
  brand_mentioned: boolean;
  cited_domains: string[];
  owned_domains_cited: string[];
  detected_competitors: string[];
};

export const fetchGeoReport = (propertyId: number | null) => {
  const params = new URLSearchParams();
  if (propertyId !== null) params.set("property_id", String(propertyId));
  return getJSON<GeoReport>(`/reports/geo?${params}`);
};

export const fetchGeoEvidence = (propertyId: number, queryId: number) =>
  getJSON<GeoEvidence>(
    `/reports/geo/evidence?property_id=${propertyId}&query_id=${queryId}`
  );

// --- AEO Readiness report (Phase 16E) ---

export type AeoComponent = {
  key: string;
  label: string;
  weight: number;
  raw_value: number | null;
  rule: string;
  explanation: string;
  evidence: string[];
  source_pages: string[];
  excluded: boolean;
  excluded_reason: string | null;
};

export type AeoHeatmapCell = {
  page: string;
  state: "fully_answered" | "partially_answered" | "mentioned_only" | "missing";
  stale: boolean;
  matched_terms: string[];
};

export type AeoHeatmapRow = {
  id: string;
  question: string;
  category: string;
  importance: string;
  cells: AeoHeatmapCell[];
};

export type AeoCitationPage = {
  page: string;
  signals: Record<string, boolean>;
};

export type AeoReport =
  | { scope_required: true; message: string }
  | {
      scope_required: false;
      property_id: number;
      property_name: string;
      property_type_label: string;
      generated_on: string;
      citation_disclaimer: string;
      has_content: false;
      message: string;
      structured_data: { state: DataStateKey; enabled: boolean; message: string };
    }
  | {
      scope_required: false;
      property_id: number;
      property_name: string;
      property_type_label: string;
      generated_on: string;
      citation_disclaimer: string;
      has_content: true;
      score: {
        value: number | null;
        grade: string | null;
        components: AeoComponent[];
        excluded_components: string[];
        note: string;
      };
      question_coverage_summary: {
        answered: number;
        partial: number;
        missing: number;
        total: number;
      };
      heatmap: { pages: string[]; rows: AeoHeatmapRow[] };
      citation_readiness: {
        value: number | null;
        disclaimer: string;
        pages: AeoCitationPage[];
      };
      structured_data: {
        state: DataStateKey;
        enabled: boolean;
        message: string;
        schema_types: string[];
      };
    };

export const fetchAeoReport = (propertyId: number | null) => {
  const params = new URLSearchParams();
  if (propertyId !== null) params.set("property_id", String(propertyId));
  return getJSON<AeoReport>(`/reports/aeo?${params}`);
};

// --- Content Impact report + change log (Phase 16F) ---

export const CHANGE_TYPES = [
  "new_page",
  "expanded_content",
  "faq_update",
  "metadata_update",
  "internal_link_update",
  "structured_data_update",
  "technical_correction",
  "other",
] as const;

export type ChangeType = (typeof CHANGE_TYPES)[number];

export type ContentChange = {
  id: number;
  property_id: number;
  company_id: number | null;
  change_title: string;
  change_type: ChangeType;
  date_implemented: string;
  page_url: string | null;
  notes: string | null;
  related_opportunity: string | null;
  created_by: string | null;
  before_snapshot_ref: string | null;
  after_snapshot_ref: string | null;
  created_at: string;
};

export type ContentChangeInput = {
  change_title: string;
  change_type: ChangeType;
  date_implemented: string;
  page_url?: string | null;
  notes?: string | null;
};

export type ImpactMetric = {
  key: string;
  label: string;
  higher_is_better: boolean;
  before: number | null;
  after: number | null;
  comparison: Comparison | null;
  state: DataStateKey;
};

export type ImpactComparison = {
  days: number;
  before_window: { start: string; end: string };
  after_window: { start: string; end: string };
  after_complete: boolean;
  after_days_elapsed: number;
  metrics: ImpactMetric[];
  caveat: string;
};

export type ContentImpactChange = {
  id: number;
  change_title: string;
  change_type: string;
  date_implemented: string;
  page_url: string | null;
  notes: string | null;
  related_opportunity: string | null;
  comparison: ImpactComparison;
};

export type ContentImpactReport =
  | { scope_required: true; message: string }
  | {
      scope_required: false;
      property_id: number;
      property_name: string;
      window: number;
      available_windows: number[];
      caveat: string;
      has_changes: boolean;
      changes: ContentImpactChange[];
      timeline: { date: string; title: string; type: string }[];
      generated_on: string;
    };

export const fetchContentImpact = (propertyId: number | null, window: number) => {
  const params = new URLSearchParams();
  if (propertyId !== null) params.set("property_id", String(propertyId));
  params.set("window", String(window));
  return getJSON<ContentImpactReport>(`/reports/content-impact?${params}`);
};

export const fetchContentChanges = (propertyId: number) =>
  getJSON<ContentChange[]>(`/content-changes/${propertyId}`);

export async function createContentChange(
  propertyId: number,
  input: ContentChangeInput
): Promise<ContentChange> {
  const res = await fetch(`${API_BASE}/content-changes/${propertyId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

export async function deleteContentChange(propertyId: number, changeId: number): Promise<void> {
  const res = await fetch(`${API_BASE}/content-changes/${propertyId}/${changeId}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
}

// --- Audience geography report (Phase 16G) ---

export type AudienceCity = {
  city: string;
  region: string | null;
  sessions: number;
  engaged_sessions: number;
  key_events: number;
  ai_sessions: number;
  engagement_rate: number | null;
  sessions_share: number | null;
  ai_share: number | null;
};

export type AudienceRegion = {
  region: string;
  sessions: number;
  sessions_share: number | null;
};

export type AudienceTopCity = {
  city: string;
  region: string | null;
  sessions: number;
  sessions_share: number | null;
};

export type AudienceReport =
  | {
      scope_label: string;
      has_data: false;
      geography_available: false;
      message: string;
      generated_on: string;
    }
  | {
      scope_label: string;
      has_data: true;
      geography_available: boolean;
      geography_note: string;
      geography_message: string | null;
      disclosure: string;
      window: { days: number; start: string; end: string; anchored_to_latest_data: boolean };
      last_data_date: string;
      summary: {
        total_sessions: number;
        ai_sessions: number;
        ai_share: number | null;
        located_sessions: number;
        located_share: number | null;
        distinct_cities: number;
        distinct_regions: number;
        top_city: AudienceTopCity | null;
      };
      cities: AudienceCity[];
      cities_shown: number;
      cities_total: number;
      regions: AudienceRegion[];
      generated_on: string;
    };

export const fetchAudienceReport = (scope: ReportScope, days: number) => {
  const params = scopeParams(scope);
  params.set("days", String(days));
  return getJSON<AudienceReport>(`/reports/audience?${params}`);
};
