import { API_BASE, SCOPE_STORAGE_KEY } from "@/lib/api";

// The session token and the organization the user is acting as. Both live in
// localStorage and are attached to every API call by SessionProvider's fetch
// patch, so no call site needs to know about them.
export const SESSION_KEY = "citeroll.session";
export const ORG_KEY = "citeroll.org";

export type Role = "none" | "viewer" | "admin" | "owner" | "platform_admin";

export type OrgSummary = { id: number; name: string; slug: string; role: Role; sample_data: boolean };

export type Membership = {
  organization_id: number;
  organization_name: string;
  organization_slug: string;
  role: Role;
  sample_data: boolean;
};

export type Me = {
  user: { id: number; email: string; name: string | null; is_platform_admin: boolean; last_login_at: string | null } | null;
  via: "session" | "access_key" | "open";
  is_platform_admin: boolean;
  org: OrgSummary | null;
  memberships: Membership[];
  organizations: OrgSummary[];
};

export type LoginResult = Me & { token: string };

export type InvitePublic = {
  organization_name: string;
  email: string;
  role: Role;
  state: "open" | "expired" | "accepted";
  existing_user: boolean;
};

export type InviteOut = {
  invite_id: number;
  email: string;
  role: Role;
  organization_id: number;
  link: string;
  expires_at: string;
  delivered: boolean;
  delivery_note: string;
};

export type MembersOut = {
  organization_id: number;
  members: { user_id: number; email: string; name: string | null; role: Role; last_login_at: string | null }[];
  pending_invites: { invite_id: number; email: string; role: Role; expires_at: string }[];
};

export const PUBLIC_PREFIXES = ["/login", "/invite/", "/reset/", "/shared/"];

export function isPublicPath(pathname: string) {
  return PUBLIC_PREFIXES.some((p) => pathname === p || pathname.startsWith(p));
}

function read(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string | null) {
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch {}
}

export const getToken = () => read(SESSION_KEY);
export const getOrg = () => read(ORG_KEY);

/** The selected company belongs to whoever was signed in. Leaving it behind
 * makes the next person request a company they cannot see, so every session
 * change drops it; the sidebar's own collapse state is not user data and stays. */
function clearViewScope() {
  write(SCOPE_STORAGE_KEY, null);
}

export function setSession(token: string) {
  write(SESSION_KEY, token);
  clearViewScope();
}

export function setOrg(orgId: number | null) {
  write(ORG_KEY, orgId === null ? null : String(orgId));
  // A company belongs to one organization, so switching organizations
  // invalidates the selection the same way signing in does.
  clearViewScope();
}

export function clearSession() {
  write(SESSION_KEY, null);
  write(ORG_KEY, null);
  clearViewScope();
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function authJSON<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    cache: "no-store",
    ...init,
    headers: { "Content-Type": "application/json", ...(init.headers || {}) },
  });
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
      else if (Array.isArray(body?.detail) && body.detail[0]?.msg) detail = body.detail[0].msg;
    } catch {}
    throw new ApiError(res.status, detail);
  }
  return res.json();
}

const post = <T,>(path: string, body: unknown) =>
  authJSON<T>(path, { method: "POST", body: JSON.stringify(body) });

export const login = (email: string, password: string) => post<LoginResult>("/auth/login", { email, password });
export const logoutRequest = () => authJSON<{ status: string }>("/auth/logout", { method: "POST" });
export const fetchMe = () => authJSON<Me>("/auth/me");
export const changePassword = (current_password: string, new_password: string) =>
  post<{ status: string }>("/auth/password", { current_password, new_password });

export const readInvite = (token: string) => authJSON<InvitePublic>(`/auth/invites/${token}`);
export const acceptInvite = (token: string, body: { name?: string; password: string }) =>
  post<LoginResult>(`/auth/invites/${token}/accept`, body);
export const createInvite = (body: { organization_id: number; email: string; role: Role }) =>
  post<InviteOut>("/auth/invites", body);
export const revokeInvite = (inviteId: number) =>
  authJSON<{ status: string }>(`/auth/invites/${inviteId}`, { method: "DELETE" });

export const requestReset = (email: string) => post<{ status: string; delivered: boolean; note: string }>("/auth/reset/request", { email });
export const readReset = (token: string) => authJSON<{ valid: boolean; email: string | null }>(`/auth/reset/${token}`);
export const confirmReset = (token: string, password: string) =>
  post<{ status: string; email: string }>(`/auth/reset/${token}/confirm`, { password });
export const resetLinkFor = (userId: number) =>
  authJSON<{ link: string; delivered: boolean; delivery_note: string; email: string }>(`/auth/users/${userId}/reset-link`, { method: "POST" });

export const fetchMembers = (orgId: number) => authJSON<MembersOut>(`/auth/orgs/${orgId}/members`);
export const changeRole = (orgId: number, userId: number, role: Role) =>
  authJSON<{ role: Role }>(`/auth/orgs/${orgId}/members/${userId}`, { method: "PATCH", body: JSON.stringify({ role }) });
export const removeMember = (orgId: number, userId: number) =>
  authJSON<{ status: string }>(`/auth/orgs/${orgId}/members/${userId}`, { method: "DELETE" });

export const ROLE_LABELS: Record<Role, string> = {
  none: "No organization",
  viewer: "Viewer",
  admin: "Admin",
  owner: "Owner",
  platform_admin: "Platform admin",
};

export const ROLE_HELP: Record<Exclude<Role, "none" | "platform_admin">, string> = {
  viewer: "Reads everything, opens briefings. Cannot change anything.",
  admin: "Edits properties, facts, competitors, prompts and uploads.",
  owner: "Everything an admin can do, plus team and billing.",
};
