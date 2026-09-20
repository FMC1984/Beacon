/** The CiteRoll mark and lockup.
 *
 * The mark is inline SVG rather than an <img> so it inherits crisp rendering
 * at every size and needs no network request; the wordmark is real text in the
 * brand face, so it stays selectable and never ships a font inside an image
 * (external fonts do not load inside an <img> SVG).
 *
 * The mark reads: a speech bubble (the AI answer) whose middle line is
 * highlighted (the citation), beside a multifamily building (the community).
 */

export function CiteRollMark({ size = 28, className = "" }: { size?: number; className?: string }) {
  return (
    <svg
      viewBox="0 0 128 128"
      width={size}
      height={size}
      className={`shrink-0 ${className}`}
      role="img"
      aria-label="CiteRoll"
    >
      <defs>
        <linearGradient id="cr-bubble" gradientUnits="userSpaceOnUse" x1="10" y1="14" x2="102" y2="106">
          <stop offset="0" stopColor="#6DD5FA" />
          <stop offset="1" stopColor="#7C5CFF" />
        </linearGradient>
      </defs>
      <rect x="10" y="14" width="92" height="72" rx="18" fill="url(#cr-bubble)" />
      <path d="M28 82 L28 106 L52 82 Z" fill="url(#cr-bubble)" />
      <rect x="26" y="34" width="40" height="8" rx="4" fill="#FFFFFF" />
      <rect x="22" y="48" width="48" height="16" rx="5" fill="#D6F05A" />
      <rect x="27" y="52" width="38" height="8" rx="4" fill="#1B1F4A" />
      <rect x="26" y="68" width="30" height="8" rx="4" fill="#FFFFFF" opacity="0.9" />
      <rect x="76" y="30" width="34" height="84" rx="3" fill="#EAF0FA" />
      <g fill="#0B0E1C">
        <rect x="83" y="40" width="8" height="9" rx="1.5" /><rect x="96" y="40" width="8" height="9" rx="1.5" />
        <rect x="83" y="54" width="8" height="9" rx="1.5" /><rect x="96" y="54" width="8" height="9" rx="1.5" />
        <rect x="83" y="68" width="8" height="9" rx="1.5" /><rect x="96" y="68" width="8" height="9" rx="1.5" />
        <rect x="83" y="82" width="8" height="9" rx="1.5" /><rect x="96" y="82" width="8" height="9" rx="1.5" />
        <rect x="83" y="96" width="8" height="9" rx="1.5" /><rect x="96" y="96" width="8" height="9" rx="1.5" />
      </g>
      <rect x="110" y="58" width="14" height="56" rx="2" fill="#B78CFF" />
      <g fill="#0B0E1C">
        <rect x="114" y="66" width="6" height="7" rx="1.2" /><rect x="114" y="80" width="6" height="7" rx="1.2" />
        <rect x="114" y="94" width="6" height="7" rx="1.2" />
      </g>
    </svg>
  );
}

/** Mark plus wordmark. `size` drives the mark; the wordmark scales with it. */
export function CiteRollLogo({ size = 26, className = "" }: { size?: number; className?: string }) {
  return (
    <span className={`flex items-center gap-2 ${className}`}>
      <CiteRollMark size={size} />
      <span
        className="font-display font-bold tracking-tight text-foreground"
        style={{ fontSize: size * 0.86, lineHeight: 1 }}
      >
        Cite<span className="text-violet-a">Roll</span>
      </span>
    </span>
  );
}
