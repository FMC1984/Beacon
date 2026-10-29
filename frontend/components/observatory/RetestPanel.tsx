"use client";

/** Did the fix work?
 *
 * A retest stores two measurements, not a series, so this draws exactly that:
 * the before and the after as a pair. The sentence under them is the one the
 * retest rule wrote, including its own association caveat, rather than a
 * fresh claim made here. The panel renders nothing when no action has been
 * tracked, since an empty "did it work" box reads as a failure.
 */

import type { ActionOutcome, TrackedAction } from "@/lib/observatory";
import { fetchTrackedActions } from "@/lib/observatory";
import { Panel, useLoad } from "./ui";

const OUTCOME: Record<ActionOutcome, { text: string; cls: string }> = {
  resolved: { text: "Fixed", cls: "bg-emerald-a/15 text-emerald-a" },
  improved: { text: "Improved", cls: "bg-emerald-a/15 text-emerald-a" },
  persists: { text: "Still there", cls: "bg-pink-a/15 text-pink-a" },
  declined: { text: "Went down", cls: "bg-pink-a/15 text-pink-a" },
  no_change: { text: "No change", cls: "bg-surface-raised text-muted" },
  inconclusive: { text: "Cannot tell yet", cls: "bg-amber-a/15 text-amber-a" },
};

const OPEN_STATUS: Record<string, string> = {
  open: "Not started",
  in_progress: "In progress",
  implemented: "Done, waiting on the retest",
};

type Measure = { value: number | null; numerator: number; denominator: number };

function pair(action: TrackedAction): { before: Measure; after: Measure } | null {
  const r = action.result as { before?: Measure; after?: Measure } | null;
  if (!r?.before || !r?.after || r.before.value === null || r.after.value === null) return null;
  return { before: r.before, after: r.after };
}

function Bar({ caption, m, tone }: { caption: string; m: Measure; tone: string }) {
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2 text-xs text-muted">
        <span>{caption}</span>
        <span className="tabular-nums">
          {m.numerator} of {m.denominator}
        </span>
      </div>
      <div className="mt-1">
        <span className="block h-5 rounded-md bg-surface-raised">
          <span className={`block h-5 rounded-md ${tone}`} style={{ width: `${Math.max((m.value ?? 0) * 100, 1.5)}%` }} />
        </span>
      </div>
    </div>
  );
}

export function RetestPanel({ propertyId }: { propertyId: number }) {
  const { data } = useLoad(() => fetchTrackedActions(propertyId), [propertyId]);
  if (!data) return null;

  const retested = data.actions
    .filter((a) => a.status === "retested" && a.outcome)
    .sort((a, b) => (b.retested_at ?? "").localeCompare(a.retested_at ?? ""));
  const stillOpen = data.actions.filter((a) => a.status in OPEN_STATUS);
  if (retested.length === 0 && stillOpen.length === 0) return null;

  const latest = retested[0];
  const measures = latest ? pair(latest) : null;

  return (
    <Panel
      title="Did the fix work?"
      label="MEASURED"
      subtitle="CiteRoll re-measures the evidence an action came from, then reports what moved."
    >
      {latest ? (
        <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
          <div>
            <div className="flex items-start justify-between gap-2">
              <p className="text-sm font-medium">{latest.title}</p>
              <span
                className={`shrink-0 rounded-full px-2.5 py-0.5 text-xs ${OUTCOME[latest.outcome as ActionOutcome].cls}`}
              >
                {OUTCOME[latest.outcome as ActionOutcome].text}
              </span>
            </div>
            {latest.implemented_on && (
              <p className="mt-1 text-xs text-muted">Implemented {latest.implemented_on}</p>
            )}
            {measures && (
              <div className="mt-3 space-y-2.5">
                <Bar caption="Before" m={measures.before} tone="bg-line" />
                <Bar caption="Since" m={measures.after} tone="bg-emerald-a" />
              </div>
            )}
            {latest.result?.sentence && <p className="mt-3 text-sm text-muted">{latest.result.sentence}</p>}
          </div>

          <div>
            <p className="text-xs text-muted">
              {stillOpen.length === 0
                ? "Nothing else is being tracked right now."
                : `${stillOpen.length} other${stillOpen.length === 1 ? "" : "s"} being tracked`}
            </p>
            <ul className="mt-2 space-y-2.5">
              {stillOpen.slice(0, 3).map((a) => (
                <li key={a.id} className="flex items-start justify-between gap-3 border-t border-line pt-2.5 first:border-0 first:pt-0">
                  <span className="text-sm">{a.title}</span>
                  <span className="shrink-0 text-xs text-muted">{OPEN_STATUS[a.status]}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      ) : (
        <>
          <p className="text-sm text-muted">
            Nothing has been retested yet. {stillOpen.length} action{stillOpen.length === 1 ? " is" : "s are"} being tracked.
          </p>
          <ul className="mt-2 space-y-2.5">
            {stillOpen.slice(0, 3).map((a) => (
              <li key={a.id} className="flex items-start justify-between gap-3 border-t border-line pt-2.5 first:border-0 first:pt-0">
                <span className="text-sm">{a.title}</span>
                <span className="shrink-0 text-xs text-muted">{OPEN_STATUS[a.status]}</span>
              </li>
            ))}
          </ul>
        </>
      )}
      <p className="mt-3 text-xs text-muted">{data.note}</p>
    </Panel>
  );
}
