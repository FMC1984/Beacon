"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { AuthCard, fieldClass, primaryButtonClass } from "@/components/AuthCard";
import { confirmReset, readReset } from "@/lib/auth";

export default function ResetPage() {
  const params = useParams<{ token: string }>();
  const token = params.token;
  const [state, setState] = useState<"checking" | "invalid" | "ready" | "done">("checking");
  const [email, setEmail] = useState<string | null>(null);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    readReset(token)
      .then((r) => {
        setEmail(r.email);
        setState(r.valid ? "ready" : "invalid");
      })
      .catch(() => setState("invalid"));
  }, [token]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (password !== confirm) {
      setError("The two passwords do not match.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await confirmReset(token, password);
      setState("done");
    } catch (err) {
      setError((err as Error).message || "Could not reset the password.");
    } finally {
      setBusy(false);
    }
  }

  if (state === "checking") return <AuthCard><p className="text-sm text-muted">Checking your link…</p></AuthCard>;
  if (state === "invalid") {
    return (
      <AuthCard title="Link not valid">
        <p className="text-sm text-muted">This reset link has expired or was already used. Ask for a new one.</p>
        <Link href="/login" className="block text-xs text-violet-a hover:underline">Go to sign in</Link>
      </AuthCard>
    );
  }
  if (state === "done") {
    return (
      <AuthCard title="Password updated">
        <p className="text-sm text-muted">Every other session for {email} has been signed out. Sign in with the new password.</p>
        <Link href="/login" className={`${primaryButtonClass} block text-center`}>Sign in</Link>
      </AuthCard>
    );
  }
  return (
    <AuthCard title="Choose a new password">
      <p className="text-sm text-muted">For {email}.</p>
      <form onSubmit={submit} className="space-y-3">
        <label htmlFor="reset-password" className="sr-only">New password</label>
        <input id="reset-password" type="password" required autoComplete="new-password" value={password}
               onChange={(e) => setPassword(e.target.value)} placeholder="New password (10+ characters)" className={fieldClass} autoFocus />
        <label htmlFor="reset-confirm" className="sr-only">Confirm password</label>
        <input id="reset-confirm" type="password" required autoComplete="new-password" value={confirm}
               onChange={(e) => setConfirm(e.target.value)} placeholder="Type it again" className={fieldClass} />
        {error && <p className="text-xs text-pink-a">{error}</p>}
        <button disabled={busy || !password || !confirm} className={primaryButtonClass}>{busy ? "Saving…" : "Set password"}</button>
      </form>
    </AuthCard>
  );
}
