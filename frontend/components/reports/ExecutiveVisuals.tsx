"use client";

/** Executive report visuals. Charts earn their place by showing what the metric
 * tiles cannot: AI referral traffic as a share of the whole, the Content
 * Intelligence score as progress toward 100, and organic search efficiency
 * (impressions -> clicks). Each renders only when its source cards are complete;
 * a metric that is "no data yet" is omitted, never charted as zero. All color is
 * from Beacon's accent ramp, one dominant hue per chart. */

import {
  Bar,
  BarChart,
  Cell,
  Pie,
  PieChart,
  PolarAngleAxis,
  RadialBar,
  RadialBarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { fmtNum, fmtPct } from "@/lib/format";
import type { ExecCard } from "@/lib/reports";

const TOOLTIP_STYLE = {
  background: "var(--surface-raised)",
  border: "1px solid var(--border)",
  borderRadius: 12,
  color: "var(--foreground)",
  fontSize: 12,
};

function completeValue(cards: ExecCard[], key: string): number | null {
  const c = cards.find((x) => x.key === key);
  if (!c || c.state !== "complete" || c.value === null) return null;
  return c.value;
}

function Panel({ title, sub, children }: { title: string; sub?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl border border-line bg-surface p-5">
      <h3 className="text-sm font-medium">{title}</h3>
      {sub && <p className="mt-0.5 text-xs text-muted">{sub}</p>}
      <div className="mt-4">{children}</div>
    </section>
  );
}

/** Part-to-whole: AI-referred sessions against everything else. One highlighted
 * slice (violet = AI, Beacon's thesis metric); the rest is recessive surface. */
function AiShareDonut({ share, sessions }: { share: number; sessions: number | null }) {
  const data = [
    { name: "AI referral", value: share },
    { name: "Other traffic", value: Math.max(0, 1 - share) },
  ];
  return (
    <Panel title="AI referral share" sub="Share of sessions arriving from AI assistants.">
      <div className="flex items-center gap-5">
        <div className="relative h-40 w-40 shrink-0">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={data}
                dataKey="value"
                nameKey="name"
                innerRadius={54}
                outerRadius={72}
                startAngle={90}
                endAngle={-270}
                stroke="var(--surface)"
                strokeWidth={2}
              >
                <Cell fill="var(--accent-violet)" />
                <Cell fill="var(--surface-raised)" />
              </Pie>
              <Tooltip
                contentStyle={TOOLTIP_STYLE}
                formatter={(value, name) => [fmtPct(Number(value)), name]}
              />
            </PieChart>
          </ResponsiveContainer>
          <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
            <span className="text-2xl font-semibold">{fmtPct(share)}</span>
            <span className="text-[11px] text-muted">AI</span>
          </div>
        </div>
        <ul className="space-y-2 text-sm">
          <li className="flex items-center gap-2">
            <span aria-hidden className="h-2.5 w-2.5 rounded-full" style={{ background: "var(--accent-violet)" }} />
            AI referral
            {sessions !== null && <span className="text-muted">{fmtNum(sessions)} sessions</span>}
          </li>
          <li className="flex items-center gap-2">
            <span aria-hidden className="h-2.5 w-2.5 rounded-full" style={{ background: "var(--surface-raised)", outline: "1px solid var(--border)" }} />
            <span className="text-muted">Other traffic</span>
          </li>
        </ul>
      </div>
    </Panel>
  );
}

/** Single bounded KPI: the content score as an arc toward 100. One hue. */
function ScoreGauge({ score }: { score: number }) {
  const data = [{ name: "score", value: score }];
  return (
    <Panel title="Content Intelligence score" sub="Website content readiness, out of 100.">
      <div className="relative h-40">
        <ResponsiveContainer width="100%" height="100%">
          <RadialBarChart
            data={data}
            innerRadius="72%"
            outerRadius="100%"
            startAngle={220}
            endAngle={-40}
          >
            <PolarAngleAxis type="number" domain={[0, 100]} tick={false} />
            <RadialBar
              dataKey="value"
              cornerRadius={8}
              fill="var(--accent-emerald)"
              background={{ fill: "var(--surface-raised)" }}
            />
          </RadialBarChart>
        </ResponsiveContainer>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-3xl font-semibold">{score}</span>
          <span className="text-[11px] text-muted">out of 100</span>
        </div>
      </div>
    </Panel>
  );
}

/** Magnitude + efficiency: impressions vs clicks from Search Console, with CTR.
 * Both from one source, so the relationship is honest. */
function OrganicSearch({ impressions, clicks }: { impressions: number; clicks: number }) {
  const ctr = impressions > 0 ? clicks / impressions : null;
  const data = [
    { name: "Impressions", value: impressions },
    { name: "Clicks", value: clicks },
  ];
  return (
    <Panel title="Organic search" sub={ctr !== null ? `Impressions to clicks · ${fmtPct(ctr)} CTR` : "Impressions to clicks"}>
      <div className="h-40">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} layout="vertical" margin={{ left: 8, right: 16, top: 4, bottom: 4 }}>
            <XAxis type="number" hide />
            <YAxis
              type="category"
              dataKey="name"
              width={84}
              tick={{ fill: "var(--muted)", fontSize: 12 }}
              axisLine={false}
              tickLine={false}
            />
            <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: "var(--surface-raised)" }} formatter={(value) => fmtNum(Number(value))} />
            <Bar dataKey="value" fill="var(--accent-cyan)" radius={[0, 4, 4, 0]} barSize={22} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </Panel>
  );
}

export function ExecutiveVisuals({ cards }: { cards: ExecCard[] }) {
  const aiShare = completeValue(cards, "ai_share");
  const aiSessions = completeValue(cards, "ai_referral_sessions");
  const contentScore = completeValue(cards, "content_score");
  const impressions = completeValue(cards, "organic_impressions");
  const clicks = completeValue(cards, "organic_clicks");

  const panels: React.ReactNode[] = [];
  if (aiShare !== null) panels.push(<AiShareDonut key="ai" share={aiShare} sessions={aiSessions} />);
  if (contentScore !== null) panels.push(<ScoreGauge key="score" score={contentScore} />);
  if (impressions !== null && clicks !== null)
    panels.push(<OrganicSearch key="organic" impressions={impressions} clicks={clicks} />);

  if (panels.length === 0) return null;

  return <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">{panels}</div>;
}
