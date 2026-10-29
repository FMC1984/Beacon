"use client";

import type { TrendPoint } from "@/lib/observatory";

/** A metric's own shape over the window.
 *
 * Only days that cleared the sample minimum are drawn, and each sits at its
 * real date rather than at an even step, so a week nobody monitored reads as
 * a gap instead of a straight run. Under two such days cannot make a shape,
 * so nothing is drawn at all: an almost-empty chart invites the reader to see
 * a trend that the sample does not support.
 *
 * The y axis is the rate's own 0 to 100%, never the data's own range. Fitting
 * the line to its min and max makes a metric that moved two points look like
 * a mountain range, which is the chart lying about magnitude.
 */
export function Sparkline({
  series,
  from,
  to,
  height = 32,
  area = false,
  label,
}: {
  series: TrendPoint[];
  from: string;
  to: string;
  height?: number;
  area?: boolean;
  label: string;
}) {
  const points = series.filter((p) => p.value !== null);
  if (points.length < 2) return null;

  const W = 240;
  const pad = 4;
  const t0 = Date.parse(from);
  const span = Math.max(Date.parse(to) - t0, 1);
  const x = (p: TrendPoint) => Math.round(((Date.parse(p.day) - t0) / span) * W * 10) / 10;
  const y = (p: TrendPoint) =>
    Math.round((pad + (1 - (p.value as number)) * (height - pad * 2)) * 10) / 10;

  const coords = points.map((p) => `${x(p)},${y(p)}`).join(" ");
  const last = points[points.length - 1];

  return (
    <svg
      viewBox={`0 0 ${W} ${height}`}
      width="100%"
      height={height}
      preserveAspectRatio="none"
      role="img"
      aria-label={label}
      className="overflow-visible"
    >
      {area && (
        <polygon
          points={`${x(points[0])},${height} ${coords} ${x(last)},${height}`}
          fill="currentColor"
          opacity={0.14}
        />
      )}
      <polyline
        points={coords}
        fill="none"
        stroke="currentColor"
        strokeWidth={area ? 2 : 1.75}
        strokeLinejoin="round"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
      <circle cx={x(last)} cy={y(last)} r={area ? 3 : 2.5} fill="currentColor" />
    </svg>
  );
}
