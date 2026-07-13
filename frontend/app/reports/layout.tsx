"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ErrorState } from "@/components/reports/DataStates";
import { ReportControls } from "@/components/reports/ReportControls";
import {
  ReportProvider,
  useReportContext,
} from "@/components/reports/ReportContext";

function ReportsShell({ children }: { children: React.ReactNode }) {
  const { tabs, loaded, loadError, reload } = useReportContext();
  const pathname = usePathname();

  // The print route is a standalone, self-contained layout: no control bar,
  // no tabs. It reads its own scope from the URL.
  if (pathname.endsWith("/print")) return <>{children}</>;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Reports</h1>
        <p className="mt-1 text-sm text-muted">
          The communication layer over Beacon&apos;s analysis modules. Every
          figure names its source, sample, and freshness.
        </p>
      </div>

      {loadError ? (
        <ErrorState message={loadError} onRetry={reload} />
      ) : !loaded ? (
        <p className="text-sm text-muted">Loading reports...</p>
      ) : (
        <>
          <ReportControls />

          <nav aria-label="Report tabs" className="flex flex-wrap gap-1 border-b border-line">
            {tabs.map((tab) => {
              const href = `/reports/${tab.key}`;
              const active = pathname === href;
              return (
                <Link
                  key={tab.key}
                  href={href}
                  aria-current={active ? "page" : undefined}
                  className={`-mb-px rounded-t-lg border-b-2 px-3.5 py-2 text-sm transition-colors ${
                    active
                      ? "border-violet-a font-medium text-foreground"
                      : "border-transparent text-muted hover:text-foreground"
                  }`}
                >
                  {tab.label}
                </Link>
              );
            })}
          </nav>

          {children}
        </>
      )}
    </div>
  );
}

export default function ReportsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <ReportProvider>
      <ReportsShell>{children}</ReportsShell>
    </ReportProvider>
  );
}
