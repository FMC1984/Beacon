"use client";

/** "This week": the three highest-ranked actions from the Opportunity Engine
 * for this property, each with its source and first evidence line, so the
 * AI Visibility Overview answers "what do we do" without a second click.
 * The ranking is the engine's own (state, impact, corroboration, effort). */

import Link from "next/link";
import { fetchActions, type ActionItem } from "@/lib/observatory";
import { LoadState, Panel, useLoad } from "./ui";

const STATE_CLS: Record<string, string> = {
  Actionable: "bg-emerald-500/15 text-emerald-300",
  "Requires confirmation": "bg-amber-500/15 text-amber-300",
  Monitor: "bg-surface-raised text-muted",
};

function ActionRow({ action, rank }: { action: ActionItem; rank: number }) {
  const first = action.citations?.[0];
  return (
    <li className="flex gap-3 rounded-xl border border-line/60 px-3 py-2.5">
      <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-violet-a/15 text-xs font-medium text-violet-a">
        {rank}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
          <span className="text-sm font-medium">{action.title}</span>
          <span className={`rounded-full px-2 py-0.5 text-[11px] ${STATE_CLS[action.state] ?? STATE_CLS.Monitor}`}>{action.state}</span>
          <span className="text-[11px] text-muted">{action.source_label}</span>
          {action.impact && <span className="text-[11px] text-muted">Impact {action.impact.toLowerCase()}</span>}
        </div>
        {action.reason && <p className="mt-0.5 line-clamp-2 text-xs text-muted">{action.reason}</p>}
        {first?.evidence?.[0] && <p className="mt-0.5 text-[11px] text-cyan-300">Evidence: {first.evidence[0]}</p>}
        {action.gate_reason && <p className="mt-0.5 text-[11px] text-amber-300">{action.gate_reason}</p>}
      </div>
    </li>
  );
}

export function ThisWeekStrip({ propertyId }: { propertyId: number }) {
  const { data, error, loading, retry } = useLoad(() => fetchActions(propertyId), [propertyId]);
  const top = data?.opportunities.slice(0, 3) ?? [];
  return (
    <Panel
      title="This week"
      subtitle="The three actions Beacon ranks highest for this property, with the evidence behind each. Every module feeds this list; the Observatory adds listing gaps, fact conflicts and content gaps."
      actions={
        <Link href={`/opportunities?property_id=${propertyId}`} className="text-xs text-violet-a hover:underline">
          All actions{data ? ` (${data.opportunities.length})` : ""} ›
        </Link>
      }
    >
      <LoadState
        loading={loading && !data}
        error={error}
        retry={retry}
        empty={{ when: data !== null && top.length === 0, title: "Nothing to act on yet", body: "Actions appear once monitored answers, Property Context and first-party data give Beacon evidence to point at." }}
      >
        {top.length > 0 && (
          <ol className="space-y-2">
            {top.map((a, i) => (
              <ActionRow key={`${a.source}-${a.title}`} action={a} rank={i + 1} />
            ))}
          </ol>
        )}
      </LoadState>
    </Panel>
  );
}
