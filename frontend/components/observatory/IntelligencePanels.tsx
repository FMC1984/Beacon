"use client";

/** Slice 5 panels: AI-discovered competitor candidates, AI fact claims,
 * alerts, and monitoring usage with a scheduler plan preview. */

import { useState } from "react";
import { fmtDate } from "@/lib/format";
import {
  asUtc,
  decideCandidate,
  dismissClaim,
  fetchAlerts,
  fetchCandidates,
  fetchClaims,
  fetchCosts,
  previewPlan,
  setAlertStatus,
  type Alert,
  type ClaimStatus,
  type Plan,
} from "@/lib/observatory";
import { DataLabelBadge, LoadState, Panel, useLoad } from "./ui";

const SEVERITY: Record<string, string> = {
  high: "border-pink-a/40 bg-pink-a/10 text-pink-a",
  medium: "border-amber-a/40 bg-amber-a/10 text-amber-a",
  low: "border-line bg-surface-raised text-muted",
};

export function CandidatesPanel({ propertyId }: { propertyId: number }) {
  const [nonce, setNonce] = useState(0);
  const [domains, setDomains] = useState<Record<number, string>>({});
  const [error, setError] = useState<string | null>(null);
  const { data, loading, error: loadError, retry } = useLoad(() => fetchCandidates(propertyId), [propertyId, nonce]);

  async function act(id: number, decision: "confirmed" | "ignored") {
    setError(null);
    try {
      await decideCandidate(id, propertyId, decision, domains[id]);
      setNonce((n) => n + 1);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <Panel
      title="AI-discovered competitors"
      label="MODELED"
      subtitle={data?.note ?? "Names AI answers in this market keep mentioning that you do not track yet."}
    >
      {error && <p className="mb-2 text-xs text-pink-a">{error}</p>}
      <LoadState
        loading={loading && !data}
        error={loadError}
        retry={retry}
        empty={{
          when: data !== null && data.candidates.length === 0,
          title: "No new names to review",
          body: `A name appears here once at least ${data?.minimum_responses ?? 2} monitored answers in this market mention it.`,
        }}
      >
        <ul className="divide-y divide-line">
          {data?.candidates.map((c) => (
            <li key={c.id} className="flex flex-wrap items-start justify-between gap-3 py-3">
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium">{c.name}</p>
                <p className="text-xs text-muted">
                  Named in {c.responses} answers · confidence {Math.round(c.confidence * 100)}%
                  {c.last_seen ? ` · last seen ${fmtDate(asUtc(c.last_seen))}` : ""}
                </p>
                {c.sample_context && <p className="mt-1 line-clamp-2 text-xs text-muted">&ldquo;{c.sample_context}&rdquo;</p>}
              </div>
              <div className="flex items-center gap-2">
                <input
                  value={domains[c.id] ?? ""}
                  onChange={(e) => setDomains((d) => ({ ...d, [c.id]: e.target.value }))}
                  placeholder="Website (optional)"
                  aria-label={`Website for ${c.name}`}
                  className="w-40 rounded-lg border border-line bg-surface-raised px-2.5 py-1 text-xs"
                />
                <button onClick={() => act(c.id, "confirmed")} className="rounded-lg bg-violet-a px-2.5 py-1 text-xs font-medium text-background">
                  Track
                </button>
                <button onClick={() => act(c.id, "ignored")} className="rounded-lg border border-line px-2.5 py-1 text-xs hover:bg-surface-raised">
                  Ignore
                </button>
              </div>
            </li>
          ))}
        </ul>
      </LoadState>
    </Panel>
  );
}

const CLAIM_META: Record<ClaimStatus, { label: string; cls: string }> = {
  conflict_detected: { label: "Conflict detected", cls: "border-pink-a/40 bg-pink-a/10 text-pink-a" },
  unable_to_verify: { label: "Unable to verify", cls: "border-line bg-surface-raised text-muted" },
  likely_accurate: { label: "Likely accurate", cls: "border-cyan-a/40 bg-cyan-a/10 text-cyan-a" },
  confirmed: { label: "Confirmed", cls: "border-emerald-a/40 bg-emerald-a/10 text-emerald-a" },
};

export function ClaimsPanel({ propertyId }: { propertyId: number }) {
  const [nonce, setNonce] = useState(0);
  const [open, setOpen] = useState<number | null>(null);
  const { data, loading, error, retry } = useLoad(() => fetchClaims(propertyId), [propertyId, nonce]);

  return (
    <Panel
      title="What AI answers claim about the property"
      label="OBSERVED"
      subtitle="Claims are taken from sentences that name the property and checked against Property Context and the property's recorded attributes."
    >
      <LoadState
        loading={loading && !data}
        error={error}
        retry={retry}
        empty={{
          when: data !== null && data.claims.length === 0,
          title: "No claims recorded yet",
          body: "Claims appear when monitored answers mention the property with a checkable fact such as pets, amenities, rent or property type.",
        }}
      >
        {data && (
          <>
            <div className="mb-3 flex flex-wrap gap-2">
              {(Object.keys(CLAIM_META) as ClaimStatus[]).map((s) => (
                <span key={s} className={`rounded-full border px-2.5 py-0.5 text-[11px] font-medium ${CLAIM_META[s].cls}`}>
                  {CLAIM_META[s].label}: {data.counts[s] ?? 0}
                </span>
              ))}
            </div>
            <ul className="divide-y divide-line rounded-xl border border-line">
              {data.claims.map((c) => (
                <li key={c.id} className="px-4 py-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <button onClick={() => setOpen(open === c.id ? null : c.id)} className="min-w-0 flex-1 text-left" aria-expanded={open === c.id}>
                      <span className={`mr-2 rounded-full border px-2 py-0.5 text-[10px] font-medium ${CLAIM_META[c.verification_status].cls}`}>
                        {CLAIM_META[c.verification_status].label}
                      </span>
                      <span className="text-sm font-medium">{c.claim_value}</span>
                      <span className="ml-2 text-xs text-muted">
                        {c.claim_type.replace(/_/g, " ")} · seen {c.occurrence_count}x on {c.platforms.join(", ")}
                      </span>
                    </button>
                    <button
                      onClick={() => dismissClaim(c.id).then(() => setNonce((n) => n + 1))}
                      className="rounded-lg border border-line px-2 py-0.5 text-xs text-muted hover:text-foreground"
                    >
                      Dismiss
                    </button>
                  </div>
                  <p className="mt-1 text-xs text-muted">{c.evidence}</p>
                  {open === c.id && (
                    <blockquote className="mt-2 rounded-lg bg-surface-raised p-2.5 text-xs leading-relaxed">
                      &ldquo;{c.claim_text}&rdquo;
                      <span className="mt-1 block text-muted">
                        Responses: {c.response_ids.join(", ")} · first seen {c.first_seen ? fmtDate(asUtc(c.first_seen)) : "n/a"}
                      </span>
                    </blockquote>
                  )}
                </li>
              ))}
            </ul>
          </>
        )}
      </LoadState>
    </Panel>
  );
}

export function AlertsPanel({ propertyId }: { propertyId: number }) {
  const [nonce, setNonce] = useState(0);
  const { data, error, retry } = useLoad(() => fetchAlerts(propertyId), [propertyId, nonce]);
  if (error) return null; // alerts are an enhancement; the page still works without them
  const alerts = data?.alerts ?? [];
  if (alerts.length === 0) return null;

  const update = (a: Alert, status: Alert["status"]) => setAlertStatus(a.id, status).then(() => setNonce((n) => n + 1)).catch(retry);
  return (
    <Panel title={`Alerts (${alerts.length})`} subtitle="Changes worth a look. They describe what changed in monitored answers, not why.">
      <ul className="space-y-2">
        {alerts.map((a) => (
          <li key={a.id} className={`rounded-xl border p-3 ${SEVERITY[a.severity] ?? SEVERITY.low}`}>
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-foreground">{a.title}</p>
                <p className="mt-0.5 text-xs text-muted">{a.detail}</p>
                <p className="mt-1 flex items-center gap-2 text-[11px] text-muted">
                  <DataLabelBadge label={a.data_label} />
                  {a.created_at ? fmtDate(asUtc(a.created_at)) : ""}
                  {a.escalated && " · monitoring increased for 3 weeks"}
                </p>
              </div>
              <div className="flex gap-1.5">
                <button onClick={() => update(a, "acknowledged")} className="rounded-lg border border-line bg-surface px-2 py-0.5 text-xs text-foreground">
                  Acknowledge
                </button>
                <button onClick={() => update(a, "resolved")} className="rounded-lg border border-line bg-surface px-2 py-0.5 text-xs text-foreground">
                  Resolve
                </button>
              </div>
            </div>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

export function UsagePanel({ days, propertyId }: { days: number; propertyId: number | null }) {
  const { data, loading, error, retry } = useLoad(() => fetchCosts(days, propertyId), [days, propertyId]);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [planError, setPlanError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function preview() {
    setBusy(true);
    setPlanError(null);
    try {
      setPlan(await previewPlan());
    } catch (e) {
      setPlanError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const cost = data?.total.cost;
  return (
    <Panel
      title="Monitoring usage"
      subtitle="Beacon's own API calls across this property's organization, including failed and discarded runs because they still spend."
      actions={
        <button onClick={preview} disabled={busy} className="rounded-xl border border-line px-3 py-1.5 text-sm hover:bg-surface-raised disabled:opacity-50">
          {busy ? "Planning..." : "Preview next scheduled plan"}
        </button>
      }
    >
      <LoadState loading={loading && !data} error={error} retry={retry}>
        {data && cost && (
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <div>
              <p className="text-xs text-muted">Runs ({data.window.days}d)</p>
              <p className="text-2xl font-semibold">{data.total.runs}</p>
              <p className="text-[11px] text-muted">
                {Object.entries(data.total.by_status).map(([k, v]) => `${v} ${k}`).join(" · ") || "none"}
              </p>
            </div>
            <div>
              <p className="flex items-center gap-1.5 text-xs text-muted">
                Tokens <DataLabelBadge label="OBSERVED" />
              </p>
              <p className="text-2xl font-semibold">{(data.total.tokens.input + data.total.tokens.output).toLocaleString()}</p>
              <p className="text-[11px] text-muted">{data.total.search_operations} web searches</p>
            </div>
            <div>
              <p className="flex items-center gap-1.5 text-xs text-muted">
                Estimated cost <DataLabelBadge label={cost.label} />
              </p>
              <p className="text-2xl font-semibold">{cost.estimated_usd === null ? "n/a" : `$${cost.estimated_usd.toFixed(2)}`}</p>
              {cost.note && <p className="text-[11px] text-muted">{cost.note}</p>}
            </div>
            <div>
              <p className="text-xs text-muted">Monthly budget ({data.budget.period})</p>
              <p className="text-2xl font-semibold">
                {data.budget.spent_runs}
                <span className="text-sm font-normal text-muted"> / {data.budget.allowance_runs} runs</span>
              </p>
              <p className="text-[11px] text-muted">{data.observations_produced} property scores produced</p>
            </div>
          </div>
        )}
      </LoadState>
      {planError && <p className="mt-3 text-xs text-pink-a">{planError}</p>}
      {plan && (
        <div className="mt-4 rounded-xl border border-line bg-surface-raised p-3 text-xs">
          <p className="font-medium">
            Dry run: {plan.selected} of {plan.due} due prompt{plan.due === 1 ? "" : "s"} would run
            {plan.skipped_budget ? `, ${plan.skipped_budget} held back by the budget` : ""}. Nothing was spent.
          </p>
          <ul className="mt-2 max-h-56 space-y-1 overflow-auto">
            {plan.decisions.slice(0, 25).map((d) => (
              <li key={`${d.schedule_id}-${d.platform}`} className="flex justify-between gap-2 text-muted">
                <span className="truncate">
                  Prompt {d.prompt_id} on {d.platform} ({d.tier.replace(/_/g, " ")}): {d.reason}
                </span>
                <span className="shrink-0">priority {Math.round(d.priority_score)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Panel>
  );
}
