"use client";

/** Three views that reuse stored answers (no new AI calls):
 *   StandingStrip       market rank and confirmed comp-set rank
 *   PlatformPanel       per-platform metrics; unconnected platforms say why
 *   SourceMatrixPanel   where AI learns about this property, with an action
 */

import Link from "next/link";
import {
  fetchPlatformBreakdown,
  fetchSourceMatrix,
  fetchStanding,
  fmtRate,
  type PlatformAvailability,
  type SourceAction,
  type SourceMatrixRow,
} from "@/lib/observatory";
import { LoadState, Panel, ShareBar, useLoad } from "./ui";

// --- Standing ------------------------------------------------------------------

function Tile({ title, big, lines, href, cta }: { title: string; big: string; lines: string[]; href?: string; cta?: string }) {
  return (
    <div className="rounded-2xl border border-line bg-surface p-4">
      <div className="text-xs uppercase tracking-wider text-muted">{title}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{big}</div>
      {lines.map((l) => (
        <p key={l} className="mt-1 text-xs text-muted">{l}</p>
      ))}
      {href && cta && (
        <Link href={href} className="mt-2 inline-block text-xs text-violet-a hover:underline">{cta} ›</Link>
      )}
    </div>
  );
}

export function StandingStrip({ propertyId, days }: { propertyId: number; days: number }) {
  const { data } = useLoad(() => fetchStanding(propertyId, days), [propertyId, days]);
  if (!data) return null;
  const m = data.market;
  const c = data.comp_set;
  const marketLines = m.available
    ? [
        m.only_one
          ? "The only community Beacon monitors in this market, so there is nobody to rank against yet."
          : `By AI Visibility (${fmtRate(m.ai_visibility)}) among ${m.size} monitored communit${m.size === 1 ? "y" : "ies"} here${m.tied ? ", tied" : ""}.`,
        ...(m.also_named > 0 ? [`AI answers also name ${m.also_named} other communit${m.also_named === 1 ? "y" : "ies"} in this market that nobody tracks yet.`] : []),
      ]
    : [m.reason];
  const compLines = c.available
    ? [
        c.rank === null
          ? "Not named in any monitored answer in this window."
          : `Beating ${c.beating} of ${c.competitors} confirmed competitor${c.competitors === 1 ? "" : "s"} across ${c.answers} answers${c.tied ? " (tied)" : ""}.`,
        ...c.ahead_of_you.map((a) => `${a.name} is ahead${a.winning_on.length ? `, mainly on ${a.winning_on.join(", ")}` : ""}.`),
      ]
    : [c.reason];
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
      <Tile
        title="Your market"
        big={m.available && !m.only_one ? `#${m.rank} of ${m.size}` : m.available ? "1 monitored" : "n/a"}
        lines={marketLines}
        href={`/ai-visibility/markets?property_id=${propertyId}`}
        cta="Market view"
      />
      <Tile
        title="Your comp set"
        big={c.available ? (c.rank !== null ? `#${c.rank} of ${c.size}` : `unranked of ${c.size}`) : "n/a"}
        lines={compLines}
        href={`/ai-visibility/competitors?property_id=${propertyId}`}
        cta="Rankings by topic"
      />
    </div>
  );
}

// --- Platforms -------------------------------------------------------------------

const AVAIL: Record<PlatformAvailability["state"], { text: string; cls: string }> = {
  live: { text: "Live", cls: "bg-emerald-500/15 text-emerald-300" },
  needs_key: { text: "Ready, no key", cls: "bg-amber-500/15 text-amber-300" },
  planned: { text: "Planned", cls: "bg-surface-raised text-muted" },
  no_api: { text: "No API", cls: "bg-surface-raised text-muted" },
};

export function PlatformPanel({ propertyId, days }: { propertyId: number; days: number }) {
  const { data, error, loading, retry } = useLoad(() => fetchPlatformBreakdown(propertyId, days), [propertyId, days]);
  return (
    <Panel
      title="By AI platform"
      label="MEASURED"
      subtitle="Each platform is measured from its own answers. Platforms that are not connected say why and add nothing to any number."
    >
      <LoadState loading={loading && !data} error={error} retry={retry}>
        {data && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-sm">
              <thead className="text-left text-xs text-muted">
                <tr className="border-b border-line">
                  <th className="py-2 pr-3 font-normal">Platform</th>
                  <th className="py-2 pr-3 text-right font-normal">Answers</th>
                  <th className="py-2 pr-3 text-right font-normal">AI Visibility</th>
                  <th className="py-2 pr-3 text-right font-normal">Citation Rate</th>
                  <th className="py-2 pr-3 text-right font-normal">Share of Voice</th>
                  <th className="py-2 font-normal">Leans on</th>
                </tr>
              </thead>
              <tbody>
                {data.platforms.map((p) => {
                  const live = p.availability.state === "live";
                  const cell = (v: number | null) => (live ? (v !== null ? fmtRate(v) : <span className="text-xs text-muted">below sample</span>) : <span className="text-muted">·</span>);
                  return (
                    <tr key={p.platform} className={`border-b border-line/60 align-top ${live ? "" : "opacity-70"}`}>
                      <td className="py-2 pr-3">
                        <span className="mr-2">{p.label}</span>
                        <span className={`rounded-full px-2 py-0.5 text-[11px] ${AVAIL[p.availability.state].cls}`} title={p.availability.detail}>
                          {AVAIL[p.availability.state].text}
                        </span>
                        {!live && <span className="mt-0.5 block max-w-xs text-[11px] text-muted">{p.availability.detail}</span>}
                      </td>
                      <td className="py-2 pr-3 text-right tabular-nums">{live ? p.answers : <span className="text-muted">·</span>}</td>
                      <td className="py-2 pr-3 text-right tabular-nums">{cell(p.ai_visibility.value)}</td>
                      <td className="py-2 pr-3 text-right tabular-nums">{cell(p.citation_rate.value)}</td>
                      <td className="py-2 pr-3 text-right tabular-nums">{cell(p.share_of_voice.value)}</td>
                      <td className="py-2 text-xs text-muted">
                        {p.top_sources.length ? p.top_sources.map((s) => `${s.domain} ${fmtRate(s.share)}`).join(" · ") : live ? "no citations yet" : ""}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </LoadState>
    </Panel>
  );
}

// --- Source Influence Matrix ---------------------------------------------------------

const ACTION_STYLE: Record<SourceAction, { text: string; cls: string }> = {
  fix: { text: "Fix", cls: "bg-rose-500/15 text-rose-300" },
  study: { text: "Study", cls: "bg-rose-500/15 text-rose-300" },
  strengthen: { text: "Strengthen", cls: "bg-amber-500/15 text-amber-300" },
  opportunity: { text: "Opportunity", cls: "bg-amber-500/15 text-amber-300" },
  check: { text: "Check", cls: "bg-surface-raised text-muted" },
  verify: { text: "Verify by hand", cls: "bg-surface-raised text-muted" },
  expand: { text: "Expand", cls: "bg-emerald-500/15 text-emerald-300" },
  maintain: { text: "Maintain", cls: "bg-emerald-500/15 text-emerald-300" },
  monitor: { text: "Monitor", cls: "bg-surface-raised text-muted" },
};

const PRESENCE: Record<SourceMatrixRow["presence"], string> = {
  owned: "Your site",
  present: "Names you",
  absent: "Does not name you",
  unknown: "Not read yet",
};

const ADVANTAGE: Record<SourceMatrixRow["competitor_advantage"], string> = {
  high: "High",
  shared: "Shared",
  none: "None",
  unknown: "Unknown",
};

export function SourceMatrixPanel({ propertyId, days }: { propertyId: number; days: number }) {
  const { data, error, loading, retry } = useLoad(() => fetchSourceMatrix(propertyId, days), [propertyId, days]);
  const multi = (data?.platforms.length ?? 0) > 1;
  return (
    <Panel
      title="Where AI learns about this property"
      label="MEASURED"
      subtitle="Every source AI answers cited for this property's questions: how much AI leans on it, whether it names you, whether a competitor has the advantage there, and what to do."
    >
      <LoadState
        loading={loading && !data}
        error={error}
        retry={retry}
        empty={{ when: data !== null && data.sources.length === 0, title: "No cited sources yet", body: "The matrix fills in once monitored AI answers cite the web." }}
      >
        {data && data.sources.length > 0 && (
          <>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[860px] text-sm">
                <thead className="text-left text-xs text-muted">
                  <tr className="border-b border-line">
                    <th className="py-2 pr-3 font-normal">Source</th>
                    <th className="w-40 py-2 pr-3 font-normal">AI influence</th>
                    <th className="py-2 pr-3 font-normal">You on the cited pages</th>
                    <th className="py-2 pr-3 font-normal">Competitor advantage</th>
                    <th className="py-2 pr-3 font-normal">Accuracy</th>
                    <th className="py-2 font-normal">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {data.sources.map((s) => (
                    <tr key={s.domain} className="border-b border-line/60 align-top">
                      <td className="py-2 pr-3">
                        {s.domain}
                        <span className="block text-[11px] text-muted">
                          {(s.source_type ?? "other").replace(/_/g, " ")} · {s.citations} citations
                          {multi && ` · ${Object.entries(s.by_platform).map(([k, v]) => `${k} ${fmtRate(v)}`).join(", ")}`}
                        </span>
                      </td>
                      <td className="py-2 pr-3">
                        <div className="flex items-center gap-2">
                          <ShareBar value={s.share} tone="cyan" />
                          <span className="w-10 shrink-0 text-right text-xs">{fmtRate(s.share)}</span>
                        </div>
                        <span className="text-[11px] capitalize text-muted">{s.influence}</span>
                      </td>
                      <td className="py-2 pr-3 text-xs">
                        {PRESENCE[s.presence]}
                        <span className="block text-[11px] text-muted">
                          {s.pages.read} of {s.pages.cited} pages read{s.pages.unreachable ? `, ${s.pages.unreachable} unreachable` : ""}
                        </span>
                      </td>
                      <td className="py-2 pr-3 text-xs">
                        {ADVANTAGE[s.competitor_advantage]}
                        {s.competitors_named.length > 0 && <span className="block text-[11px] text-muted">{s.competitors_named.join(", ")}</span>}
                      </td>
                      <td className="py-2 pr-3 text-xs text-muted" title={data.accuracy_note}>Not graded</td>
                      <td className="py-2">
                        <span className={`rounded-full px-2 py-0.5 text-[11px] ${ACTION_STYLE[s.action].cls}`} title={s.action_text}>
                          {ACTION_STYLE[s.action].text}
                        </span>
                        <span className="mt-1 block max-w-[14rem] text-[11px] text-muted">{s.action_text}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-3 text-xs text-muted">{data.note} {data.accuracy_note}</p>
          </>
        )}
      </LoadState>
    </Panel>
  );
}
