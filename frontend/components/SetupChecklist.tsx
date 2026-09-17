"use client";

/** Property setup checklist: six dependency-ordered steps from
 * GET /api/properties/{id}/setup. Two renderings share one fetch:
 *
 *   SetupChecklist  the full card on the property dashboard
 *   SetupBanner     one line on AI Visibility and Reports when a step is
 *                   missing: what is next and where to do it
 *
 * State is only set from the promise callbacks. */

import Link from "next/link";
import { useEffect, useState } from "react";
import { fetchPropertySetup, type PropertySetup, type SetupStep } from "@/lib/api";

export function useSetup(propertyId: number | null) {
  const [setup, setSetup] = useState<PropertySetup | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (propertyId === null) return;
    let live = true;
    fetchPropertySetup(propertyId)
      .then((s) => {
        if (live) setSetup(s);
      })
      .catch((e: Error) => {
        if (live) setError(e.message);
      });
    return () => {
      live = false;
    };
  }, [propertyId]);
  return { setup: setup && setup.property_id === propertyId ? setup : null, error };
}

function StepRow({ step, index, isNext }: { step: SetupStep; index: number; isNext: boolean }) {
  return (
    <li className={`flex gap-3 rounded-xl px-3 py-2.5 ${isNext ? "bg-violet-a/10" : ""}`}>
      <span
        className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-xs font-medium ${
          step.done ? "bg-emerald-500/20 text-emerald-300" : isNext ? "bg-violet-a text-background" : "bg-surface-raised text-muted"
        }`}
        aria-label={step.done ? "done" : "not done"}
      >
        {step.done ? "✓" : index + 1}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
          <span className="text-sm font-medium">{step.label}</span>
          <Link href={step.href} className="text-xs text-violet-a hover:underline">
            {step.done ? "Review" : isNext ? "Do this next" : "Open"} ›
          </Link>
        </div>
        <p className="text-xs text-muted">{step.detail}</p>
        {!step.done && step.missing.length > 0 && (
          <ul className="mt-1 list-disc pl-4 text-xs text-foreground/80">
            {step.missing.map((m) => (
              <li key={m}>{m}</li>
            ))}
          </ul>
        )}
        {step.optional_hints.length > 0 && (
          <ul className="mt-1 pl-0 text-[11px] text-muted">
            {step.optional_hints.map((h) => (
              <li key={h}>Optional: {h}</li>
            ))}
          </ul>
        )}
        <p className="mt-1 text-[11px] text-muted">Unlocks: {step.unlocks}</p>
      </div>
    </li>
  );
}

export function SetupChecklist({ propertyId }: { propertyId: number }) {
  const { setup, error } = useSetup(propertyId);
  const [expanded, setExpanded] = useState(false);
  if (error) return <p className="text-sm text-rose-300">Could not load the setup checklist: {error}</p>;
  if (!setup) return null;
  if (setup.complete && setup.is_sample) return null;
  if (setup.complete && !expanded) {
    return (
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-2xl border border-line bg-surface px-4 py-2.5 text-sm">
        <span>
          <span className="font-medium">Setup complete.</span>{" "}
          <span className="text-muted">Identity, data, facts, competitors, prompts and monitoring are all in place.</span>
        </span>
        <button type="button" onClick={() => setExpanded(true)} className="text-xs text-violet-a hover:underline">
          Review steps ›
        </button>
      </div>
    );
  }
  return (
    <section className="rounded-2xl border border-line bg-surface p-5">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-sm font-medium">{setup.complete ? "Setup complete" : "Set up this property"}</h2>
          <p className="text-xs text-muted">
            {setup.complete
              ? "Every stage of the flow has what it needs. Revisit a step to change it."
              : `${setup.done} of ${setup.total} steps done. Each step unlocks the pages after it.`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {setup.complete && (
            <button type="button" onClick={() => setExpanded(false)} className="mr-2 text-xs text-muted hover:underline">
              Collapse
            </button>
          )}
          <div className="h-2 w-32 overflow-hidden rounded-full bg-surface-raised" aria-hidden>
            <div className="h-full rounded-full bg-violet-a" style={{ width: `${setup.percent}%` }} />
          </div>
          <span className="text-xs tabular-nums text-muted">{setup.percent}%</span>
        </div>
      </div>
      <ol className="space-y-1">
        {setup.steps.map((s, i) => (
          <StepRow key={s.key} step={s} index={i} isNext={setup.next?.key === s.key} />
        ))}
      </ol>
    </section>
  );
}

export function SetupBanner({ propertyId, requires }: { propertyId: number | null; requires?: string[] }) {
  const { setup } = useSetup(propertyId);
  if (!setup || setup.complete || setup.is_sample) return null;
  const relevant = requires ? setup.steps.filter((s) => requires.includes(s.key) && !s.done) : [];
  const step = relevant[0] ?? setup.next;
  if (!step) return null;
  return (
    <div role="note" className="flex flex-wrap items-center justify-between gap-2 rounded-2xl border border-violet-a/40 bg-violet-a/10 px-4 py-3 text-sm">
      <span>
        <span className="font-semibold">Finish setup ({setup.done} of {setup.total}).</span>{" "}
        <span className="text-foreground/80">
          Next: {step.label.toLowerCase()}. {(step.missing[0] ?? step.detail).replace(/\.?$/, ".")} This unlocks{" "}
          {step.unlocks.toLowerCase()}.
        </span>
      </span>
      <span className="flex gap-3 text-xs">
        <Link href={step.href} className="font-medium text-violet-a hover:underline">
          {step.label} ›
        </Link>
        <Link href={`/properties/${propertyId}`} className="text-muted hover:underline">
          Full checklist
        </Link>
      </span>
    </div>
  );
}
