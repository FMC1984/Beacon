"use client";

/** Bulk-import reviews from a CSV export (the working path for Google Business
 * Profile reviews until the live connector is API-approved). Posts to
 * /api/reviews/{id}/import, which upserts by provider + external review id so
 * re-imports update rather than duplicate. */

import { useRef, useState } from "react";
import { API_BASE } from "@/lib/api";

type ImportResult = {
  imported: number;
  updated: number;
  skipped: number;
  provider: string;
};

export function ReviewImport({
  propertyId,
  onImported,
}: {
  propertyId: number | null;
  onImported: () => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);

  async function onFile(file: File) {
    if (propertyId === null) return;
    setBusy(true);
    setNotice(null);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("provider", "google");
      const res = await fetch(`${API_BASE}/reviews/${propertyId}/import`, {
        method: "POST",
        body: form,
      });
      const body = await res.json();
      if (!res.ok) {
        setNotice({ ok: false, text: body.detail ?? "Import failed." });
        return;
      }
      const r = body as ImportResult;
      setNotice({
        ok: true,
        text: `Imported ${r.imported} new, updated ${r.updated}${
          r.skipped ? `, skipped ${r.skipped} without text` : ""
        }.`,
      });
      onImported();
    } catch {
      setNotice({ ok: false, text: "Import failed. Check the file and try again." });
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <input
        ref={inputRef}
        type="file"
        accept=".csv,text/csv"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onFile(f);
        }}
      />
      <button
        onClick={() => inputRef.current?.click()}
        disabled={busy || propertyId === null}
        title="Import reviews from a Google Business Profile CSV export"
        className="rounded-xl border border-line px-4 py-2 text-sm text-muted hover:text-foreground disabled:opacity-50"
      >
        {busy ? "Importing…" : "Import reviews (CSV)"}
      </button>
      {notice && (
        <span className={`text-xs ${notice.ok ? "text-emerald-a" : "text-pink-a"}`}>
          {notice.text}
        </span>
      )}
    </div>
  );
}
