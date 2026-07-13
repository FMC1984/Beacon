"use client";

/** Public, read-only view of a shared briefing snapshot (Phase 17D). Reached
 * via an unguessable token; the backend route is exempt from the access key
 * and returns only the frozen, client-safe payload. Shared mode hides Ask
 * Nora launches (viewers have no app access). */

import { use, useEffect, useState } from "react";
import { BriefingBody, SharedModeContext } from "@/components/briefing/BriefingView";
import { fetchSharedBriefing, type BriefingResponse } from "@/lib/briefing";

export default function SharedBriefingPage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = use(params);
  const [data, setData] = useState<BriefingResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchSharedBriefing(token)
      .then(setData)
      .catch(() => setError("This shared briefing link is invalid or has been revoked."));
  }, [token]);

  return (
    <div className="mx-auto max-w-5xl px-6 py-8">
      <div className="mb-4 flex items-center justify-between">
        <p className="text-sm font-semibold uppercase tracking-wider text-violet-a">Beacon</p>
        <span className="rounded-full border border-line bg-surface px-2.5 py-0.5 text-[11px] text-muted">
          Shared read-only report
        </span>
      </div>

      {error ? (
        <div className="rounded-2xl border border-line bg-surface p-8 text-center">
          <p className="text-sm font-medium">Link not available</p>
          <p className="mt-1 text-sm text-muted">{error}</p>
        </div>
      ) : !data ? (
        <p className="text-sm text-muted">Loading briefing...</p>
      ) : data.scope_required ? (
        <p className="text-sm text-muted">{data.message}</p>
      ) : (
        <SharedModeContext.Provider value={true}>
          <BriefingBody data={data} />
        </SharedModeContext.Provider>
      )}
    </div>
  );
}
