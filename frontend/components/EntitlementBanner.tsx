"use client";

/** One line at the top of the app when billing needs attention: no active
 * subscription (the org is read-only), or more communities monitored than paid
 * for. Silent for platform admins across all orgs, sample orgs and paid orgs. */

import Link from "next/link";
import { useEffect, useState } from "react";
import { useSession } from "@/components/SessionProvider";
import { fetchBillingStatus, type Entitlement } from "@/lib/billing";

export function EntitlementBanner() {
  const { me, org, role } = useSession();
  const [ent, setEnt] = useState<Entitlement | null>(null);

  useEffect(() => {
    if (!me?.user || !org) return;
    let cancelled = false;
    fetchBillingStatus()
      .then((s) => {
        if (!cancelled) setEnt(s.entitlement);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [me, org]);

  if (!ent || ent.source === "sample" || ent.source === "override") return null;
  const canFix = role === "owner" || role === "platform_admin";
  const fixLink = canFix ? (
    <Link href="/settings/billing" className="ml-2 underline hover:text-foreground">Open billing</Link>
  ) : (
    <span className="ml-2">Ask your organization owner.</span>
  );

  if (!ent.active) {
    return (
      <div className="border-b border-amber-a/40 bg-amber-a/10 px-4 py-2 text-sm text-amber-a">
        {org?.name} is read-only until monitoring starts. Everything stays visible; changes are paused.
        {fixLink}
      </div>
    );
  }
  if (ent.over_by > 0) {
    return (
      <div className="border-b border-amber-a/40 bg-amber-a/10 px-4 py-2 text-sm text-amber-a">
        {ent.monitored} communities are monitored but the plan covers {ent.quantity}. Update the plan quantity to keep billing honest.
        {fixLink}
      </div>
    );
  }
  return null;
}
