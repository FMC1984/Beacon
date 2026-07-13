"use client";

/** Placeholder body for a report tab (Phase 16A). Each tab's real content
 * replaces this in its own build phase; the Executive tab additionally shows
 * the live data-source status panel so the section is useful on day one. */

import { PlannedReport, SourceStatusPanel } from "./PlannedReport";
import { useReportContext } from "./ReportContext";

export function ReportTabPage({ tabKey }: { tabKey: string }) {
  const { tabs } = useReportContext();
  const tab = tabs.find((t) => t.key === tabKey);
  if (!tab) return null;
  return (
    <div className="space-y-6">
      <PlannedReport tab={tab} />
      {tabKey === "executive" && <SourceStatusPanel />}
    </div>
  );
}
