export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8600/api";

// Persisted company scope, shared across the dashboard and every ScopeSelect so
// a chosen company survives navigation. Values: "all" | "unassigned" | "<id>".
export const SCOPE_STORAGE_KEY = "beacon.companyScope";

export type Provenance = {
  source: string;
  date_start: string;
  date_end: string;
  last_updated: string | null;
  freshness_warning: string | null;
};

export type GA4Section = {
  sessions: number;
  ai_sessions: number;
  ai_share: number;
  key_events: number;
  ai_key_events: number;
  trend: { date: string; sessions: number; ai_sessions: number }[];
  platform_mix: { platform: string; label: string; sessions: number }[];
  disclosure: string;
  provenance: Provenance;
};

export type GSCSection = {
  clicks: number;
  impressions: number;
  ctr: number;
  avg_position: number;
  provenance: Provenance;
};

export type GBPSection = {
  search_impressions: number;
  maps_impressions: number;
  website_clicks: number;
  calls: number;
  direction_requests: number;
  provenance: Provenance;
};

export type PaidSection = {
  spend: number;
  clicks: number;
  impressions: number;
  conversions: number;
  by_platform: {
    platform: string;
    spend: number;
    clicks: number;
    impressions: number;
    conversions: number;
  }[];
  provenance: Provenance;
};

export type CRMSection = {
  total_leads: number;
  funnel: Record<"lead" | "tour" | "application" | "lease" | "lost", number>;
  provenance: Provenance;
};

export type EventRow = {
  event_name: string;
  event_count: number;
  total_users: number;
  count_share: number | null;
  per_user: number | null;
};

export type EventsSection = {
  total_event_count: number;
  distinct_events: number;
  events: EventRow[];
  events_shown: number;
  events_total: number;
  note: string;
  provenance: Provenance;
};

export type Dashboard = {
  window: {
    days: number;
    start: string;
    end: string;
    anchored_to_latest_data: boolean;
  };
  ga4: GA4Section | null;
  events: EventsSection | null;
  gsc: GSCSection | null;
  gbp: GBPSection | null;
  paid: PaidSection | null;
  crm: CRMSection | null;
};

export type Property = {
  id: number;
  name: string;
  slug: string;
  property_type: string;
  company_id: number | null;
  city: string | null;
  state: string | null;
  unit_count: number | null;
  website_url: string | null;
};

export type PropertyTypeInfo = {
  label: string;
  short_label: string;
  description: string;
  terminology: Record<string, string>;
  allowed_connectors: string[];
};

export type PropertyTypesConfig = {
  default: string;
  types: Record<string, PropertyTypeInfo>;
};

export const fetchPropertyTypes = () =>
  getJSON<PropertyTypesConfig>("/properties/types/config");

export type Company = {
  id: number;
  name: string;
  slug: string;
  created_at: string;
  property_count: number;
};

export type UploadRecord = {
  id: number;
  source_type: string;
  property_id: number | null;
  filename: string;
  source_account: string | null;
  date_start: string | null;
  date_end: string | null;
  status: "pending" | "processed" | "failed";
  row_count: number | null;
  error_message: string | null;
  uploaded_at: string;
};

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

export const fetchProperties = () => getJSON<Property[]>("/properties");
export const fetchCompanies = () => getJSON<Company[]>("/companies");
export const fetchUploads = () => getJSON<UploadRecord[]>("/uploads");

export function fetchDashboard(
  propertyId: number | null,
  days: number,
  companyId: number | null = null,
  unassigned = false
) {
  const params = new URLSearchParams({ days: String(days) });
  if (propertyId !== null) params.set("property_id", String(propertyId));
  else if (unassigned) params.set("unassigned", "true");
  else if (companyId !== null) params.set("company_id", String(companyId));
  return getJSON<Dashboard>(`/dashboard?${params}`);
}

// Download URL for the CSV/ZIP data export. Scope precedence: property, then
// unassigned, then company, then whole portfolio.
export function exportUrl(
  propertyId: number | null,
  companyId: number | null = null,
  unassigned = false
): string {
  const params = new URLSearchParams();
  if (propertyId !== null) params.set("property_id", String(propertyId));
  else if (unassigned) params.set("unassigned", "true");
  else if (companyId !== null) params.set("company_id", String(companyId));
  const qs = params.toString();
  return `${API_BASE}/export${qs ? `?${qs}` : ""}`;
}
