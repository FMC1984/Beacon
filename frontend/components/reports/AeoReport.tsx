"use client";

/** AEO Readiness report (Phase 16E). An explainable score built from
 * deterministic components (each shows its weight, rule, raw value, and
 * evidence), a question-by-page coverage heatmap, citation-readiness signals
 * with the fixed no-guarantee disclaimer, and an honest structured-data empty
 * state. No opaque model score, no vector similarity deciding cells. */

import { useEffect, useState } from "react";
import { fmtDate } from "@/lib/format";
import {
  fetchAeoReport,
  type AeoComponent,
  type AeoHeatmapCell,
  type AeoReport as AeoReportData,
} from "@/lib/reports";
import { EmptyState, ErrorState, StateBadge } from "./DataStates";
import { useReportContext } from "./ReportContext";

const CELL_META: Record<string, { glyph: string; label: string; cls: string }> = {
  fully_answered: { glyph: "●", label: "Fully answered", cls: "bg-emerald-a/30 text-emerald-a" },
  partially_answered: { glyph: "◐", label: "Partially answered", cls: "bg-amber-a/25 text-amber-a" },
  mentioned_only: { glyph: "○", label: "Mentioned only", cls: "bg-cyan-a/15 text-cyan-a" },
  missing: { glyph: "·", label: "Missing", cls: "bg-surface-raised text-muted/50" },
};

function Section({ title, sub, children }: { title: string; sub?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl border border-line bg-surface p-5">
      <h3 className="text-sm font-medium">{title}</h3>
      {sub && <p className="mt-0.5 text-xs text-muted">{sub}</p>}
      <div className="mt-4">{children}</div>
    </section>
  );
}

function ScoreDial({ value, grade }: { value: number | null; grade: string | null }) {
  return (
    <div className="flex items-center gap-4">
      <div className="flex h-20 w-20 shrink-0 flex-col items-center justify-center rounded-full border-2 border-violet-a/50 bg-violet-a/10">
        <span className="text-2xl font-semibold text-foreground">{value ?? "n/a"}</span>
        {grade && <span className="text-xs text-violet-a">Grade {grade}</span>}
      </div>
    </div>
  );
}

function ComponentRow({ c }: { c: AeoComponent }) {
  const [open, setOpen] = useState(false);
  return (
    <li className="border-b border-line/50 py-2.5">
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center gap-3 text-left text-sm"
      >
        <span className="w-44 shrink-0">{c.label}</span>
        <div className="h-2 flex-1 rounded bg-surface-raised">
          {!c.excluded && c.raw_value !== null && (
            <div
              className="h-2 rounded bg-violet-a/70"
              style={{ width: `${c.raw_value}%` }}
              role="img"
              aria-label={`${c.label}: ${c.raw_value} of 100`}
            />
          )}
        </div>
        <span className="w-16 text-right text-xs">
          {c.excluded ? <span className="text-muted">excluded</span> : `${c.raw_value}`}
        </span>
        <span className="w-14 text-right text-xs text-muted">
          {Math.round(c.weight * 100)}% wt
        </span>
      </button>
      {open && (
        <div className="mt-2 space-y-1 pl-44 text-xs text-muted">
          <p><span className="text-foreground/70">Rule:</span> {c.rule}</p>
          <p>{c.excluded ? c.excluded_reason : c.explanation}</p>
          {c.evidence.length > 0 && <p>Evidence: {c.evidence.join(", ")}</p>}
          {c.source_pages.length > 0 && <p>Pages: {c.source_pages.join(", ")}</p>}
        </div>
      )}
    </li>
  );
}

function Heatmap({ report }: { report: Extract<AeoReportData, { has_content: true }> }) {
  const hm = report.heatmap;
  const [selected, setSelected] = useState<{ q: string; cell: AeoHeatmapCell } | null>(null);
  const usedStates = new Set(hm.rows.flatMap((r) => r.cells.map((c) => c.state)));
  return (
    <div>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr>
              <th className="sticky left-0 bg-surface py-2 pr-3 text-left text-xs font-medium text-muted">
                Question
              </th>
              {hm.pages.map((p) => (
                <th key={p} className="px-2 py-2 text-center text-xs font-medium text-muted">
                  {p}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {hm.rows.map((row) => (
              <tr key={row.id} className="border-t border-line/50">
                <td className="sticky left-0 max-w-[24rem] truncate bg-surface py-1.5 pr-3" title={row.question}>
                  <span className={row.importance === "high" ? "font-medium" : ""}>{row.question}</span>
                </td>
                {row.cells.map((cell, i) => {
                  const meta = CELL_META[cell.state];
                  return (
                    <td key={i} className="px-2 py-1 text-center">
                      <button
                        onClick={() => setSelected({ q: row.question, cell })}
                        aria-label={`${meta.label}${cell.stale ? ", stale" : ""} on ${cell.page}`}
                        title={`${meta.label}${cell.stale ? " (stale)" : ""}`}
                        className={`relative inline-flex h-7 w-7 items-center justify-center rounded ${meta.cls} hover:ring-2 hover:ring-violet-a/50`}
                      >
                        {meta.glyph}
                        {cell.stale && (
                          <span className="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full bg-pink-a" aria-hidden />
                        )}
                      </button>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-3 flex flex-wrap gap-3 text-xs text-muted">
        {[...usedStates].map((st) => {
          const meta = CELL_META[st];
          return (
            <span key={st} className="inline-flex items-center gap-1.5">
              <span className={`inline-flex h-5 w-5 items-center justify-center rounded ${meta.cls}`}>
                {meta.glyph}
              </span>
              {meta.label}
            </span>
          );
        })}
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full bg-pink-a" /> Stale page
        </span>
      </div>
      {selected && (
        <div className="mt-3 rounded-xl border border-line bg-surface-raised p-4 text-sm">
          <div className="flex items-start justify-between gap-2">
            <p className="font-medium">{selected.q}</p>
            <button onClick={() => setSelected(null)} aria-label="Close" className="text-muted hover:text-foreground">✕</button>
          </div>
          <p className="mt-1 text-xs text-muted">
            {CELL_META[selected.cell.state].label} on {selected.cell.page}
            {selected.cell.stale && " (page flagged stale)"}
          </p>
          {selected.cell.matched_terms.length > 0 ? (
            <p className="mt-1 text-xs text-muted">Matched terms: {selected.cell.matched_terms.join(", ")}</p>
          ) : (
            <p className="mt-1 text-xs text-muted">No matching terms on this page.</p>
          )}
        </div>
      )}
    </div>
  );
}

export function AeoReport() {
  const { scope } = useReportContext();
  const [data, setData] = useState<AeoReportData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    fetchAeoReport(scope.propertyId)
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope.propertyId, attempt]);

  if (error) return <ErrorState message={error} onRetry={() => setAttempt((a) => a + 1)} />;
  if (!data) return <p className="text-sm text-muted">Loading AEO report...</p>;
  if (data.scope_required) return <EmptyState title="Select a property" body={data.message} />;
  if (!data.has_content) {
    return (
      <div className="space-y-4">
        <EmptyState title="No content ingested" body={data.message} />
        <StructuredData sd={data.structured_data} />
      </div>
    );
  }

  const cov = data.question_coverage_summary;
  return (
    <div className="space-y-6">
      <Section title="AEO Readiness score" sub={data.score.note}>
        <div className="flex flex-col gap-5 lg:flex-row lg:items-start">
          <ScoreDial value={data.score.value} grade={data.score.grade} />
          <ul className="flex-1">
            {data.score.components.map((c) => (
              <ComponentRow key={c.key} c={c} />
            ))}
          </ul>
        </div>
      </Section>

      <Section
        title="Question coverage heatmap"
        sub={`${cov.answered} answered, ${cov.partial} partial, ${cov.missing} missing of ${cov.total} important questions. Click a cell for evidence.`}
      >
        <Heatmap report={data} />
      </Section>

      <Section title="Citation readiness" sub={data.citation_readiness.disclaimer}>
        <div className="space-y-3">
          <p className="text-2xl font-semibold">{data.citation_readiness.value ?? "n/a"}<span className="text-sm text-muted"> / 100</span></p>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-line text-left text-xs text-muted">
                  <th className="py-2 pr-3 font-medium">Page</th>
                  <th className="py-2 pr-3 font-medium">Heading</th>
                  <th className="py-2 pr-3 font-medium">Specific answer</th>
                  <th className="py-2 pr-3 font-medium">Named</th>
                  <th className="py-2 pr-3 font-medium">Updated date</th>
                  <th className="py-2 font-medium">Crawlable</th>
                </tr>
              </thead>
              <tbody>
                {data.citation_readiness.pages.map((p) => (
                  <tr key={p.page} className="border-b border-line/50">
                    <td className="py-2 pr-3">{p.page}</td>
                    {["clear_heading", "specific_answer_present", "named_property", "updated_date", "crawlable_text"].map((k) => (
                      <td key={k} className="py-2 pr-3">
                        {p.signals[k] ? <span className="text-emerald-a">yes</span> : <span className="text-muted">no</span>}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </Section>

      <Section title="Structured data" sub="Schema.org markup detected in the property's pages.">
        <StructuredData sd={data.structured_data} />
      </Section>
    </div>
  );
}

function StructuredData({ sd }: { sd: { state: string; enabled: boolean; message: string } }) {
  return (
    <div className="flex items-start gap-3 rounded-xl border border-dashed border-line p-4">
      <StateBadge state={sd.state as never} />
      <p className="text-sm text-muted">{sd.message}</p>
    </div>
  );
}
