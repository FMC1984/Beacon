/** The CiteRoll mark and lockup.
 *
 * The mark is inline SVG rather than an <img> so it inherits crisp rendering
 * at every size and needs no network request; the wordmark is real text in the
 * brand face, so it stays selectable and never ships a font inside an image
 * (external fonts do not load inside an <img> SVG).
 *
 * The mark is the AI answer as a speech bubble, with the middle line
 * highlighted: the citation the product is named for. An earlier version put a
 * building beside it for "the community", which turned to noise at nav and
 * favicon sizes, so the bubble carries the idea alone.
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
        <linearGradient id="cr-bubble" gradientUnits="userSpaceOnUse" x1="6" y1="10" x2="122" y2="120">
          <stop offset="0" stopColor="#6DD5FA" />
          <stop offset="1" stopColor="#7C5CFF" />
        </linearGradient>
      </defs>
      <rect x="6" y="10" width="116" height="84" rx="24" fill="url(#cr-bubble)" />
      <path d="M34 92 L34 120 L64 92 Z" fill="url(#cr-bubble)" />
      <rect x="26" y="30" width="54" height="9" rx="4.5" fill="#FFFFFF" />
      <rect x="20" y="49" width="84" height="20" rx="6" fill="#D6F05A" />
      <rect x="26" y="54" width="72" height="10" rx="5" fill="#1B1F4A" />
      <rect x="26" y="76" width="40" height="9" rx="4.5" fill="#FFFFFF" opacity="0.9" />
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
