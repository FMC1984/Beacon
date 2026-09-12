/** Types and small helpers shared by the legacy AI Visibility panels (moved
 * verbatim from app/ai-visibility/page.tsx in Phase 19 slice 4). */

export type QueryRow = {
  id: number;
  platform: string;
  prompt_text: string;
  raw_response_text: string;
  executed_at: string;
  brand_mentioned: boolean;
  sources_cited: string[] | null;
  run_id?: number | null;
  provider?: string | null;
  model?: string | null;
};

// Phase 19: the run ledger + provider-reported evidence for one response.
// Every block carries a data-integrity label from the backend.
export type ObservationDetail = {
  run: {
    status: string;
    provider: string;
    model: string | null;
    latency_ms: number | null;
    browsed: boolean | null;
    tokens: {
      label: string;
      input: number | null;
      output: number | null;
      reasoning: number | null;
      search_operations: number;
    };
    cost: { label: string; estimated_usd: number | null; pricing_version: string | null; note: string };
  } | null;
  citations: {
    label: string;
    capture: string;
    note: string;
    items: { url: string; domain: string; title: string | null; source_type: string; capture_method: string }[];
  };
  search_queries: { label: string; note: string; items: { query: string }[] };
};

export const LABEL_CHIP: Record<string, string> = {
  OBSERVED: "bg-emerald-a/15 text-emerald-a",
  MEASURED: "bg-cyan-a/15 text-cyan-a",
  MODELED: "bg-amber-a/15 text-amber-a",
  UNAVAILABLE: "bg-line/60 text-muted",
};

export function LabelChip({ label }: { label: string }) {
  return (
    <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium tracking-wide ${LABEL_CHIP[label] ?? LABEL_CHIP.UNAVAILABLE}`}>
      {label}
    </span>
  );
}

export type Budget = {
  limit_per_day: number;
  used_today: number;
  remaining_today: number;
  exhausted: boolean;
};

export type PlatformInfo = { key: string; label: string; live: boolean };
export type Meta = {
  platforms: PlatformInfo[];
  methodology: { approach: string; statement: string; known_limitations: string[] };
  provider: string;
};

export type Analysis = {
  has_queries: boolean;
  date_range?: { start: string; end: string };
  sample?: { total_queries: number; sufficient: boolean; minimum: number };
  mention?: { mentions: number; queries: number; rate: number | null; status: string; explanation: string } | null;
  by_platform?: {
    label: string;
    queries: number;
    mentions: number;
    mention_rate: number | null;
    mention_rate_status: string;
    top_sources: { domain: string; count: number }[];
  }[];
  source_landscape?: { domain: string; cited_in_queries: number }[];
  own_site?: { domain: string | null; status: string; explanation: string } | null;
  fact_checks?: {
    contradictions: { field: string; known_value: string; evidence: string; platform: string }[];
    cannot_verify_count: number;
  };
  score?: {
    value: number;
    grade: string;
    directional: boolean;
    breakdown: { component: string; score: number; weight: number; explanation: string }[];
  } | null;
  recommendations?: { title: string; reason: string; state: string; gate_reason: string | null }[];
  limitations?: string[];
  deferred?: string[];
};

export const REC_CHIP: Record<string, string> = {
  Actionable: "bg-emerald-a/15 text-emerald-a",
  Monitor: "bg-cyan-a/15 text-cyan-a",
  "Requires confirmation": "bg-amber-a/15 text-amber-a",
  Suppressed: "bg-pink-a/15 text-pink-a",
  "Insufficient data": "bg-line/60 text-muted",
};

export function pct(v: number) {
  return `${Math.round(v * 100)}%`;
}

export function fmtWhen(iso: string) {
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

