"use client";

import { useCallback, useEffect, useState } from "react";
import { useSession } from "@/components/SessionProvider";
import { ROLE_LABELS } from "@/lib/auth";
import { fetchBillingStatus, openPortal, PLAN_LABELS, startCheckout, syncQuantity, type BillingStatus } from "@/lib/billing";

const SOURCE_TEXT: Record<string, string> = {
  subscription: "Active subscription",
  override: "Enabled by CiteRoll",
  sample: "Sample organization",
  none: "No subscription yet",
};

export default function BillingPage() {
  const { org, role, isPlatformAdmin } = useSession();
  const canManage = isPlatformAdmin || role === "owner";
  const [status, setStatus] = useState<BillingStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [quantity, setQuantity] = useState<number>(1);
  // The checkout result arrives as a query parameter from Stripe's redirect.
  const [note, setNote] = useState<string | null>(() => {
    if (typeof window === "undefined") return null;
    const outcome = new URLSearchParams(window.location.search).get("checkout");
    if (outcome === "success") return "Thanks. Stripe is confirming the payment; this page updates as soon as the webhook lands.";
    if (outcome === "cancelled") return "Checkout was cancelled. Nothing was charged.";
    return null;
  });

  const load = useCallback(() => {
    fetchBillingStatus()
      .then((s) => {
        setStatus(s);
        if (s.entitlement) setQuantity(Math.max(1, s.entitlement.monitored || 1));
      })
      .catch((err) => setError((err as Error).message));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function go(kind: string, fn: () => Promise<{ url: string }>) {
    setBusy(kind);
    setError(null);
    try {
      const r = await fn();
      window.location.assign(r.url);
    } catch (err) {
      setError((err as Error).message);
      setBusy(null);
    }
  }

  async function sync() {
    setBusy("sync");
    setError(null);
    try {
      const r = await syncQuantity();
      setNote(r.note);
      load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  if (!org) {
    return (
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold">Billing</h1>
        <p className="text-sm text-muted">
          {isPlatformAdmin ? "Pick an organization in the sidebar to see its billing." : "Your account is not part of an organization yet."}
        </p>
      </div>
    );
  }

  const ent = status?.entitlement ?? null;

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold">Billing</h1>
        <p className="mt-1 text-sm text-muted">
          {org.name}. Priced per monitored community per month. You are {ROLE_LABELS[role].toLowerCase()} here.
        </p>
      </div>

      {note && <div className="rounded-xl border border-line bg-surface px-4 py-3 text-sm">{note}</div>}
      {error && <div className="rounded-xl border border-pink-a/40 bg-pink-a/10 px-4 py-3 text-sm text-pink-a">{error}</div>}

      <section className="rounded-2xl border border-line bg-surface p-5">
        <h2 className="text-base font-semibold">Current plan</h2>
        {!ent ? (
          <p className="mt-2 text-sm text-muted">Loading…</p>
        ) : (
          <div className="mt-3 grid grid-cols-1 gap-4 md:grid-cols-4">
            <Stat label="Status" value={SOURCE_TEXT[ent.source] ?? ent.source} sub={ent.status ?? undefined} />
            <Stat label="Plan" value={ent.plan ? PLAN_LABELS[ent.plan] : "None"} sub={ent.cancel_at_period_end ? "Cancels at period end" : undefined} />
            <Stat label="Communities paid for" value={String(ent.quantity)} sub={ent.current_period_end ? `Renews ${new Date(ent.current_period_end).toLocaleDateString()}` : undefined} />
            <Stat
              label="Communities monitored"
              value={String(ent.monitored)}
              sub={
                ent.source !== "subscription"
                  ? undefined
                  : ent.over_by > 0
                    ? `${ent.over_by} over the plan`
                    : ent.under_by > 0
                      ? `${ent.under_by} unused`
                      : "Matches the plan"
              }
              tone={ent.over_by > 0 ? "warn" : undefined}
            />
          </div>
        )}
        {ent?.override && (
          <p className="mt-3 text-xs text-muted">Monitoring is enabled for this organization by CiteRoll{ent.override_reason ? ` (${ent.override_reason})` : ""}. No card on file is needed.</p>
        )}
        {ent && !ent.active && (
          <p className="mt-3 text-sm text-amber-a">This organization is read-only until monitoring starts. Everything stays visible.</p>
        )}
      </section>

      {status && !status.configured && (
        <section className="rounded-2xl border border-line bg-surface p-5 text-sm text-muted">
          Online billing is not set up on this server yet. Invoices are handled by hand; contact CiteRoll to start or change a plan.
        </section>
      )}

      {status?.configured && canManage && (
        <section className="rounded-2xl border border-line bg-surface p-5">
          <h2 className="text-base font-semibold">{ent?.source === "subscription" ? "Change your plan" : "Start monitoring"}</h2>
          <p className="mt-1 text-xs text-muted">Checkout and the card portal are hosted by Stripe. CiteRoll never sees card details.</p>
          {ent?.source !== "subscription" ? (
            <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-3">
              <PlanCard
                title="Standard monitoring"
                lines={["Weekly market questions", "Monthly brand questions", "Alerts, tracked fixes, monthly briefing"]}
                action={status.prices.standard ? () => go("standard", () => startCheckout("standard", quantity)) : undefined}
                busy={busy === "standard"}
                quantity={quantity}
                setQuantity={setQuantity}
              />
              <PlanCard
                title="Advanced monitoring"
                lines={["Everything in Standard", "Weekly brand questions, repeated", "Watchlist after an alert"]}
                action={status.prices.advanced ? () => go("advanced", () => startCheckout("advanced", quantity)) : undefined}
                busy={busy === "advanced"}
                quantity={quantity}
                setQuantity={setQuantity}
              />
              <PlanCard
                title="AI Visibility Audit"
                lines={["One-time, about two weeks", "The report and a walkthrough", "Credited toward monitoring"]}
                action={status.prices.audit ? () => go("audit", () => startCheckout("audit")) : undefined}
                busy={busy === "audit"}
              />
            </div>
          ) : (
            <div className="mt-4 flex flex-wrap gap-3">
              <button type="button" disabled={busy !== null} onClick={() => go("portal", openPortal)}
                      className="rounded-xl bg-violet-a px-4 py-2 text-sm font-medium text-background disabled:opacity-50">
                Manage card, invoices and cancellation
              </button>
              {ent && ent.over_by > 0 && (
                <button type="button" disabled={busy !== null} onClick={sync}
                        className="rounded-xl border border-line px-4 py-2 text-sm hover:bg-surface-raised disabled:opacity-50">
                  Update plan to {ent.monitored} communities
                </button>
              )}
              {status.prices.audit && (
                <button type="button" disabled={busy !== null} onClick={() => go("audit", () => startCheckout("audit"))}
                        className="rounded-xl border border-line px-4 py-2 text-sm hover:bg-surface-raised disabled:opacity-50">
                  Buy an audit
                </button>
              )}
            </div>
          )}
        </section>
      )}

      {status?.configured && !canManage && (
        <section className="rounded-2xl border border-line bg-surface p-5 text-sm text-muted">
          Only an organization owner can start or change the plan.
        </section>
      )}
    </div>
  );
}

function Stat({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: "warn" }) {
  return (
    <div className="rounded-xl border border-line bg-surface-raised/40 p-3">
      <div className="text-[11px] uppercase tracking-wider text-muted">{label}</div>
      <div className="mt-1 text-lg font-semibold">{value}</div>
      {sub && <div className={`mt-0.5 text-xs ${tone === "warn" ? "text-amber-a" : "text-muted"}`}>{sub}</div>}
    </div>
  );
}

function PlanCard({
  title, lines, action, busy, quantity, setQuantity,
}: {
  title: string; lines: string[]; action?: () => void; busy: boolean; quantity?: number; setQuantity?: (q: number) => void;
}) {
  return (
    <div className="flex flex-col gap-3 rounded-xl border border-line p-4">
      <div className="font-semibold">{title}</div>
      <ul className="space-y-1 text-sm text-muted">
        {lines.map((l) => <li key={l}>{l}</li>)}
      </ul>
      {setQuantity && quantity !== undefined && (
        <label className="text-xs text-muted">
          Communities
          <input type="number" min={1} value={quantity} onChange={(e) => setQuantity(Math.max(1, Number(e.target.value) || 1))}
                 className="ml-2 w-20 rounded-lg border border-line bg-surface-raised px-2 py-1 text-sm text-foreground" />
        </label>
      )}
      <button type="button" disabled={!action || busy} onClick={action}
              className="mt-auto rounded-xl bg-violet-a px-4 py-2 text-sm font-medium text-background disabled:opacity-50">
        {busy ? "Opening Stripe…" : action ? "Continue to Stripe" : "Not available yet"}
      </button>
    </div>
  );
}
