"use client";

import { useState } from "react";
import { AuthCard, fieldClass, primaryButtonClass } from "@/components/AuthCard";
import { login, requestReset, setOrg, setSession } from "@/lib/auth";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [forgot, setForgot] = useState(false);
  const [resetNote, setResetNote] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await login(email, password);
      setSession(result.token);
      setOrg(result.org?.id ?? null);
      const params = new URLSearchParams(window.location.search);
      const next = params.get("next");
      window.location.assign(next && next.startsWith("/") ? next : "/");
    } catch (err) {
      setError((err as Error).message || "Could not sign in.");
      setBusy(false);
    }
  }

  async function sendReset(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await requestReset(email);
      setResetNote(r.note);
    } catch (err) {
      setError((err as Error).message || "Could not request a reset.");
    } finally {
      setBusy(false);
    }
  }

  if (forgot) {
    return (
      <AuthCard title="Reset your password">
        <form onSubmit={sendReset} className="space-y-3">
          <p className="text-sm text-muted">
            Enter your email. If email is set up you will get a link; otherwise ask your organization owner for one.
          </p>
          <label htmlFor="reset-email" className="sr-only">Email</label>
          <input id="reset-email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)}
                 placeholder="you@company.com" className={fieldClass} autoFocus />
          {resetNote && <p className="text-xs text-muted">{resetNote}</p>}
          {error && <p className="text-xs text-pink-a">{error}</p>}
          <button disabled={busy || !email} className={primaryButtonClass}>Send reset link</button>
          <button type="button" onClick={() => setForgot(false)} className="w-full text-xs text-muted hover:text-foreground">
            Back to sign in
          </button>
        </form>
      </AuthCard>
    );
  }

  return (
    <AuthCard title="Sign in">
      <form onSubmit={submit} className="space-y-3">
        <label htmlFor="login-email" className="sr-only">Email</label>
        <input id="login-email" type="email" required autoComplete="email" value={email}
               onChange={(e) => setEmail(e.target.value)} placeholder="you@company.com" className={fieldClass} autoFocus />
        <label htmlFor="login-password" className="sr-only">Password</label>
        <input id="login-password" type="password" required autoComplete="current-password" value={password}
               onChange={(e) => setPassword(e.target.value)} placeholder="Password" className={fieldClass} />
        {error && <p className="text-xs text-pink-a">{error}</p>}
        <button disabled={busy || !email || !password} className={primaryButtonClass}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
        <button type="button" onClick={() => setForgot(true)} className="w-full text-xs text-muted hover:text-foreground">
          Forgot your password?
        </button>
        <p className="text-xs text-muted">Accounts are created by invitation. Ask your organization owner for an invite link.</p>
      </form>
    </AuthCard>
  );
}
