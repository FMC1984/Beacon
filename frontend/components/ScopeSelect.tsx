"use client";

import { useEffect, useRef, useState } from "react";
import { Company, Property, SCOPE_STORAGE_KEY } from "@/lib/api";

type CompanyScope = "" | "unassigned" | number;

/**
 * Two linked dropdowns: pick a Company, then a Property within it. The company
 * filter narrows the property list; "All companies" shows every property.
 * Reports only the selected property id (null = the optional "all" option).
 */
export function ScopeSelect({
  companies,
  properties,
  value,
  onChange,
  allowAll = false,
  allLabel = "All properties",
}: {
  companies: Company[];
  properties: Property[];
  value: number | null;
  onChange: (propertyId: number | null) => void;
  allowAll?: boolean;
  allLabel?: string;
}) {
  const [companyScope, setCompanyScope] = useState<CompanyScope>("");

  const inScope = (scope: CompanyScope) =>
    properties.filter((p) =>
      scope === ""
        ? true
        : scope === "unassigned"
        ? p.company_id === null
        : p.company_id === scope
    );

  const scopeOf = (id: number | null): CompanyScope | null => {
    const p = id === null ? undefined : properties.find((x) => x.id === id);
    if (!p) return null;
    return p.company_id === null ? "unassigned" : p.company_id;
  };

  // The selected property always wins over a remembered company: if a link or
  // another page selected a property outside the current company, show that
  // property's company instead of hiding the property (or switching away
  // from it). Derived, so there is no render where the two disagree.
  const valueScope = scopeOf(value);
  const effectiveScope: CompanyScope =
    valueScope !== null && !inScope(companyScope).some((p) => p.id === value) ? valueScope : companyScope;
  const filtered = inScope(effectiveScope);
  const hasUnassigned = properties.some((p) => p.company_id === null);

  // Restore the shared company scope once properties are loaded (so a remembered
  // company carries over from the dashboard / other pages).
  const restored = useRef(false);
  useEffect(() => {
    if (restored.current || properties.length === 0) return;
    restored.current = true;
    let saved: string | null = null;
    try {
      saved = localStorage.getItem(SCOPE_STORAGE_KEY);
    } catch {}
    if (!saved || saved === "all") return; // "" (all companies) is the default
    const scope: CompanyScope = saved === "unassigned" ? "unassigned" : Number(saved);
    setCompanyScope(scope);
    const next = inScope(scope);
    // Only fill an empty selection from the remembered company. A property
    // that is already selected (from the URL or a link) is kept; the company
    // dropdown follows it via effectiveScope.
    if (value === null && !allowAll) {
      onChange(next[0]?.id ?? null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [properties]);

  function changeCompany(raw: string) {
    const scope: CompanyScope =
      raw === "" || raw === "unassigned" ? (raw as CompanyScope) : Number(raw);
    setCompanyScope(scope);
    try {
      localStorage.setItem(
        SCOPE_STORAGE_KEY,
        scope === "" ? "all" : String(scope)
      );
    } catch {}
    const next = inScope(scope);
    // If the current property fell out of the new scope, re-point it.
    if (value === null || !next.some((p) => p.id === value)) {
      onChange(allowAll ? null : next[0]?.id ?? null);
    }
  }

  return (
    <div className="flex items-center gap-2">
      <select
        aria-label="Company"
        className="rounded-xl border border-line bg-surface px-3 py-2 text-sm"
        value={effectiveScope === "" ? "" : String(effectiveScope)}
        onChange={(e) => changeCompany(e.target.value)}
      >
        <option value="">All companies</option>
        {companies.map((c) => (
          <option key={c.id} value={c.id}>
            {c.name}
          </option>
        ))}
        {hasUnassigned && <option value="unassigned">Unassigned</option>}
      </select>
      <select
        aria-label="Property"
        className="rounded-xl border border-line bg-surface px-3 py-2 text-sm"
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}
      >
        {allowAll && <option value="">{allLabel}</option>}
        {filtered.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}
            {p.attributes?.sample_data === true ? " (sample)" : ""}
          </option>
        ))}
        {!allowAll && filtered.length === 0 && (
          <option value="" disabled>
            No properties
          </option>
        )}
      </select>
    </div>
  );
}
