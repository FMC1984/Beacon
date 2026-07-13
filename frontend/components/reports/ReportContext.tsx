"use client";

/** Shared state for the Reports section: scope (kept in sync with Beacon's
 * global company scope via ScopeSelect/SCOPE_STORAGE_KEY), date range, and
 * the previous-period comparison toggle. */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import {
  Company,
  Property,
  SCOPE_STORAGE_KEY,
  fetchCompanies,
  fetchProperties,
} from "@/lib/api";
import { fetchReportMeta, type ReportScope, type ReportTab } from "@/lib/reports";

export type RangeDays = 7 | 30 | 90;

type ReportContextValue = {
  companies: Company[];
  properties: Property[];
  tabs: ReportTab[];
  loaded: boolean;
  loadError: string | null;
  reload: () => void;
  propertyId: number | null;
  setPropertyId: (id: number | null) => void;
  days: RangeDays;
  setDays: (d: RangeDays) => void;
  compare: boolean;
  setCompare: (c: boolean) => void;
  scope: ReportScope;
};

const ReportContext = createContext<ReportContextValue | null>(null);

/** Company scope persisted by ScopeSelect: "all" | "unassigned" | "<id>". */
function readCompanyScope(): { companyId: number | null; unassigned: boolean } {
  try {
    const saved = localStorage.getItem(SCOPE_STORAGE_KEY);
    if (saved && saved !== "all") {
      if (saved === "unassigned") return { companyId: null, unassigned: true };
      if (/^\d+$/.test(saved)) return { companyId: Number(saved), unassigned: false };
    }
  } catch {}
  return { companyId: null, unassigned: false };
}

export function ReportProvider({ children }: { children: ReactNode }) {
  const [companies, setCompanies] = useState<Company[]>([]);
  const [properties, setProperties] = useState<Property[]>([]);
  const [tabs, setTabs] = useState<ReportTab[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [propertyId, setPropertyIdState] = useState<number | null>(null);
  const [days, setDays] = useState<RangeDays>(30);
  const [compare, setCompare] = useState(false);
  // Bumped whenever the property (and therefore possibly the persisted
  // company scope) changes, so `scope` re-reads localStorage.
  const [scopeVersion, setScopeVersion] = useState(0);

  const reload = useCallback(() => {
    setLoadError(null);
    Promise.all([fetchCompanies(), fetchProperties(), fetchReportMeta()])
      .then(([cs, ps, meta]) => {
        setCompanies(cs);
        setProperties(ps);
        setTabs(meta.tabs);
        setLoaded(true);
      })
      .catch((e) => setLoadError(e instanceof Error ? e.message : String(e)));
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  const setPropertyId = useCallback((id: number | null) => {
    setPropertyIdState(id);
    setScopeVersion((v) => v + 1);
  }, []);

  const company = readCompanyScopeSafe(scopeVersion, loaded);
  const scope: ReportScope =
    propertyId !== null
      ? { propertyId, companyId: null, unassigned: false }
      : { propertyId: null, ...company };

  return (
    <ReportContext.Provider
      value={{
        companies,
        properties,
        tabs,
        loaded,
        loadError,
        reload,
        propertyId,
        setPropertyId,
        days,
        setDays,
        compare,
        setCompare,
        scope,
      }}
    >
      {children}
    </ReportContext.Provider>
  );
}

// localStorage is unavailable during SSR; only read it after data loads on
// the client. scopeVersion is a dependency purely to force the re-read after
// ScopeSelect writes a new company scope.
function readCompanyScopeSafe(scopeVersion: number, loaded: boolean) {
  void scopeVersion;
  if (typeof window === "undefined" || !loaded) {
    return { companyId: null, unassigned: false };
  }
  return readCompanyScope();
}

export function useReportContext(): ReportContextValue {
  const ctx = useContext(ReportContext);
  if (!ctx) throw new Error("useReportContext must be used inside ReportProvider");
  return ctx;
}
