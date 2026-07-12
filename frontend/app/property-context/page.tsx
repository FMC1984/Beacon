"use client";

import { useCallback, useEffect, useState } from "react";
import { API_BASE, Company, Property, fetchCompanies, fetchProperties } from "@/lib/api";
import { ScopeSelect } from "@/components/ScopeSelect";

type Vocab = {
  property_types: string[];
  regulatory_programs: string[];
  restriction_flags: string[];
};

type Context = {
  configured: boolean;
  property_type: string | null;
  target_audience: string | null;
  is_regulated: boolean | null;
  regulatory_programs: string[];
  marketing_restriction_flags: string[];
  marketing_restriction_notes: string | null;
  effective_regulatory: string;
};

type RegChoice = "regulated" | "not" | "unspecified";

const REG_LABEL: Record<string, string> = {
  regulated: "Regulated",
  not_regulated: "Not regulated",
  unknown: "Unspecified (unknown)",
};

export default function PropertyContextPage() {
  const [properties, setProperties] = useState<Property[]>([]);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [propertyId, setPropertyId] = useState<number | null>(null);
  const [vocab, setVocab] = useState<Vocab | null>(null);
  const [ctx, setCtx] = useState<Context | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Editable form state.
  const [type, setType] = useState("");
  const [audience, setAudience] = useState("");
  const [reg, setReg] = useState<RegChoice>("unspecified");
  const [programs, setPrograms] = useState<string[]>([]);
  const [flags, setFlags] = useState<string[]>([]);
  const [notes, setNotes] = useState("");

  useEffect(() => {
    fetchProperties()
      .then((p) => {
        setProperties(p);
        if (p.length) setPropertyId(p[0].id);
      })
      .catch(() => setError("Could not reach the Beacon API."));
    fetchCompanies().then(setCompanies).catch(() => {});
    fetch(`${API_BASE}/property-context/vocabulary`)
      .then((r) => r.json())
      .then(setVocab)
      .catch(() => {});
  }, []);

  const load = useCallback((id: number) => {
    fetch(`${API_BASE}/property-context/${id}`)
      .then((r) => r.json())
      .then((c: Context) => {
        setCtx(c);
        setType(c.property_type ?? "");
        setAudience(c.target_audience ?? "");
        setReg(
          c.is_regulated === true
            ? "regulated"
            : c.is_regulated === false
              ? "not"
              : "unspecified",
        );
        setPrograms(c.regulatory_programs ?? []);
        setFlags(c.marketing_restriction_flags ?? []);
        setNotes(c.marketing_restriction_notes ?? "");
        setSaved(false);
      })
      .catch(() => setError("Could not reach the Beacon API."));
  }, []);

  useEffect(() => {
    if (propertyId !== null) load(propertyId);
  }, [propertyId, load]);

  function toggle(list: string[], value: string, set: (v: string[]) => void) {
    set(list.includes(value) ? list.filter((x) => x !== value) : [...list, value]);
  }

  async function save() {
    if (propertyId === null) return;
    setSaving(true);
    setError(null);
    const body = {
      property_type: type || null,
      target_audience: audience || null,
      is_regulated: reg === "regulated" ? true : reg === "not" ? false : null,
      regulatory_programs: programs,
      marketing_restriction_flags: flags,
      marketing_restriction_notes: notes || null,
    };
    try {
      const res = await fetch(`${API_BASE}/property-context/${propertyId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        setError((await res.json()).detail ?? "Save failed.");
      } else {
        setSaved(true);
        load(propertyId);
      }
    } catch {
      setError("Could not reach the Beacon API.");
    } finally {
      setSaving(false);
    }
  }

  const val = (s: string | null) =>
    s ? <span>{s}</span> : <span className="text-muted italic">unspecified</span>;

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Property Context</h1>
          <p className="mt-1 text-sm text-muted">
            Operator-provided context that keeps recommendations compliant.
            Regulatory status is never inferred; leave it unspecified if unknown.
          </p>
        </div>
        <ScopeSelect
          companies={companies}
          properties={properties}
          value={propertyId}
          onChange={setPropertyId}
        />
      </div>

      {ctx && (
        <div
          className="rounded-2xl border border-line bg-surface p-4 text-sm"
          style={{ borderColor: ctx.configured ? undefined : "var(--border)" }}
        >
          <p className="mb-2 text-xs font-medium text-muted">Current (as stored)</p>
          <div className="grid grid-cols-2 gap-2">
            <div>Type: {val(ctx.property_type)}</div>
            <div>
              Regulatory:{" "}
              <span
                className={
                  ctx.effective_regulatory === "unknown" ? "text-amber-a" : ""
                }
              >
                {REG_LABEL[ctx.effective_regulatory]}
              </span>
            </div>
            <div>Audience: {val(ctx.target_audience)}</div>
            <div>
              Programs:{" "}
              {ctx.regulatory_programs.length ? (
                ctx.regulatory_programs.join(", ")
              ) : (
                <span className="text-muted italic">none</span>
              )}
            </div>
          </div>
        </div>
      )}

      {vocab && (
        <div className="space-y-5 rounded-2xl border border-line bg-surface p-6">
          <label className="block text-sm">
            <span className="text-muted">Property type</span>
            <select
              value={type}
              onChange={(e) => setType(e.target.value)}
              className="mt-1 w-full rounded-xl border border-line bg-surface-raised px-3 py-2"
            >
              <option value="">Unspecified</option>
              {vocab.property_types.map((t) => (
                <option key={t} value={t}>
                  {t.replace("_", " ")}
                </option>
              ))}
            </select>
          </label>

          <label className="block text-sm">
            <span className="text-muted">Target audience</span>
            <input
              value={audience}
              onChange={(e) => setAudience(e.target.value)}
              placeholder="e.g. ASU students, active seniors 55+"
              className="mt-1 w-full rounded-xl border border-line bg-surface-raised px-3 py-2"
            />
          </label>

          <div className="text-sm">
            <span className="text-muted">Regulatory status</span>
            <div className="mt-1 flex gap-2">
              {(
                [
                  ["regulated", "Regulated"],
                  ["not", "Not regulated"],
                  ["unspecified", "Unspecified"],
                ] as [RegChoice, string][]
              ).map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setReg(value)}
                  className={`flex-1 rounded-xl border px-3 py-2 transition-colors ${
                    reg === value
                      ? "border-violet-a/60 bg-violet-a/15 text-violet-a"
                      : "border-line text-muted hover:text-foreground"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
            <p className="mt-1 text-xs text-muted">
              Leave Unspecified when unknown. Beacon treats unknown as unknown,
              never as unregulated, and withholds compliance-sensitive guidance.
            </p>
          </div>

          <div className="text-sm">
            <span className="text-muted">Regulatory programs</span>
            <div className="mt-1 flex flex-wrap gap-2">
              {vocab.regulatory_programs.map((p) => (
                <button
                  key={p}
                  type="button"
                  onClick={() => toggle(programs, p, setPrograms)}
                  className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                    programs.includes(p)
                      ? "border-cyan-a/60 bg-cyan-a/15 text-cyan-a"
                      : "border-line text-muted hover:text-foreground"
                  }`}
                >
                  {p.replace("_", " ")}
                </button>
              ))}
            </div>
          </div>

          <div className="text-sm">
            <span className="text-muted">Marketing restrictions</span>
            <div className="mt-1 flex flex-wrap gap-2">
              {vocab.restriction_flags.map((f) => (
                <button
                  key={f}
                  type="button"
                  onClick={() => toggle(flags, f, setFlags)}
                  className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                    flags.includes(f)
                      ? "border-pink-a/60 bg-pink-a/15 text-pink-a"
                      : "border-line text-muted hover:text-foreground"
                  }`}
                >
                  {f.replace(/_/g, " ")}
                </button>
              ))}
            </div>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Restriction notes (optional)"
              className="mt-2 w-full rounded-xl border border-line bg-surface-raised px-3 py-2"
              rows={2}
            />
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={save}
              disabled={saving}
              className="rounded-xl bg-violet-a px-4 py-2 text-sm font-medium text-background disabled:opacity-50"
            >
              {saving ? "Saving…" : "Save context"}
            </button>
            {saved && <span className="text-sm text-emerald-a">Saved</span>}
            {error && <span className="text-sm text-pink-a">{error}</span>}
          </div>
        </div>
      )}
    </div>
  );
}
