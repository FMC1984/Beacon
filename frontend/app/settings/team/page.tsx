"use client";

import { useCallback, useEffect, useState } from "react";
import { useSession } from "@/components/SessionProvider";
import {
  changePassword,
  changeRole,
  createInvite,
  fetchMembers,
  removeMember,
  resetLinkFor,
  revokeInvite,
  ROLE_HELP,
  ROLE_LABELS,
  type MembersOut,
  type Role,
} from "@/lib/auth";

const ORG_ROLES: Exclude<Role, "none" | "platform_admin">[] = ["viewer", "admin", "owner"];

function CopyLink({ link }: { link: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="flex items-center gap-2">
      <code className="min-w-0 flex-1 truncate rounded-lg bg-surface-raised px-2 py-1 text-xs">{link}</code>
      <button
        type="button"
        onClick={() => {
          navigator.clipboard?.writeText(link).then(() => setCopied(true)).catch(() => {});
        }}
        className="rounded-lg border border-line px-2 py-1 text-xs hover:bg-surface-raised"
      >
        {copied ? "Copied" : "Copy"}
      </button>
    </div>
  );
}

export default function TeamPage() {
  const { me, org, role, isPlatformAdmin } = useSession();
  const canManage = isPlatformAdmin || role === "owner";
  const [data, setData] = useState<MembersOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<Role>("viewer");
  const [inviteBusy, setInviteBusy] = useState(false);
  const [lastInvite, setLastInvite] = useState<{ email: string; link: string; delivered: boolean; note: string } | null>(null);
  const [resetLinks, setResetLinks] = useState<Record<number, string>>({});
  const [pw, setPw] = useState({ current: "", next: "" });
  const [pwNote, setPwNote] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!org) return;
    fetchMembers(org.id).then(setData).catch((err) => setError((err as Error).message));
  }, [org]);

  useEffect(() => {
    load();
  }, [load]);

  async function sendInvite(e: React.FormEvent) {
    e.preventDefault();
    if (!org) return;
    setInviteBusy(true);
    setError(null);
    try {
      const r = await createInvite({ organization_id: org.id, email: inviteEmail, role: inviteRole });
      setLastInvite({ email: r.email, link: r.link, delivered: r.delivered, note: r.delivery_note });
      setInviteEmail("");
      load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setInviteBusy(false);
    }
  }

  async function act(fn: () => Promise<unknown>) {
    setError(null);
    try {
      await fn();
      load();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function savePassword(e: React.FormEvent) {
    e.preventDefault();
    setPwNote(null);
    try {
      await changePassword(pw.current, pw.next);
      setPw({ current: "", next: "" });
      setPwNote("Password changed. Other sessions were signed out.");
    } catch (err) {
      setPwNote((err as Error).message);
    }
  }

  if (!org) {
    return (
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold">Team</h1>
        <p className="text-sm text-muted">
          {isPlatformAdmin
            ? "Pick an organization in the sidebar to manage its team."
            : "Your account is not part of an organization yet. Ask for an invite link."}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold">Team</h1>
        <p className="mt-1 text-sm text-muted">
          Who can see and change {org.name}. You are {ROLE_LABELS[role].toLowerCase()} here.
        </p>
      </div>

      {error && <div className="rounded-xl border border-pink-a/40 bg-pink-a/10 px-4 py-3 text-sm text-pink-a">{error}</div>}

      <section className="rounded-2xl border border-line bg-surface p-5">
        <h2 className="text-base font-semibold">Members</h2>
        <div className="mt-3 divide-y divide-line/60">
          {data?.members.map((m) => {
            const isSelf = me?.user?.id === m.user_id;
            return (
              <div key={m.user_id} className="flex flex-wrap items-center gap-3 py-3">
                <div className="min-w-0 flex-1">
                  <div className="text-sm">{m.name || m.email}{isSelf && <span className="ml-2 text-xs text-muted">(you)</span>}</div>
                  <div className="text-xs text-muted">{m.email}{m.last_login_at ? ` · last sign-in ${new Date(m.last_login_at).toLocaleDateString()}` : " · never signed in"}</div>
                  {resetLinks[m.user_id] && <div className="mt-2"><CopyLink link={resetLinks[m.user_id]} /></div>}
                </div>
                {canManage ? (
                  <>
                    <select
                      value={m.role}
                      onChange={(e) => act(() => changeRole(org.id, m.user_id, e.target.value as Role))}
                      className="rounded-lg border border-line bg-surface-raised px-2 py-1 text-xs"
                      aria-label={`Role for ${m.email}`}
                    >
                      {ORG_ROLES.map((r) => <option key={r} value={r}>{ROLE_LABELS[r]}</option>)}
                    </select>
                    <button type="button" className="rounded-lg border border-line px-2 py-1 text-xs hover:bg-surface-raised"
                            onClick={() => act(async () => { const r = await resetLinkFor(m.user_id); setResetLinks((s) => ({ ...s, [m.user_id]: r.link })); })}>
                      Reset link
                    </button>
                    {!isSelf && (
                      <button type="button" className="rounded-lg border border-line px-2 py-1 text-xs text-pink-a hover:bg-surface-raised"
                              onClick={() => { if (confirm(`Remove ${m.email} from ${org.name}?`)) act(() => removeMember(org.id, m.user_id)); }}>
                        Remove
                      </button>
                    )}
                  </>
                ) : (
                  <span className="rounded-full bg-surface-raised px-2 py-0.5 text-xs text-muted">{ROLE_LABELS[m.role]}</span>
                )}
              </div>
            );
          })}
          {data && data.members.length === 0 && <p className="py-3 text-sm text-muted">No members yet.</p>}
        </div>
      </section>

      {canManage && (
        <section className="rounded-2xl border border-line bg-surface p-5">
          <h2 className="text-base font-semibold">Invite someone</h2>
          <p className="mt-1 text-xs text-muted">Invites are links. Copy the link and send it yourself unless email delivery is set up.</p>
          <form onSubmit={sendInvite} className="mt-3 flex flex-wrap gap-2">
            <label htmlFor="invite-email" className="sr-only">Email</label>
            <input id="invite-email" type="email" required value={inviteEmail} onChange={(e) => setInviteEmail(e.target.value)}
                   placeholder="person@company.com" className="min-w-[220px] flex-1 rounded-xl border border-line bg-surface-raised px-3 py-2 text-sm" />
            <label htmlFor="invite-role" className="sr-only">Role</label>
            <select id="invite-role" value={inviteRole} onChange={(e) => setInviteRole(e.target.value as Role)}
                    className="rounded-xl border border-line bg-surface-raised px-3 py-2 text-sm">
              {ORG_ROLES.map((r) => <option key={r} value={r}>{ROLE_LABELS[r]}</option>)}
            </select>
            <button disabled={inviteBusy || !inviteEmail} className="rounded-xl bg-violet-a px-4 py-2 text-sm font-medium text-background disabled:opacity-50">
              Create invite link
            </button>
          </form>
          <p className="mt-2 text-xs text-muted">{ROLE_HELP[inviteRole as keyof typeof ROLE_HELP]}</p>
          {lastInvite && (
            <div className="mt-3 space-y-2 rounded-xl border border-line bg-surface-raised/50 p-3">
              <div className="text-sm">Invite for {lastInvite.email}</div>
              <CopyLink link={lastInvite.link} />
              <div className="text-xs text-muted">{lastInvite.delivered ? "Sent by email." : lastInvite.note} Expires in 14 days.</div>
            </div>
          )}
          {data && data.pending_invites.length > 0 && (
            <div className="mt-4">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-muted">Pending</h3>
              <div className="mt-1 divide-y divide-line/60">
                {data.pending_invites.map((i) => (
                  <div key={i.invite_id} className="flex items-center gap-3 py-2 text-sm">
                    <span className="flex-1">{i.email} <span className="text-xs text-muted">as {ROLE_LABELS[i.role].toLowerCase()}, expires {new Date(i.expires_at).toLocaleDateString()}</span></span>
                    <button type="button" className="text-xs text-muted hover:text-pink-a" onClick={() => act(() => revokeInvite(i.invite_id))}>Revoke</button>
                  </div>
                ))}
              </div>
            </div>
          )}
        </section>
      )}

      {me?.user && (
        <section className="rounded-2xl border border-line bg-surface p-5">
          <h2 className="text-base font-semibold">Your password</h2>
          <form onSubmit={savePassword} className="mt-3 flex flex-wrap gap-2">
            <label htmlFor="pw-current" className="sr-only">Current password</label>
            <input id="pw-current" type="password" required autoComplete="current-password" value={pw.current}
                   onChange={(e) => setPw({ ...pw, current: e.target.value })} placeholder="Current password"
                   className="min-w-[200px] flex-1 rounded-xl border border-line bg-surface-raised px-3 py-2 text-sm" />
            <label htmlFor="pw-next" className="sr-only">New password</label>
            <input id="pw-next" type="password" required autoComplete="new-password" value={pw.next}
                   onChange={(e) => setPw({ ...pw, next: e.target.value })} placeholder="New password (10+ characters)"
                   className="min-w-[200px] flex-1 rounded-xl border border-line bg-surface-raised px-3 py-2 text-sm" />
            <button className="rounded-xl border border-line px-4 py-2 text-sm hover:bg-surface-raised">Change</button>
          </form>
          {pwNote && <p className="mt-2 text-xs text-muted">{pwNote}</p>}
        </section>
      )}
    </div>
  );
}
