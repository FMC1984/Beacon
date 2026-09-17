"use client";

/** Truth layer: each fact Beacon holds about the property, against every
 * place that fact can be stated (your site, the listing pages AI cites, the
 * AI answers), with who vouches for the recorded value and when.
 *
 * Cell states are the same deterministic check in every column. A source
 * Beacon could not read is "unread" or "unreachable", never silent. Rent is
 * volatile and is never graded as a conflict. */

import { useState } from "react";
import { fmtDate } from "@/lib/format";
import { fetchTruth, saveFactProvenance, type TruthCell, type TruthFact } from "@/lib/observatory";
import { LoadState, Panel, useLoad } from "./ui";

const CELL: Record<TruthCell["state"], { text: string; cls: string }> = {
  agrees: { text: "Agrees", cls: "bg-emerald-500/15 text-emerald-300" },
  conflicts: { text: "Conflicts", cls: "bg-rose-500/15 text-rose-300" },
  mentions: { text: "Mentions", cls: "bg-surface-raised text-foreground/80" },
  not_stated: { text: "Not stated", cls: "text-muted" },
  unread: { text: "Unread", cls: "text-muted" },
  unreachable: { text: "Unreachable", cls: "bg-amber-500/15 text-amber-300" },
  not_listed: { text: "Not listed", cls: "bg-amber-500/15 text-amber-300" },
  volatile: { text: "Volatile", cls: "bg-cyan-500/15 text-cyan-300" },
};

const PROV: Record<string, { text: string; cls: string }> = {
  verified: { text: "Verified", cls: "text-emerald-300" },
  stale: { text: "Needs re-verifying", cls: "text-amber-300" },
  unverified: { text: "Never verified", cls: "text-muted" },
};

function Cell({ cell }: { cell: TruthCell }) {
  const s = CELL[cell.state];
  const title = [cell.values?.join("; "), cell.evidence].filter(Boolean).join(" | ") || undefined;
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-[11px] ${s.cls}`} title={title}>
      {s.text}
      {cell.state === "conflicts" && cell.conflict ? ` (${cell.conflict})` : ""}
      {cell.state === "agrees" && cell.agree ? ` (${cell.agree})` : ""}
    </span>
  );
}

function VerifyEditor({ propertyId, fact, onSaved, onCancel }: { propertyId: number; fact: TruthFact; onSaved: () => void; onCancel: () => void }) {
  const [source, setSource] = useState(fact.provenance.source_of_truth ?? "");
  const [by, setBy] = useState(fact.provenance.verified_by ?? "");
  const [freshness, setFreshness] = useState(fact.provenance.freshness);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const save = () => {
    setBusy(true);
    saveFactProvenance(propertyId, fact.fact_key, { verified: true, source_of_truth: source, verified_by: by, freshness })
      .then(onSaved)
      .catch((e: Error) => {
        setErr(e.message);
        setBusy(false);
      });
  };
  return (
    <div className="mt-2 space-y-2 rounded-lg border border-line bg-surface-raised p-3 text-xs">
      <p className="text-muted">
        Confirm that <span className="text-foreground">{fact.label}: {fact.recorded_value}</span> is correct today, and say how you know.
      </p>
      <input
        id={`truth-source-${fact.fact_key}`}
        value={source}
        onChange={(e) => setSource(e.target.value)}
        placeholder="Source of truth (for example: community manager, lease addendum)"
        className="w-full rounded-lg border border-line bg-surface px-2 py-1.5"
      />
      <div className="flex flex-wrap gap-2">
        <input
          id={`truth-by-${fact.fact_key}`}
          value={by}
          onChange={(e) => setBy(e.target.value)}
          placeholder="Verified by"
          className="min-w-0 flex-1 rounded-lg border border-line bg-surface px-2 py-1.5"
        />
        <select
          id={`truth-fresh-${fact.fact_key}`}
          value={freshness}
          onChange={(e) => setFreshness(e.target.value as TruthFact["provenance"]["freshness"])}
          className="rounded-lg border border-line bg-surface px-2 py-1.5"
          title="How quickly this fact goes stale"
        >
          <option value="stable">Stable (re-verify every 180 days)</option>
          <option value="seasonal">Seasonal (every 90 days)</option>
          <option value="volatile">Volatile (live feed needed, never graded)</option>
        </select>
      </div>
      {err && <p className="text-rose-300">{err}</p>}
      <div className="flex gap-2">
        <button type="button" onClick={save} disabled={busy} className="rounded-lg bg-violet-a px-3 py-1.5 font-medium text-background disabled:opacity-50">
          {busy ? "Saving..." : "Mark verified today"}
        </button>
        <button type="button" onClick={onCancel} className="rounded-lg border border-line px-3 py-1.5">Cancel</button>
      </div>
    </div>
  );
}

export function TruthPanel({ propertyId, days }: { propertyId: number; days: number }) {
  const [version, setVersion] = useState(0);
  const [editing, setEditing] = useState<string | null>(null);
  const { data, error, loading, retry } = useLoad(() => fetchTruth(propertyId, days), [propertyId, days, version]);
  return (
    <Panel
      title="Property truth"
      label="MEASURED"
      subtitle="Each fact you recorded, against your website, the listing pages AI cites and the AI answers. The same check runs in every column, so a conflict means the same thing everywhere."
    >
      <LoadState
        loading={loading && !data}
        error={error}
        retry={retry}
        empty={{
          when: data !== null && data.facts.length === 0,
          title: "No facts recorded yet",
          body: "Record pets, rent range and amenities on the property, and the property type on Property Context. Beacon compares sources only against facts you gave it.",
        }}
      >
        {data && data.facts.length > 0 && (
          <>
            <div className="mb-3 flex flex-wrap gap-2 text-xs">
              <span className="rounded-full bg-surface-raised px-2 py-0.5">{data.summary.facts} facts</span>
              <span className={`rounded-full px-2 py-0.5 ${data.summary.with_conflicts ? "bg-rose-500/15 text-rose-300" : "bg-surface-raised text-muted"}`}>
                {data.summary.with_conflicts} with a conflicting source
              </span>
              <span className="rounded-full bg-surface-raised px-2 py-0.5 text-muted">{data.summary.unverified} never verified</span>
              {data.summary.stale > 0 && <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-amber-300">{data.summary.stale} need re-verifying</span>}
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[820px] text-sm">
                <thead className="text-left text-xs text-muted">
                  <tr className="border-b border-line">
                    <th className="py-2 pr-3 font-normal">Fact and recorded truth</th>
                    {data.columns.map((c) => (
                      <th key={c.key} className="py-2 pr-3 font-normal">
                        {c.label}
                        {c.kind === "listing" && <span className="block text-[10px]">{c.citations} citations</span>}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.facts.map((f) => (
                    <tr key={f.fact_key} className="border-b border-line/60 align-top">
                      <td className="max-w-[18rem] py-2 pr-3">
                        <span className="font-medium">{f.label}:</span> {f.recorded_value}
                        <span className={`block text-[11px] ${PROV[f.provenance.status].cls}`}>
                          {PROV[f.provenance.status].text}
                          {f.provenance.verified_at && ` ${fmtDate(f.provenance.verified_at)}`}
                          {f.provenance.source_of_truth && ` · ${f.provenance.source_of_truth}`}
                          {" · "}
                          <button type="button" onClick={() => setEditing(editing === f.fact_key ? null : f.fact_key)} className="text-violet-a hover:underline">
                            {f.provenance.status === "verified" ? "update" : "verify"}
                          </button>
                        </span>
                        {f.cited_sources_with_same_value.map((o) => (
                          <span key={o.url} className="mt-1 block text-[11px] text-rose-300" title={o.evidence}>
                            A page the conflicting answers cited shows the same value: {o.url} ({o.value})
                          </span>
                        ))}
                        {editing === f.fact_key && (
                          <VerifyEditor
                            propertyId={propertyId}
                            fact={f}
                            onCancel={() => setEditing(null)}
                            onSaved={() => {
                              setEditing(null);
                              setVersion((v) => v + 1);
                            }}
                          />
                        )}
                      </td>
                      {data.columns.map((c) => (
                        <td key={c.key} className="py-2 pr-3">
                          <Cell cell={f.cells[c.key]} />
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {data.notes.map((n) => (
              <p key={n} className="mt-3 text-xs text-amber-300">{n}</p>
            ))}
            <p className="mt-3 text-xs text-muted">{data.note}</p>
          </>
        )}
      </LoadState>
    </Panel>
  );
}
