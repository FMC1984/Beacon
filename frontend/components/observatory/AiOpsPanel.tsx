"use client";

/** Admin AI Ops panel (Phase 19 slice 5): jobs queue, recent failures with
 * retry, runner heartbeat, run outcomes in the last 24 hours, budget,
 * rollup watermark and database size. */

import { useCallback, useEffect, useState } from "react";
import { API_BASE } from "@/lib/api";
import { fmtDateTime } from "@/lib/format";
import { asUtc } from "@/lib/observatory";

type AiOps = {
  jobs: { by_status: Record<string, number>; by_type: { job_type: string; status: string; count: number }[] };
  recent_failures: { id: number; job_type: string; status: string; attempts: number; error_class: string | null; last_error: string }[];
  runner_heartbeat: { last_tick?: string } | null;
  runs_last_24h: { by_status: Record<string, number>; errors: Record<string, number> };
  budget: { period: string; allowance_runs: number; spent_runs: number; remaining_runs: number };
  rollup_watermark: { observation_id: number; updated_at: string } | null;
  scheduler_enabled: boolean;
  database: { bytes: number | null; wal_bytes: number | null };
};

const mb = (b: number | null) => (b === null ? "n/a" : `${(b / 1024 / 1024).toFixed(1)} MB`);
const pairs = (o: Record<string, number>) => Object.entries(o).map(([k, v]) => `${v} ${k}`).join(" · ") || "none";

export function AiOpsPanel() {
  const [ops, setOps] = useState<AiOps | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const reload = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    let cancelled = false;
    fetch(`${API_BASE}/admin/ai-ops`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((d) => !cancelled && setOps(d))
      .catch(() => !cancelled && setError("Could not load AI Ops."));
    return () => {
      cancelled = true;
    };
  }, [nonce]);

  async function retry(id: number) {
    await fetch(`${API_BASE}/admin/jobs/${id}/retry`, { method: "POST" });
    reload();
  }

  return (
    <section className="rounded-2xl border border-line bg-surface p-5 text-sm">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-medium text-muted">AI Ops (Observatory)</h2>
        <button onClick={reload} className="rounded-lg border border-line px-2.5 py-1 text-xs hover:bg-surface-raised">
          Refresh
        </button>
      </div>
      {error && <p className="text-xs text-pink-a">{error}</p>}
      {ops && (
        <div className="space-y-1">
          <Line label="Jobs" value={pairs(ops.jobs.by_status)} />
          <Line
            label="Runner heartbeat"
            value={ops.runner_heartbeat?.last_tick ? fmtDateTime(asUtc(ops.runner_heartbeat.last_tick)) : "no heartbeat yet"}
          />
          <Line label="Runs, last 24h" value={pairs(ops.runs_last_24h.by_status)} />
          <Line label="Run errors, last 24h" value={pairs(ops.runs_last_24h.errors)} />
          <Line
            label={`Budget ${ops.budget.period}`}
            value={`${ops.budget.spent_runs} of ${ops.budget.allowance_runs} runs (${ops.budget.remaining_runs} left)`}
          />
          <Line label="Scheduler" value={ops.scheduler_enabled ? "enabled" : "off (BEACON_AI_SCHEDULER_ENABLED)"} />
          <Line
            label="Rollups through observation"
            value={ops.rollup_watermark ? `#${ops.rollup_watermark.observation_id}, ${fmtDateTime(asUtc(ops.rollup_watermark.updated_at))}` : "not run yet"}
          />
          <Line label="Database" value={`${mb(ops.database.bytes)} (WAL ${mb(ops.database.wal_bytes)})`} />
          {ops.recent_failures.length > 0 && (
            <div className="pt-3">
              <p className="mb-1 text-xs font-medium text-muted">Failed and dead jobs</p>
              <ul className="space-y-1.5">
                {ops.recent_failures.map((j) => (
                  <li key={j.id} className="flex items-start justify-between gap-3 rounded-lg bg-surface-raised p-2 text-xs">
                    <span className="min-w-0">
                      #{j.id} {j.job_type} · {j.status} after {j.attempts} attempt{j.attempts === 1 ? "" : "s"}
                      {j.error_class ? ` · ${j.error_class}` : ""}
                      {j.last_error && <span className="block truncate text-muted">{j.last_error}</span>}
                    </span>
                    <button onClick={() => retry(j.id)} className="shrink-0 rounded-md border border-line px-2 py-0.5">
                      Retry
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function Line({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-6 border-b border-line/50 py-1.5 last:border-0">
      <span className="shrink-0 text-muted">{label}</span>
      <span className="text-right">{value}</span>
    </div>
  );
}
