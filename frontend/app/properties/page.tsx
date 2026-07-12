"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import {
  API_BASE,
  Company,
  Property,
  PropertyTypesConfig,
  fetchCompanies,
  fetchProperties,
  fetchPropertyTypes,
} from "@/lib/api";

type Draft = {
  name: string;
  propertyType: string;
  companyId: string;
  city: string;
  state: string;
  unitCount: string;
  websiteUrl: string;
};

const emptyDraft: Draft = {
  name: "",
  propertyType: "multifamily_apartment",
  companyId: "",
  city: "",
  state: "",
  unitCount: "",
  websiteUrl: "",
};

export default function PropertiesPage() {
  const [properties, setProperties] = useState<Property[]>([]);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [types, setTypes] = useState<PropertyTypesConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Create-property form
  const [name, setName] = useState("");
  const [propertyType, setPropertyType] = useState("multifamily_apartment");
  const [companyId, setCompanyId] = useState("");
  const [city, setCity] = useState("");
  const [state, setState] = useState("");
  const [unitCount, setUnitCount] = useState("");
  const [websiteUrl, setWebsiteUrl] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  // Company management
  const [newCompany, setNewCompany] = useState("");
  const [companyBusy, setCompanyBusy] = useState(false);
  const [companyError, setCompanyError] = useState<string | null>(null);
  const [confirmDeleteCompany, setConfirmDeleteCompany] = useState<number | null>(null);

  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);
  const [deleting, setDeleting] = useState(false);

  const [editingId, setEditingId] = useState<number | null>(null);
  const [draft, setDraft] = useState<Draft>(emptyDraft);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    Promise.all([fetchProperties(), fetchCompanies()])
      .then(([props, comps]) => {
        setProperties(props);
        setCompanies(comps);
      })
      .catch(() => setError("Could not reach the Beacon API."))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);
  useEffect(() => {
    fetchPropertyTypes().then(setTypes).catch(() => {});
  }, []);

  const typeLabel = (key: string) => types?.types[key]?.label ?? key;
  const unitLabel = (key: string) =>
    types?.types[key]?.terminology?.unit_count_label ?? "Unit count";

  async function createCompany(e: React.FormEvent) {
    e.preventDefault();
    if (!newCompany.trim()) return;
    setCompanyBusy(true);
    setCompanyError(null);
    try {
      const res = await fetch(`${API_BASE}/companies`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: newCompany.trim() }),
      });
      if (!res.ok) {
        setCompanyError((await res.json()).detail ?? "Could not create company.");
      } else {
        setNewCompany("");
        load();
      }
    } catch {
      setCompanyError("Could not reach the Beacon API.");
    } finally {
      setCompanyBusy(false);
    }
  }

  async function deleteCompany(id: number) {
    setConfirmDeleteCompany(null);
    try {
      await fetch(`${API_BASE}/companies/${id}`, { method: "DELETE" });
      load();
    } catch {
      setError("Could not reach the Beacon API.");
    }
  }

  async function createProperty(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setCreating(true);
    setCreateError(null);
    try {
      const res = await fetch(`${API_BASE}/properties`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: name.trim(),
          property_type: propertyType,
          company_id: companyId ? Number(companyId) : null,
          city: city.trim() || null,
          state: state.trim() || null,
          unit_count: unitCount ? Number(unitCount) : null,
          website_url: websiteUrl.trim() || null,
        }),
      });
      if (!res.ok) {
        setCreateError((await res.json()).detail ?? "Could not create property.");
      } else {
        setName("");
        setPropertyType("multifamily_apartment");
        setCompanyId("");
        setCity("");
        setState("");
        setUnitCount("");
        setWebsiteUrl("");
        load();
      }
    } catch {
      setCreateError("Could not reach the Beacon API.");
    } finally {
      setCreating(false);
    }
  }

  async function deleteProperty(id: number) {
    setDeleting(true);
    try {
      await fetch(`${API_BASE}/properties/${id}`, { method: "DELETE" });
      setConfirmDeleteId(null);
      load();
    } catch {
      setError("Could not reach the Beacon API.");
    } finally {
      setDeleting(false);
    }
  }

  function startEdit(p: Property) {
    setEditingId(p.id);
    setSaveError(null);
    setDraft({
      name: p.name,
      propertyType: p.property_type ?? "multifamily_apartment",
      companyId: p.company_id ? String(p.company_id) : "",
      city: p.city ?? "",
      state: p.state ?? "",
      unitCount: p.unit_count ? String(p.unit_count) : "",
      websiteUrl: p.website_url ?? "",
    });
  }

  async function saveEdit(id: number) {
    if (!draft.name.trim()) {
      setSaveError("Property name can't be empty.");
      return;
    }
    setSaving(true);
    setSaveError(null);
    try {
      const res = await fetch(`${API_BASE}/properties/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: draft.name.trim(),
          property_type: draft.propertyType,
          company_id: draft.companyId ? Number(draft.companyId) : null,
          city: draft.city.trim() || null,
          state: draft.state.trim() || null,
          unit_count: draft.unitCount ? Number(draft.unitCount) : null,
          website_url: draft.websiteUrl.trim() || null,
        }),
      });
      if (!res.ok) {
        setSaveError((await res.json()).detail ?? "Could not save changes.");
      } else {
        setEditingId(null);
        load();
      }
    } catch {
      setSaveError("Could not reach the Beacon API.");
    } finally {
      setSaving(false);
    }
  }

  // Group properties by company for display, companies first then Unassigned.
  const groups: { key: string; label: string; items: Property[] }[] = [
    ...companies.map((c) => ({
      key: `c${c.id}`,
      label: c.name,
      items: properties.filter((p) => p.company_id === c.id),
    })),
    {
      key: "unassigned",
      label: "Unassigned",
      items: properties.filter((p) => p.company_id === null),
    },
  ].filter((g) => g.items.length > 0);

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Properties</h1>
        <p className="mt-1 text-sm text-muted">
          Add a company, then the properties it manages. Deleting a property
          permanently removes all its uploaded data, content, context, and
          reviews. Deleting a company keeps its properties (they become
          Unassigned).
        </p>
      </div>

      {/* Companies */}
      <section className="space-y-3 rounded-2xl border border-line bg-surface p-6">
        <h2 className="text-sm font-medium text-muted">Companies</h2>
        <form onSubmit={createCompany} className="flex gap-2">
          <input
            value={newCompany}
            onChange={(e) => setNewCompany(e.target.value)}
            placeholder="e.g. Skyline Residential"
            className="flex-1 rounded-xl border border-line bg-surface-raised px-3 py-2 text-sm"
          />
          <button
            disabled={companyBusy || !newCompany.trim()}
            className="rounded-xl bg-violet-a px-4 py-2 text-sm font-medium text-background disabled:opacity-50"
          >
            {companyBusy ? "Adding…" : "Add company"}
          </button>
        </form>
        {companyError && (
          <div className="rounded-xl border border-pink-a/40 bg-pink-a/10 p-2.5 text-xs text-pink-a">
            {companyError}
          </div>
        )}
        {companies.length === 0 ? (
          <p className="text-xs text-muted">
            No companies yet. Add one to group your properties.
          </p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {companies.map((c) => (
              <span
                key={c.id}
                className="flex items-center gap-2 rounded-full border border-line bg-surface-raised px-3 py-1 text-xs"
              >
                <span className="font-medium">{c.name}</span>
                <span className="text-muted">{c.property_count} props</span>
                {confirmDeleteCompany === c.id ? (
                  <>
                    <button
                      onClick={() => deleteCompany(c.id)}
                      className="text-pink-a"
                      title="Delete company (properties kept)"
                    >
                      delete
                    </button>
                    <button onClick={() => setConfirmDeleteCompany(null)} className="text-muted">
                      no
                    </button>
                  </>
                ) : (
                  <button
                    onClick={() => setConfirmDeleteCompany(c.id)}
                    aria-label={`Delete ${c.name}`}
                    className="text-muted hover:text-pink-a"
                  >
                    ✕
                  </button>
                )}
              </span>
            ))}
          </div>
        )}
      </section>

      {/* Create property */}
      <form
        onSubmit={createProperty}
        className="space-y-4 rounded-2xl border border-line bg-surface p-6"
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block text-sm sm:col-span-2">
            <span className="text-muted">Property name</span>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Willow Creek Apartments"
              required
              className="mt-1 w-full rounded-xl border border-line bg-surface-raised px-3 py-2"
            />
          </label>
          <label className="block text-sm sm:col-span-2">
            <span className="text-muted">Company</span>
            <select
              value={companyId}
              onChange={(e) => setCompanyId(e.target.value)}
              className="mt-1 w-full rounded-xl border border-line bg-surface-raised px-3 py-2"
            >
              <option value="">No company (Unassigned)</option>
              {companies.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-sm sm:col-span-2">
            <span className="text-muted">Property type</span>
            <select
              value={propertyType}
              onChange={(e) => setPropertyType(e.target.value)}
              className="mt-1 w-full rounded-xl border border-line bg-surface-raised px-3 py-2"
            >
              {Object.entries(types?.types ?? {}).map(([key, info]) => (
                <option key={key} value={key}>
                  {info.label}
                </option>
              ))}
            </select>
            {types?.types[propertyType]?.description && (
              <span className="mt-1 block text-xs text-muted">
                {types.types[propertyType].description}
              </span>
            )}
          </label>
          <label className="block text-sm">
            <span className="text-muted">City</span>
            <input
              value={city}
              onChange={(e) => setCity(e.target.value)}
              className="mt-1 w-full rounded-xl border border-line bg-surface-raised px-3 py-2"
            />
          </label>
          <label className="block text-sm">
            <span className="text-muted">State</span>
            <input
              value={state}
              onChange={(e) => setState(e.target.value)}
              maxLength={2}
              placeholder="AZ"
              className="mt-1 w-full rounded-xl border border-line bg-surface-raised px-3 py-2"
            />
          </label>
          <label className="block text-sm">
            <span className="text-muted">{unitLabel(propertyType)}</span>
            <input
              value={unitCount}
              onChange={(e) => setUnitCount(e.target.value.replace(/\D/g, ""))}
              inputMode="numeric"
              className="mt-1 w-full rounded-xl border border-line bg-surface-raised px-3 py-2"
            />
          </label>
          <label className="block text-sm sm:col-span-2">
            <span className="text-muted">Website URL</span>
            <input
              value={websiteUrl}
              onChange={(e) => setWebsiteUrl(e.target.value)}
              placeholder="https://example.com"
              type="url"
              className="mt-1 w-full rounded-xl border border-line bg-surface-raised px-3 py-2"
            />
            <span className="mt-1 block text-xs text-muted">
              Optional. For a shared site (e.g. a housing authority), use the
              main domain or the property&apos;s landing page.
            </span>
          </label>
        </div>
        <button
          disabled={creating || !name.trim()}
          className="rounded-xl bg-violet-a px-4 py-2 text-sm font-medium text-background disabled:opacity-50"
        >
          {creating ? "Adding…" : "Add property"}
        </button>
        {createError && (
          <div className="rounded-xl border border-pink-a/40 bg-pink-a/10 p-3 text-sm text-pink-a">
            {createError}
          </div>
        )}
      </form>

      <section>
        <h2 className="mb-3 text-sm font-medium text-muted">Your properties</h2>
        {error && (
          <div className="rounded-xl border border-pink-a/40 bg-pink-a/10 p-3 text-sm text-pink-a">
            {error}
          </div>
        )}
        {loading && <p className="text-sm text-muted">Loading…</p>}
        {!loading && properties.length === 0 && !error && (
          <div className="rounded-2xl border border-line bg-surface p-8 text-center text-sm text-muted">
            No properties yet. Add one above to get started.
          </div>
        )}
        <div className="space-y-5">
          {groups.map((group) => (
            <div key={group.key}>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">
                {group.label}
              </h3>
              <div className="space-y-2">
                {group.items.map((p) =>
                  editingId === p.id ? (
                    <div
                      key={p.id}
                      className="space-y-4 rounded-2xl border border-violet-a/40 bg-surface p-4"
                    >
                      <div className="grid gap-3 sm:grid-cols-2">
                        <label className="block text-sm sm:col-span-2">
                          <span className="text-muted">Property name</span>
                          <input
                            value={draft.name}
                            onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
                            autoFocus
                            className="mt-1 w-full rounded-xl border border-line bg-surface-raised px-3 py-2 text-sm"
                          />
                        </label>
                        <label className="block text-sm sm:col-span-2">
                          <span className="text-muted">Company</span>
                          <select
                            value={draft.companyId}
                            onChange={(e) => setDraft((d) => ({ ...d, companyId: e.target.value }))}
                            className="mt-1 w-full rounded-xl border border-line bg-surface-raised px-3 py-2 text-sm"
                          >
                            <option value="">No company (Unassigned)</option>
                            {companies.map((c) => (
                              <option key={c.id} value={c.id}>
                                {c.name}
                              </option>
                            ))}
                          </select>
                        </label>
                        <label className="block text-sm sm:col-span-2">
                          <span className="text-muted">Property type</span>
                          <select
                            value={draft.propertyType}
                            onChange={(e) => setDraft((d) => ({ ...d, propertyType: e.target.value }))}
                            className="mt-1 w-full rounded-xl border border-line bg-surface-raised px-3 py-2 text-sm"
                          >
                            {Object.entries(types?.types ?? {}).map(([key, info]) => (
                              <option key={key} value={key}>
                                {info.label}
                              </option>
                            ))}
                          </select>
                        </label>
                        <label className="block text-sm">
                          <span className="text-muted">City</span>
                          <input
                            value={draft.city}
                            onChange={(e) => setDraft((d) => ({ ...d, city: e.target.value }))}
                            className="mt-1 w-full rounded-xl border border-line bg-surface-raised px-3 py-2 text-sm"
                          />
                        </label>
                        <label className="block text-sm">
                          <span className="text-muted">State</span>
                          <input
                            value={draft.state}
                            onChange={(e) => setDraft((d) => ({ ...d, state: e.target.value }))}
                            maxLength={2}
                            className="mt-1 w-full rounded-xl border border-line bg-surface-raised px-3 py-2 text-sm"
                          />
                        </label>
                        <label className="block text-sm">
                          <span className="text-muted">{unitLabel(draft.propertyType)}</span>
                          <input
                            value={draft.unitCount}
                            onChange={(e) =>
                              setDraft((d) => ({ ...d, unitCount: e.target.value.replace(/\D/g, "") }))
                            }
                            inputMode="numeric"
                            className="mt-1 w-full rounded-xl border border-line bg-surface-raised px-3 py-2 text-sm"
                          />
                        </label>
                        <label className="block text-sm sm:col-span-2">
                          <span className="text-muted">Website URL</span>
                          <input
                            value={draft.websiteUrl}
                            onChange={(e) => setDraft((d) => ({ ...d, websiteUrl: e.target.value }))}
                            placeholder="https://example.com"
                            type="url"
                            className="mt-1 w-full rounded-xl border border-line bg-surface-raised px-3 py-2 text-sm"
                          />
                        </label>
                      </div>
                      {saveError && (
                        <div className="rounded-xl border border-pink-a/40 bg-pink-a/10 p-2.5 text-xs text-pink-a">
                          {saveError}
                        </div>
                      )}
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => saveEdit(p.id)}
                          disabled={saving}
                          className="rounded-xl bg-violet-a px-4 py-2 text-sm font-medium text-background disabled:opacity-50"
                        >
                          {saving ? "Saving…" : "Save"}
                        </button>
                        <button
                          onClick={() => setEditingId(null)}
                          className="rounded-xl border border-line px-4 py-2 text-sm text-muted hover:text-foreground"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div
                      key={p.id}
                      className="flex items-start justify-between gap-4 rounded-2xl border border-line bg-surface px-4 py-3"
                    >
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <Link href={`/properties/${p.id}`} className="font-medium hover:underline">
                            {p.name}
                          </Link>
                          <span
                            className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${
                              p.property_type === "housing_authority"
                                ? "bg-cyan-a/15 text-cyan-a"
                                : "bg-violet-a/15 text-violet-a"
                            }`}
                          >
                            {typeLabel(p.property_type)}
                          </span>
                        </div>
                        <p className="text-xs text-muted">
                          {[p.city, p.state].filter(Boolean).join(", ") || "No location set"}
                          {p.unit_count
                            ? ` · ${p.unit_count} ${types?.types[p.property_type]?.terminology?.unit_plural ?? "units"}`
                            : ""}
                        </p>
                        {p.website_url ? (
                          <a
                            href={p.website_url}
                            target="_blank"
                            rel="noreferrer"
                            className="mt-1 block truncate text-xs text-cyan-a hover:underline"
                          >
                            {p.website_url}
                          </a>
                        ) : (
                          <p className="mt-1 text-xs text-muted italic">No website URL set</p>
                        )}
                      </div>
                      <div className="flex shrink-0 items-center gap-2">
                        <button
                          onClick={() => startEdit(p)}
                          className="rounded-lg border border-line px-3 py-1.5 text-sm text-muted hover:border-violet-a/40 hover:text-violet-a"
                        >
                          Edit
                        </button>
                        {confirmDeleteId === p.id ? (
                          <div className="flex items-center gap-2 text-sm">
                            <span className="text-pink-a">Delete permanently?</span>
                            <button
                              onClick={() => deleteProperty(p.id)}
                              disabled={deleting}
                              className="rounded-lg bg-pink-a px-3 py-1.5 font-medium text-background disabled:opacity-50"
                            >
                              {deleting ? "Deleting…" : "Confirm"}
                            </button>
                            <button
                              onClick={() => setConfirmDeleteId(null)}
                              className="rounded-lg border border-line px-3 py-1.5 text-muted"
                            >
                              Cancel
                            </button>
                          </div>
                        ) : (
                          <button
                            onClick={() => setConfirmDeleteId(p.id)}
                            className="rounded-lg border border-line px-3 py-1.5 text-sm text-muted hover:border-pink-a/40 hover:text-pink-a"
                          >
                            Delete
                          </button>
                        )}
                      </div>
                    </div>
                  )
                )}
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
