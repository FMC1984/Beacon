"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Suspense } from "react";
import { ScopeSelect } from "@/components/ScopeSelect";
import { ErrorState } from "@/components/reports/DataStates";
import {
  ObservatoryProvider,
  useObservatory,
  type ObsDays,
} from "@/components/observatory/ObservatoryContext";

const TABS: { href: string; label: string }[] = [
  { href: "/ai-visibility", label: "Overview" },
  { href: "/ai-visibility/prompts", label: "Prompts" },
  { href: "/ai-visibility/citations", label: "Citations" },
  { href: "/ai-visibility/competitors", label: "Competitors" },
  { href: "/ai-visibility/sources", label: "Sources" },
  { href: "/ai-visibility/markets", label: "Markets" },
  { href: "/ai-visibility/recommendations", label: "Recommendations" },
  { href: "/ai-visibility/accuracy", label: "Accuracy" },
  { href: "/ai-visibility/trends", label: "Trends" },
  { href: "/ai-visibility/portfolio", label: "Portfolio" },
];

function ObservatoryShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { companies, properties, propertyId, setPropertyId, days, setDays, loaded, loadError, reload, withScope } =
    useObservatory();

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">AI Visibility</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted">
            How AI answers mention, cite and recommend each property, measured from
            Beacon&apos;s own monitoring runs. Monitoring runs are not consumer
            impressions, and Beacon never reports AI search volume.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <ScopeSelect companies={companies} properties={properties} value={propertyId} onChange={setPropertyId} />
          <div role="group" aria-label="Date range" className="flex rounded-xl border border-line bg-surface p-0.5">
            {([7, 30, 90] as ObsDays[]).map((d) => (
              <button
                key={d}
                onClick={() => setDays(d)}
                aria-pressed={days === d}
                className={`rounded-lg px-3 py-1.5 text-sm transition-colors ${
                  days === d ? "bg-violet-a font-medium text-background" : "text-muted hover:text-foreground"
                }`}
              >
                {d}d
              </button>
            ))}
          </div>
        </div>
      </div>

      <nav aria-label="AI Visibility tabs" className="flex gap-1 overflow-x-auto border-b border-line">
        {TABS.map((tab) => {
          const active = pathname === tab.href;
          return (
            <Link
              key={tab.href}
              href={withScope(tab.href)}
              aria-current={active ? "page" : undefined}
              className={`-mb-px shrink-0 rounded-t-lg border-b-2 px-3.5 py-2 text-sm transition-colors ${
                active ? "border-violet-a font-medium text-foreground" : "border-transparent text-muted hover:text-foreground"
              }`}
            >
              {tab.label}
            </Link>
          );
        })}
      </nav>

      {loadError ? (
        <ErrorState message={loadError} onRetry={reload} />
      ) : !loaded ? (
        <p className="text-sm text-muted">Loading...</p>
      ) : (
        children
      )}
    </div>
  );
}

export default function AIVisibilityLayout({ children }: { children: React.ReactNode }) {
  return (
    <Suspense fallback={<p className="text-sm text-muted">Loading...</p>}>
      <ObservatoryProvider>
        <ObservatoryShell>{children}</ObservatoryShell>
      </ObservatoryProvider>
    </Suspense>
  );
}
