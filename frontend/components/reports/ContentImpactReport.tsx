"use client";

/** Content Impact report (Phase 16F). Records website changes and shows
 * performance in the equal windows before and after each change date. This is
 * observational, never causal: the external-factors caveat rides on every
 * comparison, and an after-window that has not fully elapsed is disclosed, not
 * shown as a drop to zero. */

import { useEffect, useState } from "react";
import { fmtDate, fmtNum, fmtPct } from "@/lib/format";
import {
  CHANGE_TYPES,
  createContentChange,
  deleteContentChange,
  fetchContentImpact,
  type ChangeType,
  type ContentImpactChange,
  type ContentImpactReport as ImpactData,
  type ImpactMetric,
} from "@/lib/reports";
import { EmptyState, ErrorState, StateBadge } from "./DataStates";
import { useReportContext } from "./ReportContext";

const TYPE_LABELS: Record<string, string> = {
  new_page: "New page",
  expanded_content: "Expanded content",
  faq_update: "FAQ update",
  metadata_update: "Metadata update",
  internal_link_update: "Internal-link update",
  structured_data_update: "Structured-data update",
  technical_correction: "Technical correction",
  other: "Other",
};

function fmtMetric(m: ImpactMetric, which: "before" | "after"): string {
  const v = m[which];
  if (v === null) return "n/a";
  if (m.key === "ctr") return fmtPct(v);
  if (m.key === "position") return v.toFixed(1);
  return fmtNum(v);
}

function ChangeCard({ change }: { change: ContentImpactChange }) {
  const cmp = change.comparison;
  return (
    <div className="rounded-2xl border border-line bg-surface p-5">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="font-medium">{change.change_title}</p>
          <p className="mt-0.5 text-xs text-muted">
            {TYPE_LABELS[change.change_type] ?? change.change_type} · implemented{" "}
            {fmtDate(change.date_implemented)}
            {change.page_url && ` · ${change.page_url}`}
          </p>
        </div>
        {!cmp.after_complete && (
          <span className="inline-flex items-center gap-1.5 rounded-full border border-amber-a/40 bg-amber-a/10 px-2.5 py-0.5 text-[11px] text-amber-a">
            After window still accumulating ({cmp.after_days_elapsed}/{cmp.days} days)
          </span>
        )}
      </div>

      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs text-muted">
              <th className="py-2 pr-3 font-medium">Metric</th>
              <th className="py-2 pr-3 text-right font-medium">
                Before ({fmtDate(cmp.before_window.start)}–{fmtDate(cmp.before_window.end)})
              </th>
              <th className="py-2 pr-3 text-right font-medium">
                After ({fmtDate(cmp.after_window.start)}–{fmtDate(cmp.after_window.end)})
              </th>
              <th className="py-2 text-right font-medium">Observed change</th>
            </tr>
          </thead>
          <tbody>
            {cmp.metrics.map((m) => {
              const change2 = m.comparison?.change ?? null;
              const improved =
                change2 !== null && change2 !== 0
                  ? (change2 > 0) === m.higher_is_better
                  : null;
              return (
                <tr key={m.key} className="border-b border-line/50">
                  <td className="py-2 pr-3">{m.label}</td>
                  <td className="py-2 pr-3 text-right">{fmtMetric(m, "before")}</td>
                  <td className="py-2 pr-3 text-right">{fmtMetric(m, "after")}</td>
                  <td className="py-2 text-right">
                    {m.comparison && change2 !== null ? (
                      <span
                        className={
                          improved === true
                            ? "text-emerald-a"
                            : improved === false
                            ? "text-pink-a"
                            : "text-muted"
                        }
                      >
                        {change2 > 0 ? "+" : ""}
                        {m.key === "ctr"
                          ? fmtPct(change2)
                          : m.key === "position"
                          ? change2.toFixed(1)
                          : fmtNum(change2)}
                      </span>
                    ) : (
                      <span className="text-muted">n/a</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-3 border-t border-line/60 pt-2 text-[11px] leading-snug text-muted">
        {cmp.caveat}
      </p>
    </div>
  );
}

function AddChangeForm({ propertyId, onAdded }: { propertyId: number; onAdded: () => void }) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [type, setType] = useState<ChangeType>("expanded_content");
  const [dateVal, setDateVal] = useState("");
  const [pageUrl, setPageUrl] = useState("");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim() || !dateVal) {
      setErr("Title and date are required.");
      return;
    }
    setSaving(true);
    setErr(null);
    try {
      await createContentChange(propertyId, {
        change_title: title.trim(),
        change_type: type,
        date_implemented: dateVal,
        page_url: pageUrl.trim() || null,
      });
      setTitle("");
      setPageUrl("");
      setDateVal("");
      setOpen(false);
      onAdded();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : String(e2));
    } finally {
      setSaving(false);
    }
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="rounded-xl border border-violet-a/50 bg-violet-a/15 px-3 py-2 text-sm text-foreground transition-colors hover:bg-violet-a/25"
      >
        Record a content change
      </button>
    );
  }
  return (
    <form onSubmit={submit} className="rounded-2xl border border-line bg-surface p-5">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className="text-sm">
          <span className="mb-1 block text-xs text-muted">Change title</span>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="w-full rounded-lg border border-line bg-surface-raised px-3 py-2"
            placeholder="e.g. Expanded maintenance FAQ"
          />
        </label>
        <label className="text-sm">
          <span className="mb-1 block text-xs text-muted">Change type</span>
          <select
            value={type}
            onChange={(e) => setType(e.target.value as ChangeType)}
            className="w-full rounded-lg border border-line bg-surface-raised px-3 py-2"
          >
            {CHANGE_TYPES.map((t) => (
              <option key={t} value={t}>
                {TYPE_LABELS[t]}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          <span className="mb-1 block text-xs text-muted">Date implemented</span>
          <input
            type="date"
            value={dateVal}
            onChange={(e) => setDateVal(e.target.value)}
            className="w-full rounded-lg border border-line bg-surface-raised px-3 py-2"
          />
        </label>
        <label className="text-sm">
          <span className="mb-1 block text-xs text-muted">Page URL (optional)</span>
          <input
            value={pageUrl}
            onChange={(e) => setPageUrl(e.target.value)}
            className="w-full rounded-lg border border-line bg-surface-raised px-3 py-2"
            placeholder="/faq"
          />
        </label>
      </div>
      {err && <p className="mt-2 text-sm text-pink-a">{err}</p>}
      <div className="mt-3 flex gap-2">
        <button
          type="submit"
          disabled={saving}
          className="rounded-xl border border-violet-a/50 bg-violet-a/15 px-3 py-2 text-sm disabled:opacity-60"
        >
          {saving ? "Saving..." : "Save change"}
        </button>
        <button
          type="button"
          onClick={() => setOpen(false)}
          className="rounded-xl border border-line px-3 py-2 text-sm text-muted"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}

export function ContentImpactReport() {
  const { scope } = useReportContext();
  const [window, setWindow] = useState(30);
  const [data, setData] = useState<ImpactData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    fetchContentImpact(scope.propertyId, window)
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope.propertyId, window, attempt]);

  if (error) return <ErrorState message={error} onRetry={() => setAttempt((a) => a + 1)} />;
  if (!data) return <p className="text-sm text-muted">Loading content impact...</p>;
  if (data.scope_required) return <EmptyState title="Select a property" body={data.message} />;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div
          role="group"
          aria-label="Comparison window"
          className="flex items-center rounded-xl border border-line bg-surface p-1"
        >
          {data.available_windows.map((w) => (
            <button
              key={w}
              onClick={() => setWindow(w)}
              aria-pressed={window === w}
              className={`rounded-lg px-3 py-1 text-sm transition-colors ${
                window === w
                  ? "bg-surface-raised font-medium text-foreground"
                  : "text-muted hover:text-foreground"
              }`}
            >
              {w}d before/after
            </button>
          ))}
        </div>
        <AddChangeForm propertyId={data.property_id} onAdded={() => setAttempt((a) => a + 1)} />
      </div>

      <div className="rounded-xl border border-amber-a/30 bg-amber-a/10 px-4 py-2.5 text-sm text-amber-a">
        {data.caveat}
      </div>

      {!data.has_changes ? (
        <EmptyState
          title="No content changes recorded"
          body="Record a website or optimization change to see performance in the windows before and after its date."
        />
      ) : (
        <div className="space-y-4">
          {data.changes.map((c) => (
            <ChangeCard key={c.id} change={c} />
          ))}
        </div>
      )}
    </div>
  );
}
