"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

function Icon({ children }: { children: ReactNode }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="h-[18px] w-[18px] shrink-0"
      aria-hidden
    >
      {children}
    </svg>
  );
}

const ICONS: Record<string, ReactNode> = {
  dashboard: <><rect x="3" y="3" width="7" height="9" /><rect x="14" y="3" width="7" height="5" /><rect x="14" y="12" width="7" height="9" /><rect x="3" y="16" width="7" height="5" /></>,
  opportunities: <><path d="M9 11l3 3L22 4" /><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" /></>,
  visibility: <><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z" /><circle cx="12" cy="12" r="3" /></>,
  signals: <><path d="M3 12h4l3 8 4-16 3 8h4" /></>,
  competitors: <><circle cx="9" cy="7" r="3" /><path d="M2 21v-1a5 5 0 0 1 5-5h4a5 5 0 0 1 5 5v1" /><circle cx="18" cy="7" r="2.5" /><path d="M22 21v-1a4 4 0 0 0-3-3.9" /></>,
  content: <><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z" /><path d="M14 2v6h6" /><path d="M8 13h8M8 17h6" /></>,
  reviews: <><path d="m12 3 2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9 6.8 19.1l1-5.8L3.5 9.2l5.9-.9Z" /></>,
  context: <><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z" /><path d="M12 8v4M12 16h.01" /></>,
  nora: <><path d="M12 3l1.6 4.4L18 9l-4.4 1.6L12 15l-1.6-4.4L6 9l4.4-1.6Z" /><path d="M19 14l.7 1.8L21.5 17l-1.8.7L19 19.5l-.7-1.8L16.5 17l1.8-.7Z" /></>,
  properties: <><path d="M3 21h18" /><path d="M5 21V7l8-4v18" /><path d="M19 21V11l-6-4" /><path d="M9 9v.01M9 12v.01M9 15v.01M9 18v.01" /></>,
  uploads: <><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><path d="M17 8l-5-5-5 5" /><path d="M12 3v12" /></>,
  admin: <><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1Z" /></>,
};

type Item = { href: string; label: string; icon: keyof typeof ICONS };
type Group = { label: string; items: Item[] };

const GROUPS: Group[] = [
  {
    label: "Overview",
    items: [
      { href: "/", label: "Dashboard", icon: "dashboard" },
      { href: "/opportunities", label: "Opportunities", icon: "opportunities" },
    ],
  },
  {
    label: "AI Intelligence",
    items: [
      { href: "/ai-visibility", label: "AI Visibility", icon: "visibility" },
      { href: "/ai-query-signals", label: "AI Query Signals", icon: "signals" },
      { href: "/competitors", label: "Competitor IQ", icon: "competitors" },
    ],
  },
  {
    label: "Content & Reviews",
    items: [
      { href: "/content-intelligence", label: "Content IQ", icon: "content" },
      { href: "/review-intelligence", label: "Review IQ", icon: "reviews" },
      { href: "/property-context", label: "Context", icon: "context" },
    ],
  },
  { label: "Assistant", items: [{ href: "/nora", label: "Nora", icon: "nora" }] },
  {
    label: "Data",
    items: [
      { href: "/properties", label: "Properties", icon: "properties" },
      { href: "/uploads", label: "Uploads", icon: "uploads" },
    ],
  },
  { label: "System", items: [{ href: "/admin", label: "Admin", icon: "admin" }] },
];

const COLLAPSE_KEY = "beacon.sidebarCollapsed";
const GROUPS_KEY = "beacon.sidebarGroups";

function isActive(pathname: string, href: string) {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(href + "/");
}

function Chevron({ dir }: { dir: "left" | "right" | "down" }) {
  const d =
    dir === "left" ? "m15 18-6-6 6-6" : dir === "right" ? "m9 18 6-6-6-6" : "m6 9 6 6 6-6";
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
      strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4" aria-hidden>
      <path d={d} />
    </svg>
  );
}

export function Sidebar() {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const [closedGroups, setClosedGroups] = useState<Record<string, boolean>>({});

  // Restore persisted state after mount (avoids SSR hydration mismatch).
  useEffect(() => {
    try {
      setCollapsed(localStorage.getItem(COLLAPSE_KEY) === "1");
      const raw = localStorage.getItem(GROUPS_KEY);
      if (raw) setClosedGroups(JSON.parse(raw));
    } catch {}
  }, []);

  function toggleCollapsed() {
    setCollapsed((c) => {
      const next = !c;
      try {
        localStorage.setItem(COLLAPSE_KEY, next ? "1" : "0");
      } catch {}
      return next;
    });
  }

  function toggleGroup(label: string) {
    setClosedGroups((g) => {
      const next = { ...g, [label]: !g[label] };
      try {
        localStorage.setItem(GROUPS_KEY, JSON.stringify(next));
      } catch {}
      return next;
    });
  }

  return (
    <aside
      className={`sticky top-0 flex h-screen shrink-0 flex-col border-r border-line bg-surface/40 transition-[width] duration-200 ${
        collapsed ? "w-16" : "w-60"
      }`}
    >
      {/* Floating handle sitting on the divider line, near the top. */}
      <button
        onClick={toggleCollapsed}
        aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        title={collapsed ? "Expand" : "Collapse"}
        className="absolute -right-3 top-16 z-30 flex h-6 w-6 items-center justify-center rounded-full border border-line bg-surface text-muted shadow-sm transition-colors hover:border-violet-a/50 hover:text-foreground"
      >
        <Chevron dir={collapsed ? "right" : "left"} />
      </button>

      <div className={`flex h-14 items-center ${collapsed ? "justify-center px-0" : "px-3"}`}>
        <Link
          href="/"
          className={`flex items-center ${collapsed ? "" : "px-2"}`}
          aria-label="Beacon home"
        >
          {collapsed ? (
            <Image src="/beacon-mark.png" alt="Beacon" width={28} height={28} priority className="h-7 w-7 shrink-0" />
          ) : (
            <Image src="/beacon-logo.png" alt="Beacon" width={130} height={26} priority className="h-6 w-auto shrink-0" />
          )}
        </Link>
      </div>

      <nav className={`flex-1 space-y-4 overflow-y-auto pb-4 pt-1 ${collapsed ? "px-2" : "px-3"}`}>
        {GROUPS.map((group, gi) => {
          const closed = !collapsed && closedGroups[group.label];
          return (
            <div key={group.label} className={collapsed && gi > 0 ? "border-t border-line/60 pt-3" : ""}>
              {!collapsed && (
                <button
                  onClick={() => toggleGroup(group.label)}
                  aria-expanded={!closed}
                  className="flex w-full items-center justify-between px-3 pb-1 text-[11px] font-semibold uppercase tracking-wider text-muted/70 transition-colors hover:text-muted"
                >
                  {group.label}
                  <span className={`transition-transform ${closed ? "-rotate-90" : ""}`}>
                    <Chevron dir="down" />
                  </span>
                </button>
              )}
              {!closed && (
                <div className="space-y-0.5">
                  {group.items.map((item) => {
                    const active = isActive(pathname, item.href);
                    return (
                      <Link
                        key={item.href}
                        href={item.href}
                        aria-current={active ? "page" : undefined}
                        title={collapsed ? item.label : undefined}
                        className={`flex items-center gap-3 rounded-lg py-2 text-sm transition-colors ${
                          collapsed ? "justify-center px-0" : "px-3"
                        } ${
                          active
                            ? "bg-violet-a/15 font-medium text-foreground"
                            : "text-muted hover:bg-surface-raised hover:text-foreground"
                        }`}
                      >
                        <span className={active ? "text-violet-a" : ""}>
                          <Icon>{ICONS[item.icon]}</Icon>
                        </span>
                        {!collapsed && item.label}
                      </Link>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </nav>

    </aside>
  );
}
