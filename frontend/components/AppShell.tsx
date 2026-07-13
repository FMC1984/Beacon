"use client";

/** App chrome. On desktop the sidebar is a sticky column; on mobile it becomes
 * an off-canvas drawer opened from a top bar, so the nav never eats the phone
 * screen. Content padding tightens on small screens. */

import { useEffect, useState } from "react";
import Image from "next/image";
import { usePathname } from "next/navigation";
import { Sidebar } from "./Sidebar";

function MenuIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="h-6 w-6" aria-hidden>
      <path d="M3 6h18M3 12h18M3 18h18" />
    </svg>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();

  // Close the drawer on navigation.
  useEffect(() => {
    setOpen(false);
  }, [pathname]);

  // Lock body scroll while the drawer is open.
  useEffect(() => {
    document.body.style.overflow = open ? "hidden" : "";
    return () => {
      document.body.style.overflow = "";
    };
  }, [open]);

  // Public share routes (Phase 17D) render bare: no sidebar, no app chrome.
  if (pathname.startsWith("/shared/")) {
    return <>{children}</>;
  }

  return (
    <div className="flex min-h-screen">
      <div className="hidden md:flex">
        <Sidebar />
      </div>

      <div
        className={`fixed inset-0 z-50 md:hidden ${open ? "" : "pointer-events-none"}`}
        aria-hidden={!open}
      >
        <div
          className={`absolute inset-0 bg-black/50 transition-opacity duration-200 ${open ? "opacity-100" : "opacity-0"}`}
          onClick={() => setOpen(false)}
        />
        <div
          role="dialog"
          aria-label="Navigation"
          className={`absolute left-0 top-0 flex h-full w-64 max-w-[82%] flex-col border-r border-line bg-surface transition-transform duration-200 ${open ? "translate-x-0" : "-translate-x-full"}`}
        >
          <div className="flex h-14 shrink-0 items-center justify-between border-b border-line px-4">
            <Image src="/beacon-logo.png" alt="Beacon" width={120} height={24} className="h-6 w-auto" />
            <button
              onClick={() => setOpen(false)}
              aria-label="Close menu"
              className="rounded-lg p-1 text-muted hover:bg-surface-raised hover:text-foreground"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="h-5 w-5" aria-hidden>
                <path d="M18 6 6 18M6 6l12 12" />
              </svg>
            </button>
          </div>
          <Sidebar mobile onNavigate={() => setOpen(false)} />
        </div>
      </div>

      <main className="min-w-0 flex-1">
        <div className="sticky top-0 z-30 flex items-center gap-3 border-b border-line bg-surface/80 px-4 py-2.5 backdrop-blur md:hidden">
          <button
            onClick={() => setOpen(true)}
            aria-label="Open menu"
            className="rounded-lg p-1 text-foreground hover:bg-surface-raised"
          >
            <MenuIcon />
          </button>
          <Image src="/beacon-logo.png" alt="Beacon" width={110} height={22} className="h-5 w-auto" />
        </div>

        <div className="mx-auto max-w-6xl px-4 py-6 md:px-8 md:py-8">{children}</div>
      </main>
    </div>
  );
}
