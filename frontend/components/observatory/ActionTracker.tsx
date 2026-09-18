"use client";

/** Action lifecycle: track an action, move it open -> in progress ->
 * implemented, and read the automatic retest against the evidence it came
 * from. TrackButton is dropped onto any surface that shows an action; the
 * ActionTrackerPanel lists them all for one property. */

import { useState } from "react";
import { fmtDate } from "@/lib/format";
import {
  fetchTrackedActions,
  retestTrackedAction,
  trackAction,
  updateTrackedAction,
  type ActionOutcome,
  type ActionRef,
  type ActionStatus,
  type TrackPayload,
  type TrackedAction,
} from "@/lib/observatory";
import { LoadState, Panel, useLoad } from "./ui";

export const STATUS_TEXT: Record<ActionStatus, { text: string; cls: string }> = {
  open: { text: "Tracked", cls: "bg-surface-raised text-foreground/80" },
  in_progress: { text: "In progress", cls: "bg-violet-a/15 text-violet-a" },
  implemented: { text: "Awaiting retest", cls: "bg-cyan-500/15 text-cyan-300" },
  retested: { text: "Retested", cls: "bg-surface-raised text-foreground/80" },
  done: { text: "Done", cls: "bg-emerald-500/15 text-emerald-300" },
  dismissed: { text: "Dismissed", cls: "bg-surface-raised text-muted" },
};

export const OUTCOME_TEXT: Record<ActionOutcome, { text: string; cls: string }> = {
  resolved: { text: "Resolved", cls: "bg-emerald-500/15 text-emerald-300" },
  improved: { text: "Improved", cls: "bg-emerald-500/15 text-emerald-300" },
  persists: { text: "Still there", cls: "bg-rose-500/15 text-rose-300" },
  declined: { text: "Declined", cls: "bg-rose-500/15 text-rose-300" },
  no_change: { text: "No change", cls: "bg-amber-500/15 text-amber-300" },
  inconclusive: { text: "Inconclusive", cls: "bg-surface-raised text-muted" },
};

export function ActionChip({ action }: { action: ActionRef }) {
  if (!action) return null;
  const s = action.outcome ? OUTCOME_TEXT[action.outcome] : STATUS_TEXT[action.status];
  return <span className={`rounded-full px-2 py-0.5 text-[11px] ${s.cls}`}>{s.text}</span>;
}

/** Track this action, or show its current state if it is already tracked. */
export function TrackButton({ payload, current, label = "Track" }: { payload: TrackPayload; current?: ActionRef; label?: string }) {
  const [state, setState] = useState<ActionRef | undefined>(current);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  if (state) return <ActionChip action={state} />;
  const go = () => {
    setBusy(true);
    trackAction(payload)
      .then((a) => setState({ id: a.id, status: a.status, outcome: a.outcome }))
      .catch((e: Error) => {
        setErr(e.message);
        setBusy(false);
      });
  };
  return (
    <span className="inline-flex items-center gap-1">
      <button
        type="button"
        onClick={go}
        disabled={busy}
        className="rounded-full border border-violet-a/50 px-2 py-0.5 text-[11px] text-violet-a hover:bg-violet-a/10 disabled:opacity-50"
        title="Track this action and have Beacon retest it after you implement it"
      >
        {busy ? "Tracking..." : `${label} ›`}
      </button>
      {err && <span className="text-[11px] text-rose-300">{err}</span>}
    </span>
  );
}

function ImplementForm({ action, onDone }: { action: TrackedAction; onDone: () => void }) {
  const today = new Date().toISOString().slice(0, 10);
  const [day, setDay] = useState(today);
  const [page, setPage] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const logsChange = action.kind === "content_gap" || action.kind === "topic" || action.kind === "fact";
  const save = () => {
    setBusy(true);
    updateTrackedAction(action.id, { status: "implemented", implemented_on: day, page_url: page || undefined })
      .then(onDone)
      .catch((e: Error) => {
        setErr(e.message);
        setBusy(false);
      });
  };
  return (
    <div className="mt-2 flex flex-wrap items-end gap-2 rounded-lg border border-line bg-surface-raised p-2 text-xs">
      <label className="flex flex-col gap-0.5">
        <span className="text-muted">Implemented on</span>
        <input id={`impl-day-${action.id}`} type="date" max={today} value={day} onChange={(e) => setDay(e.target.value)} className="rounded-md border border-line bg-surface px-2 py-1" />
      </label>
      {logsChange && (
        <label className="flex min-w-[14rem] flex-1 flex-col gap-0.5">
          <span className="text-muted">Page you changed (optional, logs it for Content Impact)</span>
          <input id={`impl-page-${action.id}`} value={page} onChange={(e) => setPage(e.target.value)} placeholder="https://" className="rounded-md border border-line bg-surface px-2 py-1" />
        </label>
      )}
      <button type="button" onClick={save} disabled={busy} className="rounded-md bg-violet-a px-3 py-1.5 font-medium text-background disabled:opacity-50">
        {busy ? "Saving..." : action.automatic_retest ? "Mark implemented" : "Mark done"}
      </button>
      {err && <span className="text-rose-300">{err}</span>}
    </div>
  );
}

function Row({ action, onChange }: { action: TrackedAction; onChange: () => void }) {
  const [implementing, setImplementing] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const move = (status: ActionStatus) => updateTrackedAction(action.id, { status }).then(onChange).catch((e: Error) => setErr(e.message));
  const retestNow = () => retestTrackedAction(action.id).then(onChange).catch((e: Error) => setErr(e.message));
  const chip = action.outcome ? OUTCOME_TEXT[action.outcome] : STATUS_TEXT[action.status];
  return (
    <li className="rounded-xl border border-line/60 px-3 py-2.5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-sm font-medium">{action.title}</span>
        <span className={`rounded-full px-2 py-0.5 text-[11px] ${chip.cls}`}>{chip.text}</span>
      </div>
      <p className="text-[11px] text-muted">
        {action.source_label ?? action.source ?? "Tracked"}
        {action.owner && ` · ${action.owner}`}
        {action.implemented_on && ` · implemented ${fmtDate(action.implemented_on)}`}
        {action.status === "implemented" && action.retest_after && ` · retest on or after ${fmtDate(action.retest_after)}`}
        {action.retested_at && ` · retested ${fmtDate(action.retested_at)}`}
      </p>
      {action.result?.sentence && <p className="mt-1 text-sm">{action.result.sentence}</p>}
      {!action.result?.sentence && action.reason && <p className="mt-1 line-clamp-2 text-xs text-muted">{action.reason}</p>}
      <p className="mt-1 text-[11px] text-muted">{action.retest_rule}</p>
      <div className="mt-2 flex flex-wrap gap-2 text-xs">
        {(action.status === "open" || action.status === "dismissed") && (
          <button type="button" onClick={() => move(action.status === "dismissed" ? "open" : "in_progress")} className="rounded-md border border-line px-2 py-1 hover:bg-surface-raised">
            {action.status === "dismissed" ? "Reopen" : "Start"}
          </button>
        )}
        {(action.status === "open" || action.status === "in_progress") && (
          <>
            <button type="button" onClick={() => setImplementing((v) => !v)} className="rounded-md border border-violet-a/50 px-2 py-1 text-violet-a hover:bg-violet-a/10">
              {action.automatic_retest ? "Mark implemented" : "Mark done"}
            </button>
            <button type="button" onClick={() => move("dismissed")} className="rounded-md border border-line px-2 py-1 text-muted hover:bg-surface-raised">
              Dismiss
            </button>
          </>
        )}
        {action.status === "implemented" && (
          <button type="button" onClick={retestNow} className="rounded-md border border-line px-2 py-1 hover:bg-surface-raised">
            Retest now
          </button>
        )}
        {(action.status === "implemented" || action.status === "retested" || action.status === "done") && (
          <button type="button" onClick={() => move("in_progress")} className="rounded-md border border-line px-2 py-1 text-muted hover:bg-surface-raised">
            Reopen
          </button>
        )}
      </div>
      {implementing && (
        <ImplementForm
          action={action}
          onDone={() => {
            setImplementing(false);
            onChange();
          }}
        />
      )}
      {err && <p className="mt-1 text-xs text-rose-300">{err}</p>}
    </li>
  );
}

export function ActionTrackerPanel({ propertyId }: { propertyId: number }) {
  const [version, setVersion] = useState(0);
  const [showClosed, setShowClosed] = useState(false);
  const { data, error, loading, retry } = useLoad(() => fetchTrackedActions(propertyId), [propertyId, version]);
  const closed = (a: TrackedAction) => a.status === "dismissed" || a.status === "done" || a.status === "retested";
  const rows = data ? data.actions.filter((a) => showClosed || !closed(a)) : [];
  const closedCount = data ? data.actions.filter(closed).length : 0;
  return (
    <Panel
      title="Tracked actions"
      subtitle="What your team is working on. Once an action is marked implemented, Beacon waits a set number of days and re-measures the evidence it came from."
      actions={
        closedCount > 0 ? (
          <button type="button" onClick={() => setShowClosed((v) => !v)} className="text-xs text-violet-a hover:underline">
            {showClosed ? "Hide finished" : `Show finished (${closedCount})`}
          </button>
        ) : undefined
      }
    >
      <LoadState
        loading={loading && !data}
        error={error}
        retry={retry}
        empty={{
          when: data !== null && data.actions.length === 0,
          title: "Nothing tracked yet",
          body: "Press Track on an action in This week, the Opportunities list, Areas of concern or Property truth.",
        }}
      >
        {data && data.actions.length > 0 && (
          <>
            <ul className="space-y-2">
              {rows.map((a) => (
                <Row key={a.id} action={a} onChange={() => setVersion((v) => v + 1)} />
              ))}
            </ul>
            {rows.length === 0 && <p className="text-sm text-muted">Everything tracked is finished. Show finished to see the retest results.</p>}
            <p className="mt-3 text-xs text-muted">{data.note}</p>
          </>
        )}
      </LoadState>
    </Panel>
  );
}
