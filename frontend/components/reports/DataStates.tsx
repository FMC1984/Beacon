/** Shared data-state rendering for the Reports section (Phase 16A).
 *
 * Hard rule: a missing, delayed, or unconfigured source is shown as a labeled
 * state, never as a zero. Color is never the only indicator; every badge
 * carries its text label. */

import type { DataStateKey } from "@/lib/reports";
import { fmtDate } from "@/lib/format";

type Tone = "ok" | "info" | "warn" | "bad";

export const STATE_META: Record<DataStateKey, { label: string; tone: Tone }> = {
  complete: { label: "Complete", tone: "ok" },
  partial_period: { label: "Partial period", tone: "warn" },
  awaiting_data: { label: "Awaiting data", tone: "info" },
  source_delayed: { label: "Source delayed", tone: "warn" },
  not_configured: { label: "Not configured", tone: "info" },
  insufficient_sample: { label: "Insufficient sample", tone: "info" },
  failed_source: { label: "Source failed", tone: "bad" },
  empty: { label: "No data in range", tone: "info" },
};

const TONE_CLASSES: Record<Tone, string> = {
  ok: "border-emerald-a/40 bg-emerald-a/10 text-emerald-a",
  info: "border-line bg-surface-raised text-muted",
  warn: "border-amber-a/40 bg-amber-a/10 text-amber-a",
  bad: "border-pink-a/40 bg-pink-a/10 text-pink-a",
};

export function StateBadge({ state }: { state: DataStateKey }) {
  const meta = STATE_META[state] ?? { label: state, tone: "info" as Tone };
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-medium ${TONE_CLASSES[meta.tone]}`}
    >
      <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-current" />
      {meta.label}
    </span>
  );
}

/** Every sampled rate travels with its sample: "8 of 21 queries". */
export function SampleBadge({
  numerator,
  denominator,
  unit,
}: {
  numerator: number;
  denominator: number;
  unit: string;
}) {
  return (
    <span className="inline-flex items-center rounded-full border border-line bg-surface-raised px-2.5 py-0.5 text-[11px] text-muted">
      {numerator} of {denominator} {unit}
    </span>
  );
}

export function SourceBadge({ source }: { source: string }) {
  return (
    <span className="inline-flex items-center rounded-full border border-line px-2.5 py-0.5 text-[11px] text-muted">
      {source}
    </span>
  );
}

export function FreshnessFooter({
  source,
  lastDataDate,
  detail,
}: {
  source: string;
  lastDataDate: string | null;
  detail?: string;
}) {
  return (
    <p className="mt-3 border-t border-line/60 pt-2 text-[11px] text-muted">
      {source}
      {lastDataDate
        ? ` · complete through ${fmtDate(lastDataDate)}`
        : " · no data yet"}
      {detail ? ` · ${detail}` : ""}
    </p>
  );
}

export function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-2xl border border-dashed border-line bg-surface/50 p-8 text-center">
      <p className="text-sm font-medium">{title}</p>
      <p className="mx-auto mt-1 max-w-md text-sm text-muted">{body}</p>
    </div>
  );
}

export function ErrorState({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div
      role="alert"
      className="rounded-2xl border border-pink-a/40 bg-pink-a/10 p-5"
    >
      <p className="text-sm font-medium text-pink-a">Could not load this section</p>
      <p className="mt-1 text-sm text-muted">{message}</p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="mt-3 rounded-lg border border-line bg-surface px-3 py-1.5 text-sm transition-colors hover:bg-surface-raised"
        >
          Retry
        </button>
      )}
    </div>
  );
}
