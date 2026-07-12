"use client";

import { useCallback, useEffect, useState } from "react";
import { API_BASE } from "@/lib/api";

type Connection = {
  id: number;
  property_id: number;
  source_type: string;
  account_name: string;
  resource_id: string | null;
  resource_name: string | null;
  oauth_status: string;
  sync_status: string;
  last_sync_at: string | null;
  error_message: string | null;
};

type Resource = { id: string; name: string };

const SOURCE_LABELS: Record<string, string> = {
  ga4: "GA4 traffic",
  gsc: "Search Console",
};

function fmtWhen(iso: string | null) {
  if (!iso) return null;
  return new Date(iso).toLocaleString("en-US", {
    month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
  });
}

export function GoogleConnections({ propertyId }: { propertyId: string }) {
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [connections, setConnections] = useState<Connection[]>([]);
  const [resources, setResources] = useState<Record<number, Resource[]>>({});
  const [busy, setBusy] = useState<number | null>(null);
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(() => {
    if (!propertyId) return;
    fetch(`${API_BASE}/google/status?property_id=${propertyId}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((b) => {
        if (!b) return; // older backend or transient error: render nothing
        setConfigured(!!b.configured);
        setConnections(b.connections ?? []);
      })
      .catch(() => {});
  }, [propertyId]);

  useEffect(load, [load]);

  // Post-OAuth banner (the callback redirects to /uploads?google=...).
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const g = params.get("google");
    if (g === "connected") {
      setNotice({ ok: true, text: "Google account connected. Pick which GA4 property and Search Console site feed this property, then Sync now." });
    } else if (g === "error") {
      setNotice({ ok: false, text: `Google connection failed: ${params.get("reason") ?? "unknown error"}` });
    }
    if (g) window.history.replaceState(null, "", window.location.pathname);
  }, []);

  async function connect() {
    const res = await fetch(`${API_BASE}/google/connect?property_id=${propertyId}`);
    const body = await res.json();
    if (!res.ok) {
      setNotice({ ok: false, text: body.detail ?? "Could not start the Google connect flow." });
      return;
    }
    window.location.href = body.auth_url;
  }

  async function loadResources(conn: Connection) {
    setBusy(conn.id);
    try {
      const res = await fetch(`${API_BASE}/google/connections/${conn.id}/resources`);
      const body = await res.json();
      if (res.ok) setResources((m) => ({ ...m, [conn.id]: body.resources }));
      else setNotice({ ok: false, text: body.detail ?? "Could not list sources." });
    } finally {
      setBusy(null);
    }
  }

  async function pickResource(conn: Connection, id: string) {
    const chosen = resources[conn.id]?.find((r) => r.id === id);
    await fetch(`${API_BASE}/google/connections/${conn.id}/resource`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ resource_id: id, resource_name: chosen?.name ?? id }),
    });
    load();
  }

  async function syncNow(conn: Connection) {
    setBusy(conn.id);
    setNotice(null);
    try {
      const res = await fetch(`${API_BASE}/google/connections/${conn.id}/sync`, { method: "POST" });
      const body = await res.json();
      if (res.ok) {
        setNotice({
          ok: true,
          text: `${SOURCE_LABELS[conn.source_type]}: synced ${body.rows_imported} rows (${body.date_start} to ${body.date_end}).`,
        });
      } else {
        setNotice({ ok: false, text: body.detail ?? "Sync failed." });
      }
    } finally {
      setBusy(null);
      load();
    }
  }

  async function disconnect(conn: Connection) {
    if (!window.confirm("Disconnect Google for this source? Synced data stays.")) return;
    await fetch(`${API_BASE}/google/connections/${conn.id}`, { method: "DELETE" });
    load();
  }

  if (!propertyId || configured === null) return null;

  const active = connections.filter((c) => c.oauth_status === "connected");

  return (
    <section className="space-y-3 rounded-2xl border border-line bg-surface p-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-medium">Google auto-sync</h2>
          <p className="mt-0.5 text-xs text-muted">
            Scheduled sync from the GA4 Data API and Search Console API. Not
            real-time: Google&apos;s own data lags a day or two.
          </p>
        </div>
        {configured && (
          <button
            onClick={connect}
            className="rounded-xl border border-line px-3 py-1.5 text-sm text-muted hover:text-foreground"
          >
            {active.length ? "Reconnect Google" : "Connect Google"}
          </button>
        )}
      </div>

      {!configured && (
        <p className="text-xs text-muted">
          Not configured on this server. Set BEACON_GOOGLE_CLIENT_ID and
          BEACON_GOOGLE_CLIENT_SECRET (see the README&apos;s Google sync section).
        </p>
      )}

      {notice && (
        <p className={`text-xs ${notice.ok ? "text-emerald-a" : "text-pink-a"}`}>{notice.text}</p>
      )}

      {active.map((conn) => (
        <div key={conn.id} className="flex flex-wrap items-center gap-3 rounded-xl border border-line bg-surface-raised px-4 py-3">
          <div className="min-w-40">
            <p className="text-sm font-medium">{SOURCE_LABELS[conn.source_type] ?? conn.source_type}</p>
            <p className="text-xs text-muted">{conn.account_name}</p>
          </div>

          {resources[conn.id] ? (
            <select
              value={conn.resource_id ?? ""}
              onChange={(e) => pickResource(conn, e.target.value)}
              className="min-w-56 rounded-lg border border-line bg-surface px-2.5 py-1.5 text-sm"
            >
              <option value="">Choose a source…</option>
              {resources[conn.id].map((r) => (
                <option key={r.id} value={r.id}>{r.name}</option>
              ))}
            </select>
          ) : (
            <button
              onClick={() => loadResources(conn)}
              disabled={busy === conn.id}
              className="rounded-lg border border-line px-2.5 py-1.5 text-xs text-muted hover:text-foreground disabled:opacity-50"
            >
              {conn.resource_name ?? (busy === conn.id ? "Loading…" : "Choose source")}
            </button>
          )}

          <div className="ml-auto flex items-center gap-3">
            {conn.error_message && (
              <span className="max-w-64 truncate text-xs text-pink-a" title={conn.error_message}>
                {conn.error_message}
              </span>
            )}
            <span className="text-xs text-muted">
              {conn.last_sync_at ? `Last updated ${fmtWhen(conn.last_sync_at)}` : "Never synced"}
            </span>
            <button
              onClick={() => syncNow(conn)}
              disabled={busy === conn.id || !conn.resource_id}
              title={conn.resource_id ? undefined : "Choose a source first"}
              className="rounded-lg bg-violet-a px-3 py-1.5 text-xs font-medium text-background disabled:opacity-50"
            >
              {busy === conn.id ? "Syncing…" : "Sync now"}
            </button>
            <button
              onClick={() => disconnect(conn)}
              className="text-xs text-muted underline decoration-dotted hover:text-foreground"
            >
              Disconnect
            </button>
          </div>
        </div>
      ))}
    </section>
  );
}
