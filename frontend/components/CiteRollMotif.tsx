/** CiteRoll motif: a few faint lines of an answer with one highlighted
 * citation, the idea the product is named for. A small mark in the lower left
 * corner rather than a full-bleed wash, so it never sits behind the content it
 * decorates. Purely decorative (aria-hidden); the parent needs position:
 * relative and overflow-hidden. Replaces the old lighthouse sweep. */

export function CiteRollMotif({ className = "" }: { className?: string }) {
  // Ragged widths so it reads as prose rather than a chart.
  const lines = [
    { y: 4, w: 58 },
    { y: 18, w: 76 },
    { y: 32, w: 46, cited: true },
    { y: 46, w: 66 },
  ];
  return (
    <svg
      viewBox="0 0 96 58"
      width="96"
      height="58"
      aria-hidden
      className={`pointer-events-none absolute bottom-4 left-4 ${className}`}
    >
      {lines.map((l) => (
        <g key={l.y}>
          {l.cited && (
            <rect x={-3} y={l.y - 3} width={l.w + 8} height={14} rx="4" fill="#d9f06a" fillOpacity="0.10" />
          )}
          <rect
            x={0}
            y={l.y}
            width={l.w}
            height="8"
            rx="4"
            fill={l.cited ? "#d9f06a" : "#a78bfa"}
            fillOpacity={l.cited ? 0.28 : 0.14}
          />
        </g>
      ))}
    </svg>
  );
}
