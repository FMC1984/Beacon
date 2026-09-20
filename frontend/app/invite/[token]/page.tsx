"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { AuthCard, fieldClass, primaryButtonClass } from "@/components/AuthCard";
import { acceptInvite, readInvite, setOrg, setSession, type InvitePublic, ROLE_LABELS } from "@/lib/auth";

export default function InvitePage() {
  const params = useParams<{ token: string }>();
  const token = params.token;
  const [invite, setInvite] = useState<InvitePublic | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    readInvite(token)
      .then(setInvite)
      .catch((err) => setLoadError((err as Error).message || "This invite link is not valid."));
  }, [token]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await acceptInvite(token, invite?.existing_user ? { password } : { name, password });
      setSession(result.token);
      setOrg(result.org?.id ?? null);
      window.location.assign("/");
    } catch (err) {
      setError((err as Error).message || "Could not accept the invite.");
      setBusy(false);
    }
  }

  if (loadError) {
    return (
      <AuthCard title="Invite not found">
        <p className="text-sm text-muted">{loadError}</p>
        <Link href="/login" className="block text-xs text-violet-a hover:underline">Go to sign in</Link>
      </AuthCard>
    );
  }
  if (!invite) {
    return <AuthCard><p className="text-sm text-muted">Checking your invite…</p></AuthCard>;
  }
  if (invite.state !== "open") {
    return (
      <AuthCard title={invite.state === "accepted" ? "Already accepted" : "Invite expired"}>
        <p className="text-sm text-muted">
          {invite.state === "accepted"
            ? "This invite has already been used. Sign in with your email and password."
            : "This invite has expired. Ask your organization owner for a new one."}
        </p>
        <Link href="/login" className="block text-xs text-violet-a hover:underline">Go to sign in</Link>
      </AuthCard>
    );
  }

  return (
    <AuthCard title={`Join ${invite.organization_name}`}>
      <p className="text-sm text-muted">
        You are invited as <span className="text-foreground">{ROLE_LABELS[invite.role]}</span> for{" "}
        <span className="text-foreground">{invite.email}</span>.
      </p>
      <form onSubmit={submit} className="space-y-3">
        {!invite.existing_user && (
          <>
            <label htmlFor="invite-name" className="sr-only">Your name</label>
            <input id="invite-name" required value={name} onChange={(e) => setName(e.target.value)} placeholder="Your name"
                   className={fieldClass} autoFocus />
          </>
        )}
        <label htmlFor="invite-password" className="sr-only">Password</label>
        <input id="invite-password" type="password" required autoComplete={invite.existing_user ? "current-password" : "new-password"}
               value={password} onChange={(e) => setPassword(e.target.value)}
               placeholder={invite.existing_user ? "Your existing password" : "Choose a password (10+ characters)"}
               className={fieldClass} autoFocus={invite.existing_user} />
        {invite.existing_user && (
          <p className="text-xs text-muted">This email already has an account. Enter its password to add this organization to it.</p>
        )}
        {error && <p className="text-xs text-pink-a">{error}</p>}
        <button disabled={busy || !password || (!invite.existing_user && !name)} className={primaryButtonClass}>
          {busy ? "Joining…" : "Accept invite"}
        </button>
      </form>
    </AuthCard>
  );
}
