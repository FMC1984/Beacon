import { API_BASE } from "@/lib/api";
import { ApiError } from "@/lib/auth";

export type Entitlement = {
  organization_id: number;
  active: boolean;
  source: "subscription" | "override" | "sample" | "none";
  plan: "standard" | "advanced" | null;
  status: string | null;
  quantity: number;
  monitored: number;
  over_by: number;
  under_by: number;
  override: boolean;
  override_reason: string | null;
  current_period_end: string | null;
  cancel_at_period_end: boolean;
  configured: boolean;
  subscription_id: string | null;
};

export type BillingStatus = {
  configured: boolean;
  organization_id: number | null;
  entitlement: Entitlement | null;
  has_customer?: boolean;
  prices: { standard: boolean; advanced: boolean; audit: boolean };
  auto_quantity?: boolean;
  note?: string;
};

async function billingJSON<T>(path: string, init: RequestInit = {}): Promise<T> {
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
      else if (body?.detail?.message) detail = body.detail.message;
    } catch {}
    throw new ApiError(res.status, detail);
  }
  return res.json();
}

export const fetchBillingStatus = () => billingJSON<BillingStatus>("/billing/status");
export const startCheckout = (product: "standard" | "advanced" | "audit", quantity?: number) =>
  billingJSON<{ url: string; mode: string; quantity: number }>("/billing/checkout", {
    method: "POST",
    body: JSON.stringify({ product, quantity }),
  });
export const openPortal = () => billingJSON<{ url: string }>("/billing/portal", { method: "POST" });
export const syncQuantity = () => billingJSON<{ quantity: number; note: string }>("/billing/sync-quantity", { method: "POST" });

export const PLAN_LABELS: Record<string, string> = {
  standard: "Standard monitoring",
  advanced: "Advanced monitoring",
  audit: "AI Visibility Audit",
};
