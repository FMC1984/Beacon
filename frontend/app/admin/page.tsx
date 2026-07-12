"use client";

import { useCallback, useEffect, useState } from "react";
import { API_BASE } from "@/lib/api";
import { fmtDateTime } from "@/lib/format";

type Status = {
  version: string;
  phase: string;
  test_count: number;
  demo_mode: boolean;
  openai_configured: boolean;
  openai_quota: string;
  embedding_provider: string;
  llm_provider: string;
  chroma: { status: string; indexed_chunks: number | null; embedder: string | null };
  registry_chunks: number;
  last_index_run: {
    ran_at: string;
    chunks_total: number;
    embedded: number;
    embedder: string;
  } | null;
  last_nora_message: { at: string; role: string; preview: string } | null;
};

type SyncJob = {
  id: number;
  property_id: number | null;
  source: string | null;
  reason: string;
  status: string;
  chunks_embedded: number;
  chunks_total: number;
  created_at: string;
  error_message: string | null;
};

type SyncStatus = {
  last_sync: string | null;
  chunks_indexed: number | null;
  chunks_updated_today: number;
  queued_jobs: number;
  failed_jobs: number;
  embedding_provider: string;
  llm_provider: string;
  last_rebuild: string | null;
  recent_jobs: SyncJob[];
};

type ReindexResult = {
  status: string;
  chunks_total?: number;
  embedded?: number;
  unchanged?: number;
  removed?: number;
  error?: string;
};

type HealthCheck = { name: string; status: "ok" | "warn" | "fail"; detail: string };
type Health = { overall: "ok" | "warn" | "fail"; checked_at: string; checks: HealthCheck[] };

const DOT: Record<string, string> = {
  ok: "bg-emerald-a",
  warn: "bg-amber-a",
  fail: "bg-pink-a",
};
const OVERALL_LABEL: Record<string, string> = {
  ok: "All systems healthy",
  warn: "Needs attention",
  fail: "Problem detected",
};

export default function AdminPage() {
  const [status, setStatus] = useState<Status | null>(null);
  const [sync, setSync] = useState<SyncStatus | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reindexing, setReindexing] = useState(false);
  const [reindexResult, setReindexResult] = useState<ReindexResult | null>(null);
  const [draining, setDraining] = useState(false);

  const load = useCallback(() => {
    fetch(`${API_BASE}/admin/status`)
      .then((r) => r.json())
      .then(setStatus)
      .catch(() => setError("Could not reach the Beacon API."));
    fetch(`${API_BASE}/admin/sync-status`)
      .then((r) => r.json())
      .then(setSync)
      .catch(() => {});
    fetch(`${API_BASE}/admin/healthcheck`)
      .then((r) => r.json())
      .then(setHealth)
      .catch(() => {});
  }, []);

  useEffect(load, [load]);

  async function processQueue() {
    setDraining(true);
    try {
      await fetch(`${API_BASE}/admin/process-queue`, { method: "POST" });
    } catch {
      /* surfaced via reload */
    } finally {
      setDraining(false);
      load();
    }
  }

  async function reindex() {
    setReindexing(true);
    setReindexResult(null);
    try {
      const res = await fetch(`${API_BASE}/admin/reindex`, { method: "POST" });
      setReindexResult(await res.json());
    } catch {
      setReindexResult({ status: "failed", error: "Could not reach the API." });
    } finally {
      setReindexing(false);
      load();
    }
  }

  const ok = (good: boolean) => (good ? "text-emerald-a" : "text-pink-a");

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Admin</h1>
        <p className="mt-1 text-sm text-muted">
          Internal health page for debugging. Single-user tool, no auth.
        </p>
      </div>

      {error && (
        <div className="rounded-2xl border border-pink-a/40 bg-pink-a/10 p-4 text-sm text-pink-a">
          {error}
        </div>
      )}

      {health && (
        <section className="rounded-2xl border border-line bg-surface p-5">
          <div className="mb-3 flex items-center gap-2.5">
            <span className={`inline-block h-2.5 w-2.5 rounded-full ${DOT[health.overall]}`} />
            <h2 className="text-sm font-medium">
              System health — {OVERALL_LABEL[health.overall]}
            </h2>
            <button
              onClick={load}
              className="ml-auto text-xs text-muted underline decoration-dotted hover:text-foreground"
            >
              Re-check
            </button>
          </div>
          <ul className="space-y-2">
            {health.checks.map((c) => (
              <li key={c.name} className="flex items-start gap-2.5 text-sm">
                <span className={`mt-1.5 inline-block h-2 w-2 shrink-0 rounded-full ${DOT[c.status]}`} />
                <span className="min-w-36 shrink-0 font-medium">{c.name}</span>
                <span className="text-muted">{c.detail}</span>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-xs text-muted">
            Checked {fmtDateTime(health.checked_at)}.
          </p>
        </section>
      )}

      {status && (
        <div className="space-y-4">
          <section className="rounded-2xl border border-line bg-surface p-5 text-sm">
            <h2 className="mb-3 text-sm font-medium text-muted">Application</h2>
            <Row label="Version" value={status.version} />
            <Row label="Phase" value={status.phase} />
            <Row label="Tests at last checkpoint" value={String(status.test_count)} />
            <Row
              label="Mode"
              value={status.demo_mode ? "DEMO (deterministic, no OpenAI calls)" : "Live"}
              className={status.demo_mode ? "text-amber-a" : "text-emerald-a"}
            />
          </section>

          <section className="rounded-2xl border border-line bg-surface p-5 text-sm">
            <h2 className="mb-3 text-sm font-medium text-muted">OpenAI</h2>
            <Row
              label="Key configured"
              value={status.openai_configured ? "yes" : "no"}
              className={ok(status.openai_configured)}
            />
            <Row
              label="Quota check"
              value={status.openai_quota}
              className={
                status.openai_quota === "ok"
                  ? "text-emerald-a"
                  : status.openai_quota.startsWith("skipped")
                    ? "text-muted"
                    : "text-pink-a"
              }
            />
          </section>

          <section className="rounded-2xl border border-line bg-surface p-5 text-sm">
            <h2 className="mb-3 text-sm font-medium text-muted">Providers</h2>
            <Row label="Embedding provider" value={status.embedding_provider} />
            <Row label="LLM provider" value={status.llm_provider} />
          </section>

          {sync && (
            <section className="rounded-2xl border border-line bg-surface p-5 text-sm">
              <h2 className="mb-3 text-sm font-medium text-muted">
                Knowledge Base synchronization
              </h2>
              <Row
                label="Last sync"
                value={sync.last_sync ? fmtDateTime(sync.last_sync) : "never"}
              />
              <Row
                label="Chunks indexed"
                value={String(sync.chunks_indexed ?? "unknown")}
              />
              <Row
                label="Chunks updated today"
                value={String(sync.chunks_updated_today)}
              />
              <Row
                label="Queued jobs"
                value={String(sync.queued_jobs)}
                className={sync.queued_jobs > 0 ? "text-amber-a" : "text-muted"}
              />
              <Row
                label="Failed jobs"
                value={String(sync.failed_jobs)}
                className={sync.failed_jobs > 0 ? "text-pink-a" : "text-muted"}
              />
              <Row
                label="Last full rebuild"
                value={sync.last_rebuild ? fmtDateTime(sync.last_rebuild) : "never"}
              />
              <div className="mt-4">
                <button
                  onClick={processQueue}
                  disabled={draining}
                  className="rounded-xl border border-line px-4 py-2 text-sm font-medium disabled:opacity-50"
                >
                  {draining ? "Processing…" : "Process Queue"}
                </button>
              </div>
              {sync.recent_jobs.length > 0 && (
                <div className="mt-4 space-y-1.5">
                  <p className="text-xs text-muted">Recent jobs</p>
                  {sync.recent_jobs.map((j) => (
                    <div
                      key={j.id}
                      className="flex items-center justify-between gap-4 border-b border-line/40 py-1 text-xs last:border-0"
                    >
                      <span className="text-muted">
                        #{j.id} {j.reason}
                        {j.property_id ? ` · property ${j.property_id}` : ""}
                      </span>
                      <span
                        className={
                          j.status === "completed"
                            ? "text-emerald-a"
                            : j.status === "failed"
                              ? "text-pink-a"
                              : "text-amber-a"
                        }
                      >
                        {j.status}
                        {j.status === "completed" &&
                          ` (${j.chunks_embedded}/${j.chunks_total})`}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </section>
          )}

          <section className="rounded-2xl border border-line bg-surface p-5 text-sm">
            <h2 className="mb-3 text-sm font-medium text-muted">RAG index</h2>
            <Row
              label="ChromaDB"
              value={status.chroma.status}
              className={ok(status.chroma.status === "ok")}
            />
            <Row
              label="Indexed chunks"
              value={String(status.chroma.indexed_chunks ?? "unknown")}
            />
            <Row label="Registry rows" value={String(status.registry_chunks)} />
            <Row label="Index embedder" value={status.chroma.embedder ?? "none"} />
            <Row
              label="Last index run"
              value={
                status.last_index_run
                  ? `${fmtDateTime(status.last_index_run.ran_at)} (${status.last_index_run.chunks_total} chunks, ${status.last_index_run.embedded} embedded)`
                  : "never"
              }
            />
            <div className="mt-4 flex items-center gap-3">
              <button
                onClick={reindex}
                disabled={reindexing}
                className="rounded-xl bg-violet-a px-4 py-2 text-sm font-medium text-background disabled:opacity-50"
              >
                {reindexing ? "Rebuilding…" : "Rebuild RAG Index"}
              </button>
              {reindexResult && (
                <span
                  className={
                    reindexResult.status === "ok" ? "text-emerald-a" : "text-pink-a"
                  }
                >
                  {reindexResult.status === "ok"
                    ? `Done: ${reindexResult.chunks_total} chunks (${reindexResult.embedded} embedded, ${reindexResult.unchanged} unchanged, ${reindexResult.removed} removed)`
                    : `Failed: ${reindexResult.error}`}
                </span>
              )}
            </div>
          </section>

          <section className="rounded-2xl border border-line bg-surface p-5 text-sm">
            <h2 className="mb-3 text-sm font-medium text-muted">Nora</h2>
            <Row
              label="Last message"
              value={
                status.last_nora_message
                  ? `${fmtDateTime(status.last_nora_message.at)} (${status.last_nora_message.role}): ${status.last_nora_message.preview}`
                  : "none yet"
              }
            />
          </section>
        </div>
      )}
    </div>
  );
}

function Row({
  label,
  value,
  className = "",
}: {
  label: string;
  value: string;
  className?: string;
}) {
  return (
    <div className="flex justify-between gap-6 border-b border-line/50 py-1.5 last:border-0">
      <span className="shrink-0 text-muted">{label}</span>
      <span className={`text-right ${className}`}>{value}</span>
    </div>
  );
}
