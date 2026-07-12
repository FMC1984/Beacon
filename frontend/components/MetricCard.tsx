/** Plain metric tile, and the AI variant that cannot render without the
 * undercount disclosure (hard rule 3: the prop is required, not optional). */

/** THE single AI undercount disclosure rendering. Every AI traffic display in
 * the app must use this component; do not inline the styling elsewhere. */
export function Disclosure({ text }: { text: string }) {
  return (
    <p className="mt-3 rounded-lg bg-violet-a/10 px-2.5 py-1.5 text-[11px] leading-snug text-violet-a/90">
      {text}
    </p>
  );
}

export function MetricCard({
  label,
  value,
  sub,
  accent = "var(--accent-cyan)",
}: {
  label: string;
  value: string;
  sub?: string;
  accent?: string;
}) {
  return (
    <div className="rounded-2xl border border-line bg-surface p-5">
      <p className="text-sm text-muted">{label}</p>
      <p className="mt-1 text-3xl font-semibold tracking-tight" style={{ color: accent }}>
        {value}
      </p>
      {sub && <p className="mt-1 text-xs text-muted">{sub}</p>}
    </div>
  );
}

export function AIMetricCard({
  label,
  value,
  sub,
  disclosure,
}: {
  label: string;
  value: string;
  sub?: string;
  disclosure: string;
}) {
  return (
    <div className="rounded-2xl border border-violet-a/30 bg-surface p-5">
      <p className="text-sm text-muted">{label}</p>
      <p className="mt-1 text-3xl font-semibold tracking-tight text-violet-a">{value}</p>
      {sub && <p className="mt-1 text-xs text-muted">{sub}</p>}
      <Disclosure text={disclosure} />
    </div>
  );
}
