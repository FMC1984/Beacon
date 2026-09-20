"use client";

import Image from "next/image";
import { BeaconSweep } from "@/components/BeaconSweep";

/** The centered card used by sign-in, invite and reset screens. */
export function AuthCard({ title, children }: { title?: string; children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="relative w-full max-w-sm space-y-4 overflow-hidden rounded-2xl border border-line bg-surface p-6">
        <BeaconSweep className="opacity-70" />
        <div className="relative">
          <Image src="/beacon-logo.png" alt="Beacon" width={130} height={26} priority className="h-7 w-auto" />
          {title && <h1 className="mt-3 text-lg font-semibold">{title}</h1>}
        </div>
        <div className="relative space-y-4">{children}</div>
      </div>
    </div>
  );
}

export const fieldClass = "w-full rounded-xl border border-line bg-surface-raised px-3 py-2 text-sm";
export const primaryButtonClass =
  "w-full rounded-xl bg-violet-a px-4 py-2 text-sm font-medium text-background disabled:opacity-50";
