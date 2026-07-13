"use client";

/** Shared report control bar (Phase 16A): company/property scope (synced with
 * the global ScopeSelect), 7/30/90-day range, previous-period comparison
 * toggle, export menu placeholder, and a live data-freshness indicator. */

import { useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { ScopeSelect } from "@/components/ScopeSelect";
import { fetchReportStatus, type ReportStatus } from "@/lib/reports";
import { fmtDate } from "@/lib/format";
import { STATE_META, StateBadge } from "./DataStates";
import { ExportMenu } from "./ExportMenu";
import { useReportContext, type RangeDays } from "./ReportContext";

// Which report section the Export menu should target, from the route.
function sectionFromPath(
  pathname: string
): "seo" | "executive" | "geo" | "aeo" | "content-impact" | null {
  if (pathname.startsWith("/reports/seo")) return "seo";
  if (pathname.startsWith("/reports/executive")) return "executive";
  if (pathname.startsWith("/reports/geo")) return "geo";
  if (pathname.startsWith("/reports/aeo")) return "aeo";
  if (pathname.startsWith("/reports/content-impact")) return "content-impact";
  return null;
}

const RANGES: RangeDays[] = [7, 30, 90];

export function ReportControls() {
  const {
    companies,
    properties,
    propertyId,
    setPropertyId,
    days,
    setDays,
    compare,
    setCompare,
    scope,
  } = useReportContext();

  const [status, setStatus] = useState<ReportStatus | null>(null);
  const [statusError, setStatusError] = useState(false);
  const [open, setOpen] = useState(false);
  const popRef = useRef<HTMLDivElement>(null);
  const pathname = usePathname();
  const section = sectionFromPath(pathname);

  function openPrint() {
    if (section !== "executive") return;
    const params = new URLSearchParams();
    if (scope.propertyId !== null) params.set("property_id", String(scope.propertyId));
    params.set("days", String(days));
    params.set("compare", String(compare));
    window.open(`/reports/executive/print?${params}`, "_blank");
  }

  useEffect(() => {
    let cancelled = false;
    setStatus(null);
    setStatusError(false);
    fetchReportStatus(scope)
      .then((s) => {
        if (!cancelled) setStatus(s);
      })
      .catch(() => {
        if (!cancelled) setStatusError(true);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope.propertyId, scope.companyId, scope.unassigned]);

  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      if (popRef.current && !popRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  const worstTone = status ? STATE_META[status.worst_state].tone : null;
  const dotClass =
    worstTone === "ok"
      ? "bg-emerald-a"
      : worstTone === "warn"
      ? "bg-amber-a"
      : worstTone === "bad"
      ? "bg-pink-a"
      : "bg-muted";

  return (
    <div className="flex flex-wrap items-center gap-3">
      <ScopeSelect
        companies={companies}
        properties={properties}
        value={propertyId}
        onChange={setPropertyId}
        allowAll
      />

      <div
        role="group"
        aria-label="Date range"
        className="flex items-center rounded-xl border border-line bg-surface p-1"
      >
        {RANGES.map((r) => (
          <button
            key={r}
            onClick={() => setDays(r)}
            aria-pressed={days === r}
            className={`rounded-lg px-3 py-1 text-sm transition-colors ${
              days === r
                ? "bg-surface-raised font-medium text-foreground"
                : "text-muted hover:text-foreground"
            }`}
          >
            {r}d
          </button>
        ))}
      </div>

      <button
        onClick={() => setCompare(!compare)}
        aria-pressed={compare}
        className={`rounded-xl border px-3 py-2 text-sm transition-colors ${
          compare
            ? "border-violet-a/50 bg-violet-a/15 text-foreground"
            : "border-line bg-surface text-muted hover:text-foreground"
        }`}
      >
        Compare to previous period
      </button>

      <div className="ml-auto flex items-center gap-2">
        <div className="relative" ref={popRef}>
          <button
            onClick={() => setOpen((o) => !o)}
            aria-expanded={open}
            aria-label="Data status"
            className="flex items-center gap-2 rounded-xl border border-line bg-surface px-3 py-2 text-sm text-muted transition-colors hover:text-foreground"
          >
            <span aria-hidden className={`h-2 w-2 rounded-full ${dotClass}`} />
            {statusError ? "Status unavailable" : "Data status"}
          </button>
          {open && status && (
            <div className="absolute right-0 z-20 mt-2 w-80 rounded-2xl border border-line bg-surface p-4 shadow-xl">
              <p className="mb-2 text-xs text-muted">
                Checked {fmtDate(status.checked_date)}
              </p>
              <ul className="space-y-2.5">
                {status.sources.map((s) => (
                  <li key={s.key} className="text-sm">
                    <div className="flex items-center justify-between gap-2">
                      <span>{s.label}</span>
                      <StateBadge state={s.state} />
                    </div>
                    <p className="mt-0.5 text-xs text-muted">{s.detail}</p>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        <ExportMenu
          section={section}
          scope={scope}
          days={days}
          compare={compare}
          onPrint={section === "executive" ? openPrint : undefined}
        />
      </div>
    </div>
  );
}
