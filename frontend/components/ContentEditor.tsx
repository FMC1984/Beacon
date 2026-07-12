"use client";

import { useCallback, useEffect, useState } from "react";
import { API_BASE } from "@/lib/api";

type ContentPage = {
  id: number;
  property_id: number;
  page: string;
  title: string;
  body: string;
  mapped_keyword: string | null;
  source_url: string | null;
  updated_at: string | null;
};

const PAGES: { key: string; label: string }[] = [
  { key: "homepage", label: "Homepage" },
  { key: "amenities", label: "Amenities" },
  { key: "floor_plans", label: "Floor Plans" },
  { key: "neighborhood", label: "Neighborhood" },
  { key: "faq", label: "FAQ" },
];

// Page keys are fixed for storage, but labels adapt to the client/site type so a
// housing authority sees agency-appropriate section names.
const PAGE_LABELS: Record<string, Record<string, string>> = {
  housing_authority: {
    amenities: "Programs & Services",
    floor_plans: "Eligibility & Application",
    neighborhood: "Service Area & Resources",
  },
};

function fmtDate(iso: string | null) {
  if (!iso) return null;
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function ContentEditor({
  propertyId,
  defaultUrl,
  propertyType = "multifamily_apartment",
  onChanged,
}: {
  propertyId: number;
  defaultUrl: string | null;
  propertyType?: string;
  onChanged: () => void;
}) {
  const pageLabel = (key: string, fallback: string) =>
    PAGE_LABELS[propertyType]?.[key] ?? fallback;
  const [pages, setPages] = useState<Record<string, ContentPage>>({});
  const [openKey, setOpenKey] = useState<string | null>(null);
  const [urlDraft, setUrlDraft] = useState("");
  const [keywordDraft, setKeywordDraft] = useState("");
  const [titleDraft, setTitleDraft] = useState("");
  const [bodyDraft, setBodyDraft] = useState("");
  const [manualMode, setManualMode] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null);

  const load = useCallback(() => {
    fetch(`${API_BASE}/content/${propertyId}`)
      .then((r) => r.json())
      .then((rows: ContentPage[]) => {
        const byPage: Record<string, ContentPage> = {};
        rows.forEach((r) => (byPage[r.page] = r));
        setPages(byPage);
      })
      .catch(() => {});
  }, [propertyId]);

  useEffect(load, [load]);

  function openPage(key: string) {
    const existing = pages[key];
    setOpenKey(key);
    setManualMode(false);
    setResult(null);
    setUrlDraft(existing?.source_url ?? (key === "homepage" ? defaultUrl ?? "" : ""));
    setKeywordDraft(existing?.mapped_keyword ?? "");
    setTitleDraft(existing?.title ?? "");
    setBodyDraft(existing?.body ?? "");
  }

  async function fetchFromUrl(key: string) {
    if (!urlDraft.trim()) return;
    setBusy(true);
    setResult(null);
    try {
      const res = await fetch(`${API_BASE}/content/${propertyId}/${key}/fetch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url: urlDraft.trim(),
          mapped_keyword: keywordDraft.trim() || null,
        }),
      });
      const body = await res.json();
      if (!res.ok) {
        setResult({ ok: false, message: body.detail ?? "Fetch failed." });
      } else {
        setResult({
          ok: true,
          message: `Pulled ${body.char_count.toLocaleString()} characters${
            body.truncated ? " (truncated to fit)" : ""
          }.`,
        });
        load();
        onChanged();
      }
    } catch {
      setResult({ ok: false, message: "Could not reach the Beacon API." });
    } finally {
      setBusy(false);
    }
  }

  async function saveManual(key: string) {
    if (!titleDraft.trim() || !bodyDraft.trim()) {
      setResult({ ok: false, message: "Title and body are both required." });
      return;
    }
    setBusy(true);
    setResult(null);
    try {
      const res = await fetch(`${API_BASE}/content/${propertyId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          page: key,
          title: titleDraft.trim(),
          body: bodyDraft.trim(),
          mapped_keyword: keywordDraft.trim() || null,
          source_url: urlDraft.trim() || null,
        }),
      });
      if (!res.ok) {
        setResult({ ok: false, message: (await res.json()).detail ?? "Save failed." });
      } else {
        setResult({ ok: true, message: "Saved." });
        load();
        onChanged();
      }
    } catch {
      setResult({ ok: false, message: "Could not reach the Beacon API." });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-2xl border border-line bg-surface p-5">
      <h2 className="mb-1 text-sm font-medium text-muted">Website content</h2>
      <p className="mb-4 text-xs text-muted">
        Pull each page&apos;s text automatically from its URL, or write it
        manually. This is real page text, never generated.
      </p>
      <div className="space-y-2">
        {PAGES.map(({ key, label }) => {
          const existing = pages[key];
          const isOpen = openKey === key;
          return (
            <div key={key} className="rounded-xl border border-line bg-surface-raised">
              <button
                onClick={() => (isOpen ? setOpenKey(null) : openPage(key))}
                className="flex w-full items-center justify-between px-4 py-2.5 text-left text-sm"
              >
                <span className="font-medium">{pageLabel(key, label)}</span>
                <span className="flex items-center gap-2 text-xs text-muted">
                  {existing ? (
                    <>
                      <span className="rounded-full bg-emerald-a/15 px-2 py-0.5 text-emerald-a">
                        has content
                      </span>
                      {fmtDate(existing.updated_at) && (
                        <span>updated {fmtDate(existing.updated_at)}</span>
                      )}
                    </>
                  ) : (
                    <span className="rounded-full border border-line px-2 py-0.5">
                      no content
                    </span>
                  )}
                  <span>{isOpen ? "−" : "+"}</span>
                </span>
              </button>

              {isOpen && (
                <div className="space-y-3 border-t border-line px-4 py-3">
                  {!manualMode ? (
                    <>
                      <label className="block text-xs">
                        <span className="text-muted">Page URL</span>
                        <input
                          value={urlDraft}
                          onChange={(e) => setUrlDraft(e.target.value)}
                          placeholder="https://example.com/amenities"
                          type="url"
                          className="mt-1 w-full rounded-lg border border-line bg-surface px-2.5 py-1.5 text-sm"
                        />
                      </label>
                      <label className="block text-xs">
                        <span className="text-muted">Mapped keyword (optional)</span>
                        <input
                          value={keywordDraft}
                          onChange={(e) => setKeywordDraft(e.target.value)}
                          className="mt-1 w-full rounded-lg border border-line bg-surface px-2.5 py-1.5 text-sm"
                        />
                      </label>
                      <div className="flex items-center gap-3">
                        <button
                          onClick={() => fetchFromUrl(key)}
                          disabled={busy || !urlDraft.trim()}
                          className="rounded-lg bg-violet-a px-3 py-1.5 text-xs font-medium text-background disabled:opacity-50"
                        >
                          {busy ? "Fetching…" : "Fetch from URL"}
                        </button>
                        <button
                          onClick={() => setManualMode(true)}
                          className="text-xs text-muted underline decoration-dotted hover:text-foreground"
                        >
                          Write manually instead
                        </button>
                      </div>
                    </>
                  ) : (
                    <>
                      <label className="block text-xs">
                        <span className="text-muted">Title</span>
                        <input
                          value={titleDraft}
                          onChange={(e) => setTitleDraft(e.target.value)}
                          className="mt-1 w-full rounded-lg border border-line bg-surface px-2.5 py-1.5 text-sm"
                        />
                      </label>
                      <label className="block text-xs">
                        <span className="text-muted">Body</span>
                        <textarea
                          value={bodyDraft}
                          onChange={(e) => setBodyDraft(e.target.value)}
                          rows={5}
                          className="mt-1 w-full rounded-lg border border-line bg-surface px-2.5 py-1.5 text-sm"
                        />
                      </label>
                      <label className="block text-xs">
                        <span className="text-muted">Mapped keyword (optional)</span>
                        <input
                          value={keywordDraft}
                          onChange={(e) => setKeywordDraft(e.target.value)}
                          className="mt-1 w-full rounded-lg border border-line bg-surface px-2.5 py-1.5 text-sm"
                        />
                      </label>
                      <div className="flex items-center gap-3">
                        <button
                          onClick={() => saveManual(key)}
                          disabled={busy}
                          className="rounded-lg bg-violet-a px-3 py-1.5 text-xs font-medium text-background disabled:opacity-50"
                        >
                          {busy ? "Saving…" : "Save"}
                        </button>
                        <button
                          onClick={() => setManualMode(false)}
                          className="text-xs text-muted underline decoration-dotted hover:text-foreground"
                        >
                          Fetch from URL instead
                        </button>
                      </div>
                    </>
                  )}
                  {result && (
                    <p className={`text-xs ${result.ok ? "text-emerald-a" : "text-pink-a"}`}>
                      {result.message}
                    </p>
                  )}
                  {existing && (
                    <p className="line-clamp-2 text-xs text-muted">{existing.body}</p>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}
