"use client";

/** Export menu shell (Phase 16C): CSV download of the active report section
 * and a print action (the print layout is the PDF path for now). Disabled
 * with an explanation when the current section has no export yet. */

import { useEffect, useRef, useState } from "react";
import { reportCsvUrl, type ReportScope } from "@/lib/reports";
import type { RangeDays } from "./ReportContext";

export function ExportMenu({
  section,
  scope,
  days,
  compare,
  onPrint,
}: {
  section: "seo" | "executive" | "geo" | "aeo" | "content-impact" | null;
  scope: ReportScope;
  days: RangeDays;
  compare: boolean;
  onPrint?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  const disabled = section === null;
  const csvHref = section ? reportCsvUrl(section, scope, days, compare) : "#";

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => !disabled && setOpen((o) => !o)}
        disabled={disabled}
        aria-expanded={open}
        title={disabled ? "This report has no export yet" : "Export"}
        className={`rounded-xl border border-line bg-surface px-3 py-2 text-sm transition-colors ${
          disabled
            ? "cursor-not-allowed text-muted/60"
            : "text-muted hover:text-foreground"
        }`}
      >
        Export
      </button>
      {open && !disabled && (
        <div className="absolute right-0 z-20 mt-2 w-56 rounded-2xl border border-line bg-surface p-2 shadow-xl">
          <a
            href={csvHref}
            className="block rounded-lg px-3 py-2 text-sm text-foreground transition-colors hover:bg-surface-raised"
            onClick={() => setOpen(false)}
          >
            Download CSV
            <span className="mt-0.5 block text-xs text-muted">
              Underlying metrics with definitions and sources
            </span>
          </a>
          {onPrint && (
            <button
              onClick={() => {
                setOpen(false);
                onPrint();
              }}
              className="block w-full rounded-lg px-3 py-2 text-left text-sm text-foreground transition-colors hover:bg-surface-raised"
            >
              Print / Save as PDF
              <span className="mt-0.5 block text-xs text-muted">
                Opens the print-friendly layout
              </span>
            </button>
          )}
        </div>
      )}
    </div>
  );
}
