"use client";

/** GEO / AI Visibility report (Phase 16D). Tested AI answers, referral
 * sessions, mentions, and citations are shown as distinct metrics. Rates
 * always carry their sample; below the minimum they read "insufficient
 * sample", never a fake 0. Competitor comparison is labeled share of tested
 * answers, never market share. */

import { useEffect, useState } from "react";
import { fmtDate, fmtNum, fmtPct } from "@/lib/format";
import {
  fetchGeoEvidence,
  fetchGeoReport,
  type GeoEvidence,
  type GeoReport as GeoReportData,
  type MatrixCell,
} from "@/lib/reports";
import { EmptyState, ErrorState, StateBadge } from "./DataStates";
import { ReportMetricCard } from "./ReportMetricCard";
import { useReportContext } from "./ReportContext";

// Matrix cell appearance. Color is never the only signal: each cell shows a
// short glyph and every state is named in the legend and the aria-label.
const CELL_META: Record<string, { glyph: string; label: string; cls: string }> = {
  property_cited: { glyph: "★", label: "Property cited", cls: "bg-emerald-a/25 text-emerald-a" },
  property_mentioned: { glyph: "●", label: "Property mentioned", cls: "bg-cyan-a/20 text-cyan-a" },
  property_and_competitor: { glyph: "◑", label: "Property and competitor", cls: "bg-violet-a/20 text-violet-a" },
  competitor_mentioned: { glyph: "▲", label: "Competitor only", cls: "bg-amber-a/20 text-amber-a" },
  not_present: { glyph: "·", label: "Not present", cls: "bg-surface-raised text-muted" },
  not_tested: { glyph: "–", label: "Not tested", cls: "border border-dashed border-line text-muted/60" },
};

const CATEGORY_CLS: Record<string, string> = {
  owned: "bg-emerald-a/70",
  competitor: "bg-amber-a/70",
  government: "bg-cyan-a/70",
  directory: "bg-violet-a/70",
  review_platform: "bg-pink-a/70",
  media: "bg-cyan-a/40",
  unknown: "bg-muted/40",
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

function SummaryCards({ report }: { report: Extract<GeoReportData, { has_queries: true }> }) {
  const s = report.summary;
  const last = s.last_run;
  const rateCard = (
    label: string,
    r: typeof s.mention_rate,
    unit: string
  ) => (
    <ReportMetricCard
      label={label}
      state={r.state}
      stateDetail={`${r.numerator} of ${r.denominator} ${unit}; below the ${r.minimum_sample}-query minimum.`}
      value={r.value !== null ? fmtPct(r.value) : undefined}
      source="AI Visibility"
      lastDataDate={last}
      sample={{ numerator: r.numerator, denominator: r.denominator, unit }}
    />
  );
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <ReportMetricCard label="Queries completed" state="complete" value={fmtNum(s.queries_completed)} source="AI Visibility" lastDataDate={last} />
      <ReportMetricCard label="Platforms tested" state="complete" value={fmtNum(s.platforms_tested.length)} source="AI Visibility" lastDataDate={last} stateDetail={s.platforms_tested.map((p) => p.label).join(", ")} />
      {rateCard("Mention rate", s.mention_rate, "responses")}
      {rateCard("Citation rate", s.citation_rate, "responses")}
      <ReportMetricCard label="Mention count" state="complete" value={fmtNum(s.mention_count)} source="AI Visibility" lastDataDate={last} />
      <ReportMetricCard label="Owned-domain citations" state="complete" value={fmtNum(s.owned_domain_citations)} source="AI Visibility" lastDataDate={last} />
      <ReportMetricCard label="Competitor appearances" state="complete" value={fmtNum(s.competitor_appearances)} source="AI Visibility" lastDataDate={last} />
      <ReportMetricCard
        label="AI referral sessions"
        state={s.ai_referral_sessions ? "complete" : "not_configured"}
        value={s.ai_referral_sessions ? fmtNum(s.ai_referral_sessions.sessions) : undefined}
        stateDetail="No GA4 data for this property."
        source="GA4"
        lastDataDate={s.ai_referral_sessions?.last_data_date ?? null}
      />
    </div>
  );
}

function SufficiencyPanel({ report }: { report: Extract<GeoReportData, { has_queries: true }> }) {
  const g = report.sufficiency;
  if (g.sufficient) return null;
  return (
    <div className="rounded-2xl border border-amber-a/40 bg-amber-a/10 p-5">
      <div className="flex items-center gap-2">
        <StateBadge state="insufficient_sample" />
        <h3 className="text-sm font-medium text-amber-a">Below the visibility sample gate</h3>
      </div>
      <p className="mt-2 text-sm text-muted">
        {g.completed_queries} completed of {g.minimum_required} minimum. Rates are
        withheld until the sample clears the minimum. {g.failed_queries} failed,{" "}
        {g.not_run_queries} not run.
        {g.date_span &&
          ` Runs span ${fmtDate(g.date_span.start)} to ${fmtDate(g.date_span.end)}.`}
      </p>
    </div>
  );
}

function PromptMatrix({
  report,
  onCell,
}: {
  report: Extract<GeoReportData, { has_queries: true }>;
  onCell: (queryId: number) => void;
}) {
  const m = report.prompt_matrix;
  const usedStates = new Set(m.rows.flatMap((r) => r.cells.map((c) => c.state)));
  return (
    <div>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr>
              <th className="sticky left-0 bg-surface py-2 pr-3 text-left text-xs font-medium text-muted">
                Tested query
              </th>
              {m.platforms.map((p) => (
                <th key={p.key} className="px-2 py-2 text-center text-xs font-medium text-muted">
                  {p.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {m.rows.map((row) => (
              <tr key={row.prompt} className="border-t border-line/50">
                <td className="sticky left-0 max-w-[22rem] truncate bg-surface py-2 pr-3" title={row.prompt}>
                  {row.prompt}
                </td>
                {row.cells.map((cell, i) => (
                  <td key={i} className="px-2 py-1.5 text-center">
                    <CellButton cell={cell} onCell={onCell} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-3 flex flex-wrap gap-3 text-xs text-muted">
        {[...usedStates].map((st) => {
          const meta = CELL_META[st];
          if (!meta) return null;
          return (
            <span key={st} className="inline-flex items-center gap-1.5">
              <span className={`inline-flex h-5 w-5 items-center justify-center rounded ${meta.cls}`}>
                {meta.glyph}
              </span>
              {meta.label}
            </span>
          );
        })}
      </div>
    </div>
  );
}

function CellButton({ cell, onCell }: { cell: MatrixCell; onCell: (queryId: number) => void }) {
  const meta = CELL_META[cell.state] ?? CELL_META.not_present;
  const clickable = cell.query_id !== undefined;
  return (
    <button
      onClick={() => clickable && onCell(cell.query_id!)}
      disabled={!clickable}
      aria-label={`${meta.label}${cell.run_date ? `, tested ${cell.run_date}` : ""}`}
      title={meta.label}
      className={`inline-flex h-7 w-7 items-center justify-center rounded ${meta.cls} ${
        clickable ? "cursor-pointer hover:ring-2 hover:ring-violet-a/50" : "cursor-default"
      }`}
    >
      {meta.glyph}
    </button>
  );
}

function EvidenceDrawer({
  evidence,
  onClose,
}: {
  evidence: GeoEvidence | "loading" | null;
  onClose: () => void;
}) {
  if (evidence === null) return null;
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/40" onClick={onClose}>
      <div
        className="h-full w-full max-w-md overflow-y-auto border-l border-line bg-surface p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label="Query evidence"
      >
        <button onClick={onClose} aria-label="Close evidence" className="mb-4 text-muted hover:text-foreground">
          ✕ Close
        </button>
        {evidence === "loading" ? (
          <p className="text-sm text-muted">Loading evidence...</p>
        ) : (
          <div className="space-y-4 text-sm">
            <div>
              <p className="text-xs uppercase tracking-wider text-muted">Query</p>
              <p className="mt-1">{evidence.prompt}</p>
            </div>
            <div className="flex gap-4 text-xs text-muted">
              <span>{evidence.platform_label}</span>
              <span>Run {fmtDate(evidence.run_date)}</span>
            </div>
            <div>
              <p className="text-xs uppercase tracking-wider text-muted">Stored response excerpt</p>
              <p className="mt-1 whitespace-pre-wrap rounded-lg bg-surface-raised p-3 text-xs leading-relaxed text-muted">
                {evidence.response_excerpt}
              </p>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Evi label="Brand mentioned" value={evidence.brand_mentioned ? "Yes" : "No"} />
              <Evi label="Owned domains cited" value={evidence.owned_domains_cited.join(", ") || "None"} />
            </div>
            <div>
              <p className="text-xs uppercase tracking-wider text-muted">Cited domains</p>
              <p className="mt-1 text-xs">{evidence.cited_domains.join(", ") || "None detected"}</p>
            </div>
            <div>
              <p className="text-xs uppercase tracking-wider text-muted">Detected competitors</p>
              <p className="mt-1 text-xs">
                {evidence.detected_competitors.join(", ") || "None of the configured competitors"}
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function Evi({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs uppercase tracking-wider text-muted">{label}</p>
      <p className="mt-1 text-xs">{value}</p>
    </div>
  );
}

function SourceLandscape({ report }: { report: Extract<GeoReportData, { has_queries: true }> }) {
  const ls = report.source_landscape;
  if (ls.domains.length === 0) {
    return <EmptyState title="No cited sources" body="No domains were cited across the tested responses." />;
  }
  const max = Math.max(...ls.domains.map((d) => d.cited_in_responses), 1);
  return (
    <ul className="space-y-2">
      {ls.domains.slice(0, 20).map((d) => (
        <li key={d.domain} className="flex items-center gap-3 text-sm">
          <span className="w-48 shrink-0 truncate" title={d.domain}>
            {d.domain}
          </span>
          <div className="h-5 flex-1 rounded bg-surface-raised">
            <div
              className={`h-5 rounded ${CATEGORY_CLS[d.category] ?? "bg-muted/40"}`}
              style={{ width: `${(d.cited_in_responses / max) * 100}%` }}
              role="img"
              aria-label={`${d.domain}: cited in ${d.cited_in_responses} responses, category ${d.category_label}`}
            />
          </div>
          <span className="w-8 text-right">{d.cited_in_responses}</span>
          <span className="w-14 text-right text-xs text-muted">
            {d.pct_of_completed !== null ? fmtPct(d.pct_of_completed) : ""}
          </span>
          <span className="w-24 shrink-0 text-right text-xs text-muted">{d.category_label}</span>
        </li>
      ))}
    </ul>
  );
}

function CompetitorShare({ report }: { report: Extract<GeoReportData, { has_queries: true }> }) {
  const cs = report.competitor_share;
  if (!cs.has_competitors) {
    return (
      <EmptyState
        title="No competitors configured"
        body="Add the competitors you want compared on the Competitor IQ page. Beacon never guesses competitor identities."
      />
    );
  }
  const sov = cs.share_of_voice;
  if (Array.isArray(sov) || sov.status !== "measured") {
    return (
      <div className="flex items-center gap-3 rounded-xl border border-dashed border-line p-4">
        <StateBadge state="insufficient_sample" />
        <p className="text-sm text-muted">
          {Array.isArray(sov) ? "No data yet." : sov.explanation}
        </p>
      </div>
    );
  }
  const max = Math.max(...sov.entities.map((e) => e.mentions), 1);
  return (
    <ul className="space-y-2">
      {sov.entities.map((e) => (
        <li key={e.name} className="flex items-center gap-3 text-sm">
          <span className={`w-48 shrink-0 truncate ${e.is_property ? "font-medium text-foreground" : ""}`} title={e.name}>
            {e.name}
            {e.is_property && <span className="ml-1 text-xs text-violet-a">(you)</span>}
          </span>
          <div className="h-5 flex-1 rounded bg-surface-raised">
            <div
              className={`h-5 rounded ${e.is_property ? "bg-violet-a/70" : "bg-amber-a/60"}`}
              style={{ width: `${(e.mentions / max) * 100}%` }}
              role="img"
              aria-label={`${e.name}: ${e.mentions} mentions`}
            />
          </div>
          <span className="w-10 text-right">{e.mentions}</span>
          <span className="w-14 text-right text-xs text-muted">
            {e.share !== null ? fmtPct(e.share) : ""}
          </span>
        </li>
      ))}
    </ul>
  );
}

export function GeoReport() {
  const { scope } = useReportContext();
  const [data, setData] = useState<GeoReportData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [evidence, setEvidence] = useState<GeoEvidence | "loading" | null>(null);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    fetchGeoReport(scope.propertyId)
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope.propertyId, attempt]);

  function openEvidence(queryId: number) {
    if (data === null || data.scope_required || !("has_queries" in data) || !data.has_queries) return;
    setEvidence("loading");
    fetchGeoEvidence(data.property_id, queryId)
      .then(setEvidence)
      .catch(() => setEvidence(null));
  }

  if (error) return <ErrorState message={error} onRetry={() => setAttempt((a) => a + 1)} />;
  if (!data) return <p className="text-sm text-muted">Loading GEO report...</p>;
  if (data.scope_required) return <EmptyState title="Select a property" body={data.message} />;
  if (!data.has_queries) {
    return (
      <div className="space-y-4">
        <EmptyState title="No AI Visibility queries yet" body={data.message} />
        <SufficiencyPanel report={{ ...data, has_queries: true } as never} />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <p className="text-xs text-muted">{data.methodology}</p>
      <SufficiencyPanel report={data} />
      <SummaryCards report={data} />

      <Section title="Prompt visibility matrix" sub="Rows are tested queries, columns are AI platforms. Click a cell to inspect the stored response.">
        <PromptMatrix report={data} onCell={openEvidence} />
      </Section>

      <Section title="Source landscape" sub="Domains the tested AI responses cited, classified deterministically. Unknown stays unknown until configured.">
        <SourceLandscape report={data} />
      </Section>

      <Section title={data.competitor_share.label} sub="Operator-configured competitors only. This is share of tested AI answers, not market share.">
        <CompetitorShare report={data} />
      </Section>

      {data.trends.points.length > 0 && (
        <Section title="Visibility trend" sub={data.trends.note}>
          <ul className="space-y-1 text-sm">
            {data.trends.points.map((p, i) => (
              <li key={i} className="flex items-center gap-3">
                <span className="w-28 text-muted">{fmtDate(p.date)}</span>
                <span className="w-24">
                  {p.score !== null ? `Score ${p.score}` : "Below sample"}
                </span>
                <span className="text-xs text-muted">{p.sample_size} queries</span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      <EvidenceDrawer evidence={evidence} onClose={() => setEvidence(null)} />
    </div>
  );
}
