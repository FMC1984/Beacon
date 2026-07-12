import type { Provenance } from "@/lib/api";
import { fmtDate, fmtDateTime } from "@/lib/format";

/** Required footer for every component showing ingested or synced data:
 * source, date range, last updated, and freshness warning when applicable.
 * Rendered unconditionally by design; do not make this optional. */
export function ProvenanceFooter({ provenance }: { provenance: Provenance }) {
  return (
    <div className="mt-4 border-t border-line pt-3 text-xs text-muted">
      <span>{provenance.source}</span>
      <span className="px-1.5">·</span>
      <span>
        {fmtDate(provenance.date_start)} to {fmtDate(provenance.date_end)}
      </span>
      {provenance.last_updated && (
        <>
          <span className="px-1.5">·</span>
          <span>Last updated {fmtDateTime(provenance.last_updated)}</span>
        </>
      )}
      {provenance.freshness_warning && (
        <div className="mt-2 inline-flex items-start gap-1.5 rounded-lg bg-amber-a/10 px-2.5 py-1.5 text-amber-a">
          <span aria-hidden>⚠</span>
          <span>{provenance.freshness_warning}</span>
        </div>
      )}
    </div>
  );
}
