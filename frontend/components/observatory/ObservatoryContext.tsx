"use client";

/** Shared state for the AI Visibility Observatory tabs: the selected property
 * (kept in the URL as ?property_id so tab links and dashboard links land on
 * the same property), the date range, and the metric definitions from
 * /ai-observatory/meta. */

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { Company, Property, fetchCompanies, fetchProperties } from "@/lib/api";
import { fetchObservatoryMeta, type ObservatoryMeta } from "@/lib/observatory";

export type ObsDays = 7 | 30 | 90;

const PROPERTY_KEY = "beacon.observatory.property";

type Ctx = {
  companies: Company[];
  properties: Property[];
  property: Property | null;
  /** True when the selected property belongs to the labeled Sample Portfolio. */
  isSample: boolean;
  propertyId: number | null;
  setPropertyId: (id: number | null) => void;
  days: ObsDays;
  setDays: (d: ObsDays) => void;
  meta: ObservatoryMeta | null;
  loaded: boolean;
  loadError: string | null;
  reload: () => void;
  /** Appends the current property to an Observatory href. */
  withScope: (href: string) => string;
};

const ObservatoryCtx = createContext<Ctx | null>(null);

export function ObservatoryProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const search = useSearchParams();
  const [companies, setCompanies] = useState<Company[]>([]);
  const [properties, setProperties] = useState<Property[]>([]);
  const [meta, setMeta] = useState<ObservatoryMeta | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [days, setDays] = useState<ObsDays>(30);

  const urlId = Number(search.get("property_id"));
  const propertyId = Number.isInteger(urlId) && urlId > 0 ? urlId : null;

  const setPropertyId = useCallback(
    (id: number | null) => {
      const params = new URLSearchParams(search.toString());
      if (id === null) params.delete("property_id");
      else params.set("property_id", String(id));
      try {
        if (id !== null) localStorage.setItem(PROPERTY_KEY, String(id));
      } catch {}
      router.replace(`${pathname}${params.toString() ? `?${params}` : ""}`);
    },
    [pathname, router, search]
  );

  const [attempt, setAttempt] = useState(0);
  const reload = useCallback(() => {
    setLoadError(null);
    setAttempt((a) => a + 1);
  }, []);

  useEffect(() => {
    let cancelled = false;
    Promise.all([fetchCompanies(), fetchProperties()])
      .then(([cs, ps]) => {
        if (cancelled) return;
        setCompanies(cs);
        setProperties(ps);
        setLoaded(true);
      })
      .catch(() => !cancelled && setLoadError("Could not reach the Beacon API."));
    fetchObservatoryMeta()
      .then((m) => !cancelled && setMeta(m))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  // Default to the last property viewed, else the first property. A URL id
  // that no longer exists (a bookmark, or a Sample Portfolio rebuild that
  // renumbered the properties) falls back the same way instead of leaving
  // every tab querying a deleted property.
  useEffect(() => {
    if (!loaded || properties.length === 0) return;
    if (propertyId !== null && properties.some((p) => p.id === propertyId)) return;
    let saved: number | null = null;
    try {
      const raw = Number(localStorage.getItem(PROPERTY_KEY));
      if (properties.some((p) => p.id === raw)) saved = raw;
    } catch {}
    setPropertyId(saved ?? properties[0].id);
  }, [loaded, propertyId, properties, setPropertyId]);

  const property = useMemo(
    () => properties.find((p) => p.id === propertyId) ?? null,
    [properties, propertyId]
  );

  const withScope = useCallback(
    (href: string) => (propertyId === null ? href : `${href}?property_id=${propertyId}`),
    [propertyId]
  );

  return (
    <ObservatoryCtx.Provider
      value={{
        companies,
        properties,
        property,
        isSample: property?.attributes?.sample_data === true,
        propertyId,
        setPropertyId,
        days,
        setDays,
        meta,
        loaded,
        loadError,
        reload,
        withScope,
      }}
    >
      {children}
    </ObservatoryCtx.Provider>
  );
}

export function useObservatory() {
  const ctx = useContext(ObservatoryCtx);
  if (!ctx) throw new Error("useObservatory must be used inside ObservatoryProvider");
  return ctx;
}
