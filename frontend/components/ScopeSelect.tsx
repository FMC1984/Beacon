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

  const filtered = inScope(companyScope);
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
    if (value === null || !next.some((p) => p.id === value)) {
      onChange(allowAll ? null : next[0]?.id ?? null);
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
        value={companyScope === "" ? "" : String(companyScope)}
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
