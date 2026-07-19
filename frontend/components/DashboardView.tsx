"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import {
  API_BASE,
  Company,
  Dashboard,
  Property,
  SCOPE_STORAGE_KEY,
  exportUrl,
  fetchCompanies,
  fetchDashboard,
  fetchProperties,
} from "@/lib/api";
import { fmtDate, fmtMoney, fmtNum, fmtPct } from "@/lib/format";
import { AIMetricCard, Disclosure, MetricCard } from "@/components/MetricCard";
import { ProvenanceFooter } from "@/components/Provenance";
import { TrendChart } from "@/components/TrendChart";
import { PlatformDonut } from "@/components/PlatformDonut";
import { Funnel } from "@/components/Funnel";
import { EventsPanel } from "@/components/EventsPanel";

const RANGES = [7, 30, 90];

// Portfolio-mode scope: "" = nothing chosen yet, "all" = every property,
// "unassigned" = properties with no company, or a company id as a string.
type ScopeValue = "" | "all" | "unassigned" | string;

export function DashboardView({ propertyId }: { propertyId: number | null }) {
  const router = useRouter();
  const isProperty = propertyId !== null;

  const [days, setDays] = useState(30);
  const [properties, setProperties] = useState<Property[]>([]);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [scope, setScope] = useState<ScopeValue>("");
  // Defer the gate/body until we've read the persisted scope, so a remembered
  // selection doesn't flash the "choose a company" screen first.
  const [scopeReady, setScopeReady] = useState(false);
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(isProperty);
  const [staleSources, setStaleSources] = useState<string[]>([]);

  useEffect(() => {
    fetchProperties().then(setProperties).catch(() => {});
    fetchCompanies().then(setCompanies).catch(() => {});
  }, []);

  // Honesty check: if this property's Google connections have not synced in
  // 48h, say so rather than quietly showing aging numbers.
  useEffect(() => {
    if (!isProperty) {
      setStaleSources([]);
      return;
    }
    fetch(`${API_BASE}/google/status?property_id=${propertyId}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((b) => {
        if (!b?.connections) return;
        const now = Date.now();
        const stale = b.connections
          .filter((c: { oauth_status: string }) => c.oauth_status === "connected")
          .filter((c: { last_sync_at: string | null }) => {
            if (!c.last_sync_at) return true;
            return now - new Date(c.last_sync_at).getTime() > 48 * 3600 * 1000;
          })
          .map((c: { source_type: string }) =>
            c.source_type === "ga4" ? "GA4 traffic" : "Search Console",
          );
        setStaleSources(stale);
      })
      .catch(() => {});
  }, [isProperty, propertyId]);

  // Restore the last-used company scope (portfolio mode only).
  useEffect(() => {
    if (!isProperty) {
      try {
        const saved = localStorage.getItem(SCOPE_STORAGE_KEY);
        if (saved) setScope(saved);
      } catch {}
    }
    setScopeReady(true);
  }, [isProperty]);

  function chooseScope(v: ScopeValue) {
    setScope(v);
    try {
      if (v) localStorage.setItem(SCOPE_STORAGE_KEY, v);
      else localStorage.removeItem(SCOPE_STORAGE_KEY);
    } catch {}
  }

  const companyId = /^\d+$/.test(scope) ? Number(scope) : null;
  const unassigned = scope === "unassigned";
  const scopeChosen = isProperty || scope !== "";

  useEffect(() => {
    if (!scopeChosen) {
      setData(null);
      return;
    }
    setLoading(true);
    fetchDashboard(
      propertyId,
      days,
      isProperty ? null : companyId,
      isProperty ? false : unassigned
    )
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [propertyId, days, scope]);

  const currentProperty = properties.find((p) => p.id === propertyId) ?? null;
  const currentCompany = companies.find((c) => c.id === companyId) ?? null;
  const hasUnassigned = properties.some((p) => p.company_id === null);

  // Properties available to drill into, given the chosen company scope.
  const drillProperties = useMemo(
    () =>
      properties.filter((p) =>
        scope === "all"
          ? true
          : scope === "unassigned"
          ? p.company_id === null
          : p.company_id === companyId
      ),
    [properties, scope, companyId]
  );

  const scopeTitle = isProperty
    ? currentProperty?.name ?? "Property"
    : scope === ""
    ? "Portfolio"
    : scope === "all"
    ? "All companies"
    : scope === "unassigned"
    ? "Unassigned properties"
    : currentCompany?.name ?? "Company";

  const hasAnyData =
    data && (data.ga4 || data.gsc || data.gbp || data.paid || data.crm);

  const currentExportUrl = isProperty
    ? exportUrl(propertyId)
    : exportUrl(null, companyId, unassigned);

  return (
    <div className="space-y-6">
      {staleSources.length > 0 && (
        <div className="rounded-2xl border border-amber-a/40 bg-amber-a/10 px-4 py-3 text-sm text-amber-a">
          Google auto-sync is behind for {staleSources.join(" and ")} (no successful
          sync in over 48 hours). The numbers below may be stale. Open Uploads to
          Sync now, or check Admin for the reason.
        </div>
      )}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{scopeTitle}</h1>
          {isProperty && currentProperty?.company_id != null && (
            <p className="mt-0.5 text-xs text-muted">
              {companies.find((c) => c.id === currentProperty.company_id)?.name}
            </p>
          )}
          {data && scopeChosen && (
            <p className="mt-1 text-sm text-muted">
              {fmtDate(data.window.start)} to {fmtDate(data.window.end)}
              {data.window.anchored_to_latest_data &&
                " (anchored to latest ingested data)"}
            </p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {isProperty ? (
            <select
              aria-label="Property"
              className="rounded-xl border border-line bg-surface px-3 py-2 text-sm"
              value={propertyId ?? ""}
              onChange={(e) => router.push(e.target.value ? `/properties/${e.target.value}` : "/")}
            >
              <option value="">Back to portfolio</option>
              {properties.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          ) : (
            <>
              <select
                aria-label="Company"
                className="rounded-xl border border-line bg-surface px-3 py-2 text-sm"
                value={scope}
                onChange={(e) => chooseScope(e.target.value)}
              >
                <option value="">Select a company…</option>
                <option value="all">All companies</option>
                {companies.map((c) => (
                  <option key={c.id} value={String(c.id)}>
                    {c.name}
                  </option>
                ))}
                {hasUnassigned && <option value="unassigned">Unassigned</option>}
              </select>
              {scopeChosen && (
                <select
                  aria-label="Property"
                  className="rounded-xl border border-line bg-surface px-3 py-2 text-sm"
                  value=""
                  onChange={(e) =>
                    e.target.value && router.push(`/properties/${e.target.value}`)
                  }
                >
                  <option value="">
                    {scopeTitle} overview{drillProperties.length ? " · open a property" : ""}
                  </option>
                  {drillProperties.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              )}
            </>
          )}
          {scopeChosen && (
            <>
              <div className="flex rounded-xl border border-line bg-surface p-1 text-sm">
                {RANGES.map((r) => (
                  <button
                    key={r}
                    onClick={() => setDays(r)}
                    className={`rounded-lg px-3 py-1 transition-colors ${
                      days === r ? "bg-surface-raised text-foreground" : "text-muted"
                    }`}
                  >
                    {r}d
                  </button>
                ))}
              </div>
              <a
                href={currentExportUrl}
                className="rounded-xl border border-line bg-surface px-3 py-2 text-sm font-medium text-foreground transition-colors hover:bg-surface-raised"
                title={`Export ${scopeTitle} data as CSV`}
              >
                Export data
              </a>
            </>
          )}
        </div>
      </div>

      {/* Company-first gate: nothing shown until a company/scope is chosen.
          Held back until the persisted scope is read so a remembered choice
          restores straight to its data instead of flashing the gate. */}
      {scopeReady && !scopeChosen && (
        <div className="rounded-2xl border border-line bg-surface p-10 text-center">
          <p className="text-lg font-medium">Choose a company to begin</p>
          <p className="mx-auto mt-1 max-w-md text-sm text-muted">
            Pick a company above to see its portfolio, or choose &quot;All
            companies&quot; for everything. You can then drill into any single
            property.
          </p>
          {companies.length === 0 && (
            <Link
              href="/properties"
              className="mt-4 inline-block rounded-xl bg-violet-a px-4 py-2 text-sm font-medium text-background"
            >
              Add a company and properties
            </Link>
          )}
        </div>
      )}

      {error && (
        <div className="rounded-2xl border border-pink-a/40 bg-pink-a/10 p-4 text-sm text-pink-a">
          Could not reach the Beacon API. Is the backend running on port 8600?
        </div>
      )}

      {scopeChosen && loading && !data && <p className="text-muted">Loading…</p>}

      {scopeChosen && data && !hasAnyData && !error && (
        <div className="rounded-2xl border border-line bg-surface p-10 text-center">
          <p className="text-lg font-medium">No data yet</p>
          <p className="mt-1 text-sm text-muted">
            {isProperty || drillProperties.length
              ? "Upload a GA4 or Search Console export to light up this dashboard."
              : "This scope has no properties with data yet. Add properties or upload data."}
          </p>
          <Link
            href="/uploads"
            className="mt-4 inline-block rounded-xl bg-violet-a px-4 py-2 text-sm font-medium text-background"
          >
            Go to uploads
          </Link>
        </div>
      )}

      {data?.ga4 && (
        <>
          <section className="rounded-2xl border border-line bg-surface p-5">
            <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
              <MetricCard
                label="Sessions"
                value={fmtNum(data.ga4.sessions)}
                sub={`${fmtNum(data.ga4.key_events)} key events`}
                className="gradient-hairline"
              />
              <AIMetricCard
                label="AI referral sessions"
                value={fmtNum(data.ga4.ai_sessions)}
                sub={`${fmtNum(data.ga4.ai_key_events)} key events from AI traffic`}
                disclosure={data.ga4.disclosure}
              />
              <AIMetricCard
                label="AI share of sessions"
                value={fmtPct(data.ga4.ai_share)}
                disclosure={data.ga4.disclosure}
              />
              <MetricCard
                label="Key events"
                value={fmtNum(data.ga4.key_events)}
                accent="var(--accent-emerald)"
              />
            </div>
            <ProvenanceFooter provenance={data.ga4.provenance} />
          </section>

          <div className="grid gap-4 lg:grid-cols-5">
            <section className="rounded-2xl border border-line bg-surface p-5 lg:col-span-3">
              <h2 className="mb-4 text-sm font-medium text-muted">
                Sessions vs AI sessions
              </h2>
              <TrendChart data={data.ga4.trend} />
              <ProvenanceFooter provenance={data.ga4.provenance} />
            </section>
            <section className="rounded-2xl border border-line bg-surface p-5 lg:col-span-2">
              <h2 className="mb-4 text-sm font-medium text-muted">
                AI platform mix
              </h2>
              {data.ga4.platform_mix.length ? (
                <PlatformDonut data={data.ga4.platform_mix} />
              ) : (
                <p className="text-sm text-muted">
                  No AI referrals detected in this window.
                </p>
              )}
              <Disclosure text={data.ga4.disclosure} />
              <ProvenanceFooter provenance={data.ga4.provenance} />
            </section>
          </div>
        </>
      )}

      {data?.events && <EventsPanel section={data.events} />}

      <div className="grid gap-4 lg:grid-cols-3">
        {data?.gsc && (
          <section className="rounded-2xl border border-line bg-surface p-5">
            <h2 className="mb-3 text-sm font-medium text-muted">Organic search</h2>
            <div className="grid grid-cols-2 gap-3 text-sm">
              <Stat label="Clicks" value={fmtNum(data.gsc.clicks)} />
              <Stat label="Impressions" value={fmtNum(data.gsc.impressions)} />
              <Stat label="CTR" value={fmtPct(data.gsc.ctr)} />
              <Stat label="Avg position" value={String(data.gsc.avg_position)} />
            </div>
            <ProvenanceFooter provenance={data.gsc.provenance} />
          </section>
        )}
        {data?.gbp && (
          <section className="rounded-2xl border border-line bg-surface p-5">
            <h2 className="mb-3 text-sm font-medium text-muted">Business Profile</h2>
            <div className="grid grid-cols-2 gap-3 text-sm">
              <Stat
                label="Search views"
                value={fmtNum(data.gbp.search_impressions)}
              />
              <Stat label="Maps views" value={fmtNum(data.gbp.maps_impressions)} />
              <Stat label="Website clicks" value={fmtNum(data.gbp.website_clicks)} />
              <Stat label="Calls" value={fmtNum(data.gbp.calls)} />
              <Stat
                label="Directions"
                value={fmtNum(data.gbp.direction_requests)}
              />
            </div>
            <ProvenanceFooter provenance={data.gbp.provenance} />
          </section>
        )}
        {data?.paid && (
          <section className="rounded-2xl border border-line bg-surface p-5">
            <h2 className="mb-3 text-sm font-medium text-muted">Paid media</h2>
            <div className="grid grid-cols-2 gap-3 text-sm">
              <Stat label="Spend" value={fmtMoney(data.paid.spend)} />
              <Stat label="Clicks" value={fmtNum(data.paid.clicks)} />
              <Stat label="Impressions" value={fmtNum(data.paid.impressions)} />
              <Stat label="Conversions" value={fmtNum(data.paid.conversions)} />
            </div>
            <ProvenanceFooter provenance={data.paid.provenance} />
          </section>
        )}
      </div>

      {data?.crm && (
        <section className="rounded-2xl border border-line bg-surface p-5">
          <h2 className="mb-4 text-sm font-medium text-muted">
            Lead funnel ({fmtNum(data.crm.total_leads)} leads in window)
          </h2>
          <Funnel crm={data.crm} />
          <ProvenanceFooter provenance={data.crm.provenance} />
        </section>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-muted">{label}</p>
      <p className="text-lg font-semibold">{value}</p>
    </div>
  );
}
