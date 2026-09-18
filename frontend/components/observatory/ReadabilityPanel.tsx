"use client";

/** Can AI read your site? The latest raw-HTML check of the property's own
 * website: which renter facts a plain crawler finds in the initial HTML,
 * which AI crawlers robots.txt admits, and the structured data declared.
 * No JavaScript is run, and the copy never claims a fact is "hidden";
 * it says the fact is not in the raw HTML. */

import { useState } from "react";
import { fmtDateTime } from "@/lib/format";
import { fetchReadability, requestReadabilityCheck, type ReadabilityReport } from "@/lib/observatory";
import { LoadState, Panel, useLoad } from "./ui";

const SEV: Record<string, string> = {
  critical: "bg-rose-500/15 text-rose-300",
  high: "bg-amber-500/15 text-amber-300",
  medium: "bg-surface-raised text-muted",
};

const AGENT: Record<string, string> = {
  allowed: "bg-emerald-500/15 text-emerald-300",
  disallowed: "bg-rose-500/15 text-rose-300",
  unknown: "bg-surface-raised text-muted",
};

function Body({ data }: { data: Extract<ReadabilityReport, { checked: true }> }) {
  const cats = Object.entries(data.categories_spec);
  return (
    <div className="space-y-4">
      {data.status === "error" && (
        <p className="rounded-xl border border-amber-a/40 bg-amber-a/10 px-3 py-2 text-sm text-amber-a">{data.error}</p>
      )}
      {data.status === "ok" && (
        <>
          <div className="flex flex-wrap gap-2 text-xs">
            <span className="rounded-full bg-surface-raised px-2 py-0.5">
              {data.summary.present} of {data.summary.total} fact types in raw HTML
            </span>
            {data.summary.critical > 0 && <span className={`rounded-full px-2 py-0.5 ${SEV.critical}`}>{data.summary.critical} critical</span>}
            {data.summary.high > 0 && <span className={`rounded-full px-2 py-0.5 ${SEV.high}`}>{data.summary.high} high</span>}
            <span className="rounded-full bg-surface-raised px-2 py-0.5 text-muted">{data.pages.length} page{data.pages.length === 1 ? "" : "s"} checked</span>
          </div>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <div>
              <h3 className="mb-1 text-xs font-medium uppercase tracking-wider text-muted">In the raw HTML</h3>
              <ul className="space-y-1 text-sm">
                {cats.map(([key, spec]) => {
                  const c = data.categories[key];
                  return (
                    <li key={key} className="flex items-start gap-2" title={c?.evidence ?? undefined}>
                      <span className={`mt-0.5 inline-block h-2.5 w-2.5 shrink-0 rounded-full ${c?.present ? "bg-emerald-400" : "bg-rose-400"}`} />
                      <span>
                        {spec.label}
                        <span className="ml-2 text-xs text-muted">{c?.present ? "found" : `not found (${spec.severity})`}</span>
                      </span>
                    </li>
                  );
                })}
              </ul>
            </div>
            <div>
              <h3 className="mb-1 text-xs font-medium uppercase tracking-wider text-muted">AI crawlers in robots.txt</h3>
              {data.robots.reachable === false ? (
                <p className="text-xs text-muted">robots.txt could not be read.</p>
              ) : (
                <ul className="flex flex-wrap gap-1.5">
                  {data.agents.map((a) => (
                    <li key={a} className={`rounded-full px-2 py-0.5 text-[11px] ${AGENT[data.robots.agents?.[a] ?? "unknown"]}`}>
                      {a}: {data.robots.agents?.[a] ?? "unknown"}
                    </li>
                  ))}
                </ul>
              )}
              <h3 className="mb-1 mt-3 text-xs font-medium uppercase tracking-wider text-muted">Structured data declared</h3>
              <p className="text-xs text-muted">{data.structured_data.length ? data.structured_data.join(", ") : "None found (informational)"}</p>
            </div>
          </div>
        </>
      )}
      {data.findings.length > 0 && (
        <div>
          <h3 className="mb-1 text-xs font-medium uppercase tracking-wider text-muted">Findings</h3>
          <ul className="space-y-1.5">
            {data.findings.map((f) => (
              <li key={`${f.category}-${f.text}`} className="flex items-start gap-2 text-sm">
                <span className={`mt-0.5 shrink-0 rounded-full px-2 py-0.5 text-[11px] ${SEV[f.severity] ?? SEV.medium}`}>{f.severity}</span>
                <span>{f.text}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {data.status === "ok" && (
        <details className="text-xs text-muted">
          <summary className="cursor-pointer">Pages checked</summary>
          <ul className="mt-1 space-y-0.5">
            {data.pages.map((p) => (
              <li key={p.url}>
                {p.url} · {p.error ? p.error : `${p.chars ?? 0} chars of text, ${p.scripts} scripts`}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

export function ReadabilityPanel({ propertyId }: { propertyId: number }) {
  const [msg, setMsg] = useState<string | null>(null);
  const { data, error, loading, retry } = useLoad(() => fetchReadability(propertyId), [propertyId]);
  const queue = () => {
    setMsg("Queuing...");
    requestReadabilityCheck(propertyId)
      .then((r) => setMsg(r.created ? "Check queued. Results appear once the runner has fetched the pages." : "A check is already queued for today."))
      .catch((e: Error) => setMsg(e.message));
  };
  return (
    <Panel
      title="Can AI read your site?"
      label="MEASURED"
      subtitle="What a plain crawler receives from your own website, without running JavaScript: which renter facts are in the initial HTML, and which AI crawlers robots.txt admits."
      actions={
        <div className="flex items-center gap-2">
          {msg && <span className="text-xs text-muted">{msg}</span>}
          {data && data.checked && <span className="text-xs text-muted">Checked {fmtDateTime(data.checked_at)}{data.is_sample ? " (sample)" : ""}</span>}
          <button
            type="button"
            onClick={queue}
            disabled={!!data && data.checked && data.is_sample}
            className="rounded-xl border border-line px-3 py-1.5 text-xs hover:bg-surface-raised disabled:opacity-50"
            title={data && data.checked && data.is_sample ? "Sample sites are never fetched" : "Fetch the site again now"}
          >
            Run check
          </button>
        </div>
      }
    >
      <LoadState loading={loading && !data} error={error} retry={retry}>
        {data && (data.checked ? <Body data={data} /> : <p className="text-sm text-muted">{data.reason}</p>)}
      </LoadState>
      {data && <p className="mt-3 text-xs text-muted">{data.note}</p>}
    </Panel>
  );
}
