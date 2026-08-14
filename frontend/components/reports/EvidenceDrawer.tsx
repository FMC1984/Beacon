"use client";

/** Shared evidence-drawer shell (Phase 18): fixed overlay + right-docked
 * panel + loading state + close button, used by every report that lets a
 * summary number be walked back down to the stored response that produced
 * it (GEO's prompt matrix, Share of Voice's mention/topic/prompt drilldown).
 * Content is injected via children so each report keeps its own evidence
 * shape instead of forcing a shared data union. */

export function EvidenceDrawerShell({
  open,
  loading,
  onClose,
  ariaLabel,
  children,
}: {
  open: boolean;
  loading: boolean;
  onClose: () => void;
  ariaLabel: string;
  children: React.ReactNode;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/40" onClick={onClose}>
      <div
        className="h-full w-full max-w-md overflow-y-auto border-l border-line bg-surface p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label={ariaLabel}
      >
        <button onClick={onClose} aria-label="Close evidence" className="mb-4 text-muted hover:text-foreground">
          ✕ Close
        </button>
        {loading ? <p className="text-sm text-muted">Loading evidence...</p> : children}
      </div>
    </div>
  );
}

export function EvidenceField({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs uppercase tracking-wider text-muted">{label}</p>
      <p className="mt-1 text-xs">{value}</p>
    </div>
  );
}
