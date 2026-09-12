"use client";

/** Standing prompts and the visibility score history (moved from the
 * pre-Observatory AI Visibility page). */

import { useCallback, useEffect, useState } from "react";
import { API_BASE } from "@/lib/api";
import { pct, fmtWhen } from "./shared";

type StandingPrompt = { id: number; prompt_text: string; platform: string; active: boolean; cadence?: string; volatile?: boolean; owning_url?: string | null };
type ScorePoint = {
  captured_at: string;
  score: number | null;
  sample_size: number;
  mention_rate: number | null;
};

export function StandingPanel({ propertyId }: { propertyId: number }) {
  const [prompts, setPrompts] = useState<StandingPrompt[]>([]);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [history, setHistory] = useState<ScorePoint[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(() => {
    fetch(`${API_BASE}/ai-visibility/${propertyId}/prompts`)
      .then((r) => r.json())
      .then((b) => setPrompts(b.prompts ?? []))
      .catch(() => {});
    fetch(`${API_BASE}/ai-visibility/${propertyId}/prompt-suggestions`)
      .then((r) => r.json())
      .then((b) => setSuggestions(b.suggestions ?? []))
      .catch(() => {});
    fetch(`${API_BASE}/ai-visibility/${propertyId}/score-history`)
      .then((r) => r.json())
      .then((b) => setHistory(b.history ?? []))
      .catch(() => {});
  }, [propertyId]);

  useEffect(load, [load]);

  async function add(text: string) {
    if (!text.trim()) return;
    await fetch(`${API_BASE}/ai-visibility/${propertyId}/prompts`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt_text: text.trim() }),
    });
    setDraft("");
    load();
  }

  async function remove(id: number) {
    await fetch(`${API_BASE}/ai-visibility/${propertyId}/prompts/${id}`, { method: "DELETE" });
    load();
  }

  async function importSet(file: File) {
    setBusy(true);
    setNote(null);
    try {
      const payload = JSON.parse(await file.text());
      const res = await fetch(`${API_BASE}/ai-visibility/${propertyId}/import-question-set`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const b = await res.json();
      if (!res.ok) {
        setNote({ ok: false, text: b.detail ?? "Import failed." });
      } else {
        setNote({
          ok: true,
          text: `Imported: ${b.prompts_created} new prompt(s), ${b.prompts_updated} updated` +
            (b.competitors_created?.length ? `, competitors added: ${b.competitors_created.join(", ")}.` : "."),
        });
      }
    } catch {
      setNote({ ok: false, text: "Could not read that file as question-set JSON." });
    } finally {
      setBusy(false);
      load();
    }
  }

  async function runNow() {
    setBusy(true);
    setNote(null);
    try {
      const res = await fetch(`${API_BASE}/ai-visibility/${propertyId}/run-standing`, { method: "POST" });
      const b = await res.json();
      if (!res.ok) {
        setNote({ ok: false, text: b.detail ?? "Run failed." });
      } else {
        setNote({
          ok: true,
          text: `Ran ${b.prompts_run} prompt(s)${b.budget_hit ? " (daily budget reached, stopped early)" : ""}. ` +
            (b.score !== null ? `Score now ${b.score} (${b.sample_size} queries).` : `Sample ${b.sample_size}, still below the scoring minimum.`),
        });
      }
    } finally {
      setBusy(false);
      load();
    }
  }

  const scored = history.filter((h) => h.score !== null);
  const unusedSuggestions = suggestions.filter(
    (s) => !prompts.some((p) => p.prompt_text === s),
  );

  return (
    <div className="space-y-5">
      <section className="rounded-2xl border border-line bg-surface p-5">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-medium">Standing prompts</h2>
          <div className="flex items-center gap-2">
          <label className="cursor-pointer rounded-lg border border-line px-3 py-1.5 text-xs text-muted hover:text-foreground">
            Import question set
            <input
              type="file"
              accept=".json,application/json"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) importSet(f);
                e.target.value = "";
              }}
            />
          </label>
          <button
            onClick={runNow}
            disabled={busy || prompts.length === 0}
            className="rounded-lg bg-violet-a px-3 py-1.5 text-xs font-medium text-background disabled:opacity-50"
            title={prompts.length === 0 ? "Add at least one prompt first" : "Runs all active prompts now (spends OpenAI budget)"}
          >
            {busy ? "Running…" : "Run all now"}
          </button>
          </div>
        </div>
        <p className="mt-1 text-xs text-muted">
          A reusable question set. Run weekly (automatically when enabled, or with
          the button) so the property builds up enough queries to score and trend.
          Each run spends OpenAI budget, capped by the per-day limit.
        </p>
        {note && (
          <p className={`mt-2 text-xs ${note.ok ? "text-emerald-a" : "text-pink-a"}`}>{note.text}</p>
        )}

        <div className="mt-4 space-y-2">
          {prompts.length === 0 && <p className="text-sm text-muted">No standing prompts yet.</p>}
          {prompts.map((p) => (
            <div key={p.id} className="flex items-center gap-3 rounded-xl border border-line bg-surface-raised px-3 py-2 text-sm">
              <span className="flex-1">
                {p.prompt_text}
                <span className="ml-2 inline-flex gap-1 align-middle">
                  {p.cadence && (
                    <span className="rounded-full border border-line px-1.5 py-0.5 text-[10px] text-muted">
                      {p.cadence}
                    </span>
                  )}
                  {p.volatile && (
                    <span className="rounded-full border border-amber-a/40 bg-amber-a/10 px-1.5 py-0.5 text-[10px] text-amber-a">
                      volatile
                    </span>
                  )}
                </span>
              </span>
              <span className="text-xs text-muted">{p.platform}</span>
              <button onClick={() => remove(p.id)} className="text-xs text-muted hover:text-pink-a">✕</button>
            </div>
          ))}
        </div>

        <div className="mt-4 flex gap-2">
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && add(draft)}
            placeholder="Add a prompt a real applicant might ask an AI…"
            className="flex-1 rounded-lg border border-line bg-surface px-3 py-2 text-sm"
          />
          <button onClick={() => add(draft)} disabled={!draft.trim()} className="rounded-lg border border-line px-3 py-2 text-sm text-muted hover:text-foreground disabled:opacity-50">
            Add
          </button>
        </div>

        {unusedSuggestions.length > 0 && (
          <div className="mt-4">
            <p className="mb-2 text-xs text-muted">Suggested for this property type (click to add):</p>
            <div className="flex flex-wrap gap-2">
              {unusedSuggestions.map((s) => (
                <button
                  key={s}
                  onClick={() => add(s)}
                  className="rounded-full border border-line px-3 py-1 text-xs text-muted hover:border-violet-a/60 hover:text-foreground"
                >
                  + {s}
                </button>
              ))}
            </div>
          </div>
        )}
      </section>

      <section className="rounded-2xl border border-line bg-surface p-5">
        <h2 className="text-sm font-medium">Visibility score over time</h2>
        {scored.length < 2 ? (
          <p className="mt-2 text-sm text-muted">
            {scored.length === 0
              ? "No scored runs yet. Once a run clears the query minimum, its score is plotted here; a trend appears after two or more scored runs."
              : "One scored run so far. A trend line appears after the next scored run."}
          </p>
        ) : (
          <MiniTrend points={scored} />
        )}
        {history.length > 0 && (
          <ul className="mt-4 space-y-1 text-xs text-muted">
            {history.slice(-6).reverse().map((h, i) => (
              <li key={i}>
                {fmtWhen(h.captured_at)}:{" "}
                {h.score !== null ? `score ${h.score}` : "not enough data"} ({h.sample_size} queries
                {h.mention_rate !== null ? `, ${pct(h.mention_rate)} mention rate` : ""})
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function MiniTrend({ points }: { points: ScorePoint[] }) {
  const vals = points.map((p) => p.score as number);
  const max = Math.max(100, ...vals);
  const min = Math.min(0, ...vals);
  const w = 480;
  const h = 120;
  const x = (i: number) => (points.length === 1 ? w / 2 : (i / (points.length - 1)) * (w - 20) + 10);
  const y = (v: number) => h - 10 - ((v - min) / (max - min || 1)) * (h - 20);
  const path = points.map((p, i) => `${i === 0 ? "M" : "L"} ${x(i)} ${y(p.score as number)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="mt-3 w-full" role="img" aria-label="Visibility score trend">
      <path d={path} fill="none" stroke="var(--color-violet-a, #8b7cf6)" strokeWidth="2" />
      {points.map((p, i) => (
        <circle key={i} cx={x(i)} cy={y(p.score as number)} r="3" fill="var(--color-violet-a, #8b7cf6)" />
      ))}
    </svg>
  );
}

