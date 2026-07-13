"use client";

/** GA4 events breakdown (page_view, scroll, click, ...), shared by the
 * Dashboard and the SEO report. Event count is the exact, additive headline;
 * the user column carries the "summed active users" caveat from the backend. */

import { fmtNum, fmtPct } from "@/lib/format";
import type { EventsSection } from "@/lib/api";

export function EventsPanel({
  section,
  title = "Events",
}: {
  section: EventsSection;
  title?: string;
}) {
  const max = Math.max(...section.events.map((e) => e.event_count), 1);
  return (
    <section className="rounded-2xl border border-line bg-surface p-5">
      <div className="flex items-baseline justify-between">
        <h3 className="text-sm font-medium">{title}</h3>
        <span className="text-xs text-muted">
          {fmtNum(section.total_event_count)} events · {section.distinct_events} types
        </span>
      </div>

      <div className="mt-4 overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="text-left text-xs text-muted">
              <th className="py-2 pr-3 font-medium">Event</th>
              <th className="px-2 py-2 text-right font-medium">Count</th>
              <th className="px-2 py-2 font-medium">Share</th>
              <th className="px-2 py-2 text-right font-medium">Users</th>
              <th className="px-2 py-2 text-right font-medium">Per user</th>
            </tr>
          </thead>
          <tbody>
            {section.events.map((e) => (
              <tr key={e.event_name} className="border-t border-line/50">
                <td className="py-2 pr-3 font-medium">{e.event_name}</td>
                <td className="px-2 py-2 text-right tabular-nums">{fmtNum(e.event_count)}</td>
                <td className="px-2 py-2">
                  <div className="flex items-center gap-2">
                    <div className="h-3.5 w-full min-w-24 rounded bg-surface-raised">
                      <div
                        className="h-3.5 rounded bg-violet-a/70"
                        style={{ width: `${(e.event_count / max) * 100}%` }}
                        role="img"
                        aria-label={`${e.event_name}: ${e.event_count} events`}
                      />
                    </div>
                    <span className="w-12 shrink-0 text-right text-xs text-muted tabular-nums">
                      {e.count_share !== null ? fmtPct(e.count_share) : ""}
                    </span>
                  </div>
                </td>
                <td className="px-2 py-2 text-right text-muted tabular-nums">{fmtNum(e.total_users)}</td>
                <td className="px-2 py-2 text-right text-muted tabular-nums">
                  {e.per_user !== null ? e.per_user.toFixed(2) : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {section.events_total > section.events_shown && (
        <p className="mt-3 text-xs text-muted">
          Showing the top {section.events_shown} of {fmtNum(section.events_total)} event types.
        </p>
      )}
      <p className="mt-2 text-xs text-muted">{section.note}</p>
    </section>
  );
}
