"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  API_BASE,
  Property,
  PropertyTypesConfig,
  UploadRecord,
  fetchProperties,
  fetchPropertyTypes,
  fetchUploads,
} from "@/lib/api";
import { fmtDate, fmtDateTime } from "@/lib/format";
import { Disclosure } from "@/components/MetricCard";
import { GoogleConnections } from "@/components/GoogleConnections";

// `connector` is the key each source maps to in a property type's
// allowed_connectors list (note paid_media -> "paid").
const SOURCES = [
  { key: "ga4", connector: "ga4", label: "GA4 traffic", hint: "Export with Date + Session source/medium dimensions (add City + Region for the Audience report)" },
  { key: "ga4_events", connector: "ga4", label: "GA4 events", hint: "Events report export (event name + count); keep the date range or add a Date column" },
  { key: "gsc", connector: "gsc", label: "Search Console", hint: "Dates tab of the Performance export" },
  { key: "gbp", connector: "gbp", label: "Business Profile", hint: "Single-location daily performance export" },
  { key: "paid_media", connector: "paid", label: "Paid media", hint: "Daily campaign report (Google Ads or Meta)" },
  { key: "crm", connector: "crm", label: "CRM leads", hint: "Yardi adapter is a placeholder mapping for now" },
] as const;

type SourceKey = (typeof SOURCES)[number]["key"];

type UploadResponse = {
  rows_ingested: number;
  rows_replaced: number;
  rows_skipped: number;
  skipped: { line: number; reason: string }[];
  date_start: string;
  date_end: string;
  ai_rows_detected: number | null;
  disclosure: string | null;
  unmapped_columns: string[] | null;
  warnings: string[] | null;
};

export default function UploadsPage() {
  const [properties, setProperties] = useState<Property[]>([]);
  const [types, setTypes] = useState<PropertyTypesConfig | null>(null);
  const [history, setHistory] = useState<UploadRecord[]>([]);
  const [source, setSource] = useState<SourceKey>("ga4");
  const [propertyId, setPropertyId] = useState<string>("");
  const [platform, setPlatform] = useState("google_ads");
  const [sourceAccount, setSourceAccount] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<UploadResponse | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(() => {
    fetchProperties().then(setProperties).catch(() => {});
    fetchUploads().then(setHistory).catch(() => {});
  }, []);

  useEffect(refresh, [refresh]);
  useEffect(() => {
    fetchPropertyTypes().then(setTypes).catch(() => {});
  }, []);

  // Which connectors this property's client/site type supports. Until a
  // property is chosen (or the config loads) every source is shown.
  const selectedProperty = properties.find((p) => String(p.id) === propertyId);
  const allowedConnectors =
    selectedProperty && types
      ? types.types[selectedProperty.property_type]?.allowed_connectors ?? null
      : null;
  const visibleSources = allowedConnectors
    ? SOURCES.filter((s) => allowedConnectors.includes(s.connector))
    : SOURCES;

  // If the current source is not allowed for the newly selected property,
  // fall back to its first available source.
  useEffect(() => {
    if (allowedConnectors && !visibleSources.some((s) => s.key === source)) {
      setSource(visibleSources[0]?.key ?? "ga4");
      setResult(null);
      setUploadError(null);
    }
  }, [allowedConnectors, visibleSources, source]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const file = fileRef.current?.files?.[0];
    if (!file || !propertyId) return;

    const form = new FormData();
    form.set("property_id", propertyId);
    form.set("file", file);
    if (sourceAccount) form.set("source_account", sourceAccount);
    if (source === "paid_media") form.set("platform", platform);
    if (source === "crm") form.set("adapter", "yardi");

    setBusy(true);
    setResult(null);
    setUploadError(null);
    try {
      const res = await fetch(`${API_BASE}/uploads/${source}`, {
        method: "POST",
        body: form,
      });
      const body = await res.json();
      if (!res.ok) {
        setUploadError(body.detail ?? "Upload failed.");
      } else {
        setResult(body);
        if (fileRef.current) fileRef.current.value = "";
      }
    } catch {
      setUploadError("Could not reach the Beacon API. Is the backend running?");
    } finally {
      setBusy(false);
      refresh();
    }
  }

  const activeSource = SOURCES.find((s) => s.key === source)!;

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Uploads</h1>
        <p className="mt-1 text-sm text-muted">
          Manual exports are the ingestion path for now. Every upload keeps its
          raw file and provenance.
        </p>
      </div>

      <form
        onSubmit={submit}
        className="space-y-4 rounded-2xl border border-line bg-surface p-6"
      >
        <div className="flex flex-wrap gap-2">
          {visibleSources.map((s) => (
            <button
              type="button"
              key={s.key}
              onClick={() => {
                setSource(s.key);
                setResult(null);
                setUploadError(null);
              }}
              className={`rounded-xl border px-3 py-1.5 text-sm transition-colors ${
                source === s.key
                  ? "border-violet-a/60 bg-violet-a/15 text-violet-a"
                  : "border-line text-muted hover:text-foreground"
              }`}
            >
              {s.label}
            </button>
          ))}
        </div>
        <p className="text-xs text-muted">{activeSource.hint}</p>
        {selectedProperty && allowedConnectors && visibleSources.length < SOURCES.length && (
          <p className="text-xs text-muted">
            {selectedProperty.name} is a{" "}
            {types?.types[selectedProperty.property_type]?.label ??
              selectedProperty.property_type}
            , so only its supported data sources are shown.
          </p>
        )}

        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block text-sm">
            <span className="text-muted">Property</span>
            <select
              required
              value={propertyId}
              onChange={(e) => setPropertyId(e.target.value)}
              className="mt-1 w-full rounded-xl border border-line bg-surface-raised px-3 py-2"
            >
              <option value="">Select a property…</option>
              {properties.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-sm">
            <span className="text-muted">Source account (optional, for citations)</span>
            <input
              value={sourceAccount}
              onChange={(e) => setSourceAccount(e.target.value)}
              placeholder="e.g. GA4 property 498231775"
              className="mt-1 w-full rounded-xl border border-line bg-surface-raised px-3 py-2"
            />
          </label>
          {source === "paid_media" && (
            <label className="block text-sm">
              <span className="text-muted">Platform</span>
              <select
                value={platform}
                onChange={(e) => setPlatform(e.target.value)}
                className="mt-1 w-full rounded-xl border border-line bg-surface-raised px-3 py-2"
              >
                <option value="google_ads">Google Ads</option>
                <option value="meta">Meta</option>
                <option value="other">Other</option>
              </select>
            </label>
          )}
          <label className="block text-sm">
            <span className="text-muted">Export file (CSV)</span>
            <input
              ref={fileRef}
              type="file"
              accept=".csv,text/csv"
              required
              className="mt-1 w-full rounded-xl border border-line bg-surface-raised px-3 py-2 file:mr-3 file:rounded-lg file:border-0 file:bg-violet-a/20 file:px-3 file:py-1 file:text-violet-a"
            />
          </label>
        </div>

        <button
          disabled={busy}
          className="rounded-xl bg-violet-a px-4 py-2 text-sm font-medium text-background disabled:opacity-50"
        >
          {busy ? "Uploading…" : "Upload"}
        </button>

        {uploadError && (
          <div className="rounded-xl border border-pink-a/40 bg-pink-a/10 p-3 text-sm text-pink-a">
            {uploadError}
          </div>
        )}
        {result && (
          <div className="space-y-2 rounded-xl border border-emerald-a/30 bg-emerald-a/10 p-4 text-sm">
            <p className="font-medium text-emerald-a">
              Processed: {result.rows_ingested} rows ingested
              {result.rows_replaced > 0 && `, ${result.rows_replaced} replaced`}
              {result.rows_skipped > 0 && `, ${result.rows_skipped} skipped`}
              {" "}({fmtDate(result.date_start)} to {fmtDate(result.date_end)})
            </p>
            {result.ai_rows_detected !== null && (
              <div>
                AI referral rows detected: {result.ai_rows_detected}
                {result.disclosure && <Disclosure text={result.disclosure} />}
              </div>
            )}
            {result.unmapped_columns && (
              <p className="text-amber-a">
                Columns not recognized (not ingested):{" "}
                {result.unmapped_columns.join(", ")}
              </p>
            )}
            {result.warnings?.map((w) => (
              <p key={w} className="text-amber-a">
                ⚠ {w}
              </p>
            ))}
            {result.skipped.length > 0 && (
              <ul className="list-inside list-disc text-muted">
                {result.skipped.map((s) => (
                  <li key={`${s.line}-${s.reason}`}>
                    Line {s.line}: {s.reason}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </form>

      <GoogleConnections propertyId={propertyId} />

      <section>
        <h2 className="mb-3 text-sm font-medium text-muted">Ingest history</h2>
        <div className="overflow-x-auto rounded-2xl border border-line bg-surface">
          <table className="w-full text-left text-sm">
            <thead className="text-xs text-muted">
              <tr className="border-b border-line">
                <th className="px-4 py-3">When</th>
                <th className="px-4 py-3">Source</th>
                <th className="px-4 py-3">File</th>
                <th className="px-4 py-3">Rows</th>
                <th className="px-4 py-3">Covers</th>
                <th className="px-4 py-3">Status</th>
              </tr>
            </thead>
            <tbody>
              {history.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-6 text-center text-muted">
                    No uploads yet.
                  </td>
                </tr>
              )}
              {history.map((u) => (
                <tr key={u.id} className="border-b border-line/50 last:border-0">
                  <td className="px-4 py-3 whitespace-nowrap">
                    {fmtDateTime(u.uploaded_at)}
                  </td>
                  <td className="px-4 py-3 uppercase text-muted">{u.source_type}</td>
                  <td className="max-w-56 truncate px-4 py-3" title={u.filename}>
                    {u.filename}
                  </td>
                  <td className="px-4 py-3">{u.row_count ?? ""}</td>
                  <td className="px-4 py-3 whitespace-nowrap text-muted">
                    {u.date_start && u.date_end
                      ? `${fmtDate(u.date_start)} to ${fmtDate(u.date_end)}`
                      : ""}
                  </td>
                  <td className="px-4 py-3">
                    {u.status === "processed" ? (
                      <span className="rounded-full bg-emerald-a/15 px-2 py-0.5 text-xs text-emerald-a">
                        processed
                      </span>
                    ) : u.status === "failed" ? (
                      <span
                        className="cursor-help rounded-full bg-pink-a/15 px-2 py-0.5 text-xs text-pink-a"
                        title={u.error_message ?? undefined}
                      >
                        failed
                      </span>
                    ) : (
                      <span className="rounded-full bg-amber-a/15 px-2 py-0.5 text-xs text-amber-a">
                        pending
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
