"use client";

/** Signed-in session for the whole app.
 *
 * Every component talks to the API with plain fetch(`${API_BASE}...`), so the
 * session token and the acting organization are attached here once, at the
 * fetch layer. A 401 from the API signs the user out and sends them to /login.
 * Public paths (login, invite, reset, shared briefings) render without a session.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { usePathname } from "next/navigation";
import { API_BASE } from "@/lib/api";
import {
  clearSession,
  fetchMe,
  getOrg,
  getToken,
  isPublicPath,
  logoutRequest,
  setOrg as persistOrg,
  type Me,
  type OrgSummary,
  type Role,
} from "@/lib/auth";

type SessionState = {
  status: "checking" | "anonymous" | "ready";
  me: Me | null;
  org: OrgSummary | null;
  role: Role;
  isPlatformAdmin: boolean;
  orgs: OrgSummary[];
  setOrg: (orgId: number | null) => void;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
};

const SessionContext = createContext<SessionState | null>(null);

let patched = false;
function patchFetch() {
  if (patched || typeof window === "undefined") return;
  patched = true;
  const original = window.fetch.bind(window);
  window.fetch = async (input, init = {}) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
    const isApi = url.startsWith(API_BASE);
    if (isApi) {
      const headers: Record<string, string> = { ...((init.headers as Record<string, string>) || {}) };
      const token = getToken();
      const org = getOrg();
      if (token && !headers.Authorization) headers.Authorization = `Bearer ${token}`;
      if (org && !headers["X-CiteRoll-Org"]) headers["X-CiteRoll-Org"] = org;
      init = { ...init, headers };
    }
    const res = await original(input, init);
    if (isApi && res.status === 401 && !url.includes("/auth/login") && !url.includes("/auth/invites") && !url.includes("/auth/reset")) {
      const hadToken = Boolean(getToken());
      clearSession();
      if (hadToken && !isPublicPath(window.location.pathname)) {
        const next = encodeURIComponent(window.location.pathname + window.location.search);
        window.location.assign(`/login?next=${next}`);
      }
    }
    return res;
  };
}

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  // Public paths never wait on a session; their rendered output is the same on
  // the server and the client, so the differing initial state is harmless.
  const [status, setStatus] = useState<SessionState["status"]>(() =>
    typeof window !== "undefined" && isPublicPath(window.location.pathname) ? "ready" : "checking",
  );
  const [me, setMe] = useState<Me | null>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await fetchMe();
      setMe(data);
      setStatus("ready");
    } catch (err) {
      const status = (err as { status?: number }).status;
      if (status === 401) {
        setMe(null);
        setStatus("anonymous");
      } else {
        // API unreachable: let pages render their own connection errors.
        setMe(null);
        setStatus("ready");
      }
    }
  }, []);

  useEffect(() => {
    patchFetch();
    if (!isPublicPath(window.location.pathname)) queueMicrotask(refresh);
  }, [refresh]);

  useEffect(() => {
    if (status === "anonymous" && !isPublicPath(pathname)) {
      const next = encodeURIComponent(pathname);
      window.location.assign(`/login?next=${next}`);
    }
  }, [status, pathname]);

  const setOrg = useCallback((orgId: number | null) => {
    persistOrg(orgId);
    window.location.reload();
  }, []);

  const logout = useCallback(async () => {
    try {
      await logoutRequest();
    } catch {}
    clearSession();
    window.location.assign("/login");
  }, []);

  const value = useMemo<SessionState>(
    () => ({
      status,
      me,
      org: me?.org ?? null,
      role: me?.org?.role ?? (me?.is_platform_admin ? "platform_admin" : "none"),
      isPlatformAdmin: me?.is_platform_admin ?? false,
      orgs: me?.organizations ?? [],
      setOrg,
      logout,
      refresh,
    }),
    [status, me, setOrg, logout, refresh],
  );

  if (isPublicPath(pathname)) {
    return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
  }
  if (status === "checking") {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-muted">Connecting to CiteRoll…</div>
    );
  }
  if (status === "anonymous") {
    return <div className="flex min-h-screen items-center justify-center text-sm text-muted">Redirecting to sign in…</div>;
  }
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionState {
  const ctx = useContext(SessionContext);
  if (!ctx) {
    return {
      status: "ready",
      me: null,
      org: null,
      role: "none",
      isPlatformAdmin: false,
      orgs: [],
      setOrg: () => {},
      logout: async () => {},
      refresh: async () => {},
    };
  }
  return ctx;
}
