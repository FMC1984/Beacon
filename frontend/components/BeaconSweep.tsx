/** Beacon sweep motif (visual polish pass): faint radiating arcs with a soft
 * light cone, used as background line art behind empty states and the access
 * gate. Purely decorative (aria-hidden), absolutely positioned behind content;
 * the parent needs position: relative and overflow-hidden. */

export function BeaconSweep({ className = "" }: { className?: string }) {
  const arcs = [36, 72, 108, 144, 180, 216];
  return (
    <svg
      viewBox="0 0 480 240"
      aria-hidden
      className={`pointer-events-none absolute inset-x-0 bottom-0 h-full w-full ${className}`}
      preserveAspectRatio="xMidYMax slice"
    >
      {/* Light cone sweeping up-left from the source point. */}
      <defs>
        <linearGradient id="beacon-cone" x1="0.5" y1="1" x2="0.28" y2="0">
          <stop offset="0" stopColor="#22d3ee" stopOpacity="0.10" />
          <stop offset="1" stopColor="#22d3ee" stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d="M240 240 L148 0 L226 0 Z" fill="url(#beacon-cone)" />
      {arcs.map((r, i) => (
        <path
          key={r}
          d={`M ${240 - r} 240 A ${r} ${r} 0 0 1 ${240 + r} 240`}
          fill="none"
          stroke="#a78bfa"
          strokeOpacity={0.22 - i * 0.028}
          strokeWidth="1"
        />
      ))}
      <circle cx="240" cy="238" r="3" fill="#a78bfa" fillOpacity="0.7" />
    </svg>
  );
}
