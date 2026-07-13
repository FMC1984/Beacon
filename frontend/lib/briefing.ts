import { API_BASE } from "@/lib/api";
import type { Comparison, DataStateKey } from "@/lib/reports";

export type BriefingStatus =
  | "excellent"
  | "good"
  | "fair"
  | "needs_attention"
  | "not_enough_data"
  | "not_connected";

export type ModuleHealth = {
  key: string;
  label: string;
  status: BriefingStatus;
  status_label: string;
  reason: string;
  details_href: string;
  evidence: string[];
  healthy: boolean;
};

export type BriefingKpi = {
  key: string;
  label: string;
  source: string;
  state: DataStateKey;
  value: number | null;
  unit: "pct" | null;
  comparison: Comparison | null;
  higher_is_better: boolean;
  detail: string | null;
  last_data_date: string | null;
};

export type BriefingNarrativeItem = {
  text: string;
  evidence: string[];
  link: { label: string; href: string };
};

export type BriefingAction = {
  title: string;
  source_modules: string[];
  impact: string | null;
  effort: string | null;
  supporting_signal_count: number;
  explanation: string | null;
  priority: number | null;
};

export type StoryItem = {
  text: string;
  evidence: string[];
  link: { label: string; href: string };
  source_module: string;
};

export type BriefingStory = {
  wins: StoryItem[];
  risks: StoryItem[];
  trends: StoryItem[];
  note: string;
};

export type IntelCard = {
  key: string;
  label: string;
  state: "ok" | "no_data" | "not_connected";
  what_happened: string;
  biggest_opportunity: string | null;
  href: string;
};

export type CrossSystemObservation = {
  text: string;
  module: string;
  evidence: string[];
  link: { label: string; href: string };
};

export type CrossSystemInsight = {
  kind: "co_movement" | "corroborated_action";
  title: string;
  observations: CrossSystemObservation[];
  framing: string;
};

export type CrossSystem = {
  insights: CrossSystemInsight[];
  note: string;
  empty_reason: string | null;
};

export type StrategicQuestion = {
  text: string;
  why: string;
  evidence: string[];
  link: { label: string; href: string };
  nora_question: string;
};

export type AdaptiveSection = {
  key: string;
  label: string;
  connected: boolean;
  message: string;
  cta: string;
};

export type Briefing = {
  property_id: number;
  property_name: string;
  period: { label: string; start: string; end: string; year: number; month: number };
  comparison_period: { label: string; start: string; end: string };
  health: {
    modules: ModuleHealth[];
    healthy_count: number;
    assessable_count: number;
    summary: string;
  };
  executive_summary: BriefingNarrativeItem[];
  kpis: BriefingKpi[];
  story?: BriefingStory;
  intelligence_cards?: IntelCard[];
  cross_system?: CrossSystem;
  strategic_questions?: StrategicQuestion[];
  top_priorities: BriefingAction[];
  adaptive_sections: AdaptiveSection[];
  generated_on: string;
  frozen?: boolean;
  snapshot_id?: number;
  generated_at?: string;
};

export type BriefingResponse =
  | { scope_required: true; message: string }
  | ({ scope_required: false } & Briefing);

export type BriefingSnapshot = {
  id: number;
  period_label: string | null;
  period_start: string;
  period_end: string;
  generated_at: string;
};

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

export const fetchBriefing = (propertyId: number | null, year?: number, month?: number) => {
  const params = new URLSearchParams();
  if (propertyId !== null) params.set("property_id", String(propertyId));
  if (year && month) {
    params.set("year", String(year));
    params.set("month", String(month));
  }
  return getJSON<BriefingResponse>(`/briefing?${params}`);
};

export const fetchBriefingHistory = (propertyId: number) =>
  getJSON<{ property_id: number; snapshots: BriefingSnapshot[] }>(
    `/briefing/history?property_id=${propertyId}`
  );

export const fetchBriefingSnapshot = (id: number) =>
  getJSON<BriefingResponse>(`/briefing/${id}`);

// --- Strategist (17D) ---

export type StrategistFact = { n: number; kind: string; text: string; href: string };

export type StrategistRec = {
  title: string;
  why: string;
  impact: string | null;
  effort: string | null;
  grounding: { n: number; text: string; href: string }[];
};

export type Strategist = {
  state: "ok" | "insufficient_data" | "unavailable" | "no_grounded_output";
  provider?: string;
  message?: string | null;
  facts: StrategistFact[];
  recommendations: StrategistRec[];
  disclosure: string;
};

export async function fetchStrategist(
  propertyId: number,
  year?: number,
  month?: number
): Promise<Strategist> {
  const params = new URLSearchParams({ property_id: String(propertyId) });
  if (year && month) {
    params.set("year", String(year));
    params.set("month", String(month));
  }
  const res = await fetch(`${API_BASE}/briefing/strategist?${params}`, { method: "POST" });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

// --- Share (17D) ---

export async function shareBriefing(id: number): Promise<{ token: string; path: string }> {
  const res = await fetch(`${API_BASE}/briefing/${id}/share`, { method: "POST" });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

export async function revokeBriefingShare(id: number): Promise<void> {
  const res = await fetch(`${API_BASE}/briefing/${id}/share`, { method: "DELETE" });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
}

export const fetchSharedBriefing = (token: string) =>
  getJSON<BriefingResponse>(`/briefing/shared/${encodeURIComponent(token)}`);

export async function generateBriefing(
  propertyId: number,
  year?: number,
  month?: number
): Promise<{ id: number; period: { label: string } }> {
  const params = new URLSearchParams({ property_id: String(propertyId) });
  if (year && month) {
    params.set("year", String(year));
    params.set("month", String(month));
  }
  const res = await fetch(`${API_BASE}/briefing/generate?${params}`, { method: "POST" });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}
