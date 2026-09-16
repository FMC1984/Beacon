"use client";

/** Small shared pieces for the Observatory tabs: the data-label badge, the
 * formula explainer, metric cards, share bars, and loading/empty wrappers. */

import { useEffect, useState, type ReactNode } from "react";
import { EmptyState, ErrorState, StateBadge } from "@/components/reports/DataStates";
import type { DataLabel, ObsMetric } from "@/lib/observatory";
import { fmtRate } from "@/lib/observatory";

const LABEL_STYLE: Record<DataLabel, { cls: string; hint: string }> = {
  OBSERVED: {
    cls: "border-emerald-a/40 bg-emerald-a/10 text-emerald-a",
    hint: "Exactly what an AI provider returned for Beacon's monitoring call.",
  },
  MEASURED: {
    cls: "border-cyan-a/40 bg-cyan-a/10 text-cyan-a",
    hint: "Counted by Beacon from stored observations.",
  },
  MODELED: {
    cls: "border-amber-a/40 bg-amber-a/10 text-amber-a",
    hint: "Produced by a stated rule or weighted model, not observed directly.",
  },
  UNAVAILABLE: {
    cls: "border-line bg-surface-raised text-muted",
    hint: "Beacon does not have this data, so no number is shown.",
  },
};

export function DataLabelBadge({ label }: { label: DataLabel }) {
  const s = LABEL_STYLE[label] ?? LABEL_STYLE.UNAVAILABLE;
  return (
    <span
      title={s.hint}
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold tracking-wide ${s.cls}`}
    >
      {label}
    </span>
  );
}

/** "How is this calculated?" disclosure; keyboard and touch friendly. */
export function FormulaNote({ formula, note }: { formula: string; note?: string | null }) {
  return (
    <details className="group mt-2 text-[11px] text-muted">
      <summary className="cursor-pointer select-none list-none underline decoration-dotted underline-offset-2 hover:text-foreground">
        How is this calculated?
      </summary>
      <p className="mt-1">{formula}</p>
      {note && <p className="mt-0.5">{note}</p>}
    </details>
  );
}

const SAMPLE_UNIT: Record<string, string> = {
  citation_share: "tracked citations",
  share_of_voice: "tracked mentions",
  prompt_coverage: "priority clusters",
};

function unit(key: string, n: number) {
  const u = SAMPLE_UNIT[key] ?? "monitored responses";
  return n === 1 ? u.replace(/s$/, "").replace("responses", "response") : u;
}

export function ObsMetricCard({ metric, onDrill }: { metric: ObsMetric; onDrill?: (metric: string) => void }) {
  const complete = metric.state === "complete" && metric.value !== null;
  const clickable = Boolean(onDrill) && complete;
  const cmp = metric.comparison;
  const pts = complete && cmp && cmp.point_change !== null ? Math.round(cmp.point_change * 100) : null;
  const higherIsBetter = metric.key !== "competitor_win_rate";
  const tone =
    pts === null || pts === 0
      ? "text-muted"
      : (pts > 0) === higherIsBetter
      ? "text-emerald-a"
      : "text-pink-a";
  const Wrapper = clickable ? "button" : "div";
  return (
    <Wrapper
      {...(clickable ? { type: "button" as const, onClick: () => onDrill?.(metric.key), "aria-haspopup": "dialog" as const } : {})}
      className={`flex w-full flex-col rounded-2xl border border-line bg-surface p-5 text-left ${
        clickable ? "cursor-pointer transition-colors hover:border-violet-a/50 hover:bg-surface-raised" : ""
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm text-muted">{metric.label}</p>
        <span className="flex items-center gap-1.5">
          {clickable && <span className="text-[11px] text-muted" aria-hidden>details ›</span>}
          {complete ? <DataLabelBadge label={metric.data_label} /> : <StateBadge state={metric.state} />}
        </span>
      </div>
      {complete ? (
        <>
          <p className="mt-1 text-3xl font-semibold tracking-tight">{fmtRate(metric.value)}</p>
          <p className="mt-1 text-xs text-muted">
            {metric.numerator} of {metric.denominator} {unit(metric.key, metric.denominator)}
          </p>
          {cmp && (
            <p className={`mt-0.5 text-xs ${tone}`}>
              {pts === null
                ? "No comparable previous period."
                : `${pts > 0 ? "+" : ""}${pts} pts vs previous period`}
            </p>
          )}
        </>
      ) : (
        <p className="mt-2 text-sm text-muted">
          {metric.state === "insufficient_sample"
            ? metric.sample_size !== undefined
              ? `Needs at least ${metric.minimum_sample} monitored responses; ${metric.sample_size} so far.`
              : `Needs at least ${metric.minimum_sample} ${unit(metric.key, metric.minimum_sample)}; ${metric.denominator} so far.`
            : metric.value === null
            ? "Nobody tracked was mentioned in these responses, so there is no share to show."
            : "No value is shown because the data is not available."}
        </p>
      )}
      <div className="mt-auto" onClick={(e) => e.stopPropagation()}>
        <FormulaNote formula={metric.formula} note={metric.note} />
      </div>
    </Wrapper>
  );
}

export function ShareBar({ value, tone = "violet" }: { value: number | null; tone?: "violet" | "cyan" | "emerald" }) {
  const width = value === null ? 0 : Math.max(2, Math.round(value * 100));
  const color = tone === "cyan" ? "bg-cyan-a" : tone === "emerald" ? "bg-emerald-a" : "bg-violet-a";
  return (
    <div className="h-1.5 w-full rounded-full bg-line/60" aria-hidden>
      <div className={`h-1.5 rounded-full ${color}`} style={{ width: `${width}%` }} />
    </div>
  );
}

export function Panel({
  title,
  label,
  actions,
  children,
  subtitle,
}: {
  title: string;
  label?: DataLabel;
  actions?: ReactNode;
  subtitle?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="rounded-2xl border border-line bg-surface p-5">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-medium">{title}</h2>
            {label && <DataLabelBadge label={label} />}
          </div>
          {subtitle && <p className="mt-0.5 text-xs text-muted">{subtitle}</p>}
        </div>
        {actions}
      </div>
      {children}
    </section>
  );
}

/** Load-on-change helper: tracks loading, error and data for one fetch.
 * State is only set from the promise callbacks; "loading" is derived by
 * comparing the current request key with the last settled one. */
export function useLoad<T>(fn: (() => Promise<T>) | null, deps: unknown[]) {
  const [nonce, setNonce] = useState(0);
  const key = JSON.stringify([...deps, nonce]);
  const [settled, setSettled] = useState<{ key: string; data: T | null; error: string | null } | null>(null);

  useEffect(() => {
    if (!fn) return;
    let cancelled = false;
    fn()
      .then((d) => !cancelled && setSettled({ key, data: d, error: null }))
      .catch((e: Error) =>
        !cancelled && setSettled((prev) => ({ key, data: prev?.data ?? null, error: e.message || "Could not reach the Beacon API." }))
      );
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return {
    data: settled?.data ?? null,
    error: settled?.key === key ? settled.error : null,
    loading: fn !== null && settled?.key !== key,
    retry: () => setNonce((n) => n + 1),
  };
}

export function LoadState({
  loading,
  error,
  retry,
  empty,
  children,
}: {
  loading: boolean;
  error: string | null;
  retry: () => void;
  empty?: { when: boolean; title: string; body: string };
  children: ReactNode;
}) {
  if (error) return <ErrorState message={error} onRetry={retry} />;
  if (loading) return <p className="text-sm text-muted">Loading...</p>;
  if (empty?.when) return <EmptyState title={empty.title} body={empty.body} />;
  return <>{children}</>;
}

export function NeedsProperty() {
  return (
    <EmptyState
      title="Choose a property"
      body="Observatory metrics are property scoped. Pick a property above to see how AI answers treat it."
    />
  );
}
