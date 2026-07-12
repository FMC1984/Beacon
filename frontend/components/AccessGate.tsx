"use client";

import { useCallback, useEffect, useState } from "react";
import { API_BASE } from "@/lib/api";

const KEY_STORAGE = "beacon.accessKey";

// Every component talks to the API with plain fetch(`${API_BASE}...`), so the
// access key is attached here once, at the fetch layer, instead of touching
// every call site. Runs only in the browser; requests to other origins are
// untouched.
let patched = false;
function patchFetch() {
  if (patched || typeof window === "undefined") return;
  patched = true;
  const original = window.fetch.bind(window);
  window.fetch = (input, init = {}) => {
    const url =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.toString()
          : input.url;
    if (url.startsWith(API_BASE)) {
      const key = window.localStorage.getItem(KEY_STORAGE);
      if (key) {
        init = {
          ...init,
          headers: { ...(init.headers || {}), "X-Beacon-Key": key },
        };
      }
    }
    return original(input, init);
  };
}

export function AccessGate({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<"checking" | "locked" | "ready">("checking");
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);

  const probe = useCallback(async () => {
    // /api/companies is cheap and behind the key; locally (no key configured
    // on the server) it answers 200 and the gate never appears.
    try {
      const res = await fetch(`${API_BASE}/companies`);
      setState(res.status === 401 ? "locked" : "ready");
    } catch {
      // API unreachable: let the app render its own connection errors.
      setState("ready");
    }
  }, []);

  useEffect(() => {
    patchFetch();
    probe();
  }, [probe]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    window.localStorage.setItem(KEY_STORAGE, draft.trim());
    const res = await fetch(`${API_BASE}/companies`);
    if (res.status === 401) {
      window.localStorage.removeItem(KEY_STORAGE);
      setError("That key was not accepted.");
    } else {
      setState("ready");
    }
  }

  if (state === "ready") return <>{children}</>;
  if (state === "checking") {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-muted">
        Connecting to Beacon…
      </div>
    );
  }
  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <form
        onSubmit={submit}
        className="w-full max-w-sm space-y-4 rounded-2xl border border-line bg-surface p-6"
      >
        <div>
          <h1 className="text-lg font-semibold">Beacon</h1>
          <p className="mt-1 text-sm text-muted">
            This instance is protected. Enter the access key to continue.
          </p>
        </div>
        <input
          type="password"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Access key"
          autoFocus
          className="w-full rounded-xl border border-line bg-surface-raised px-3 py-2 text-sm"
        />
        {error && <p className="text-xs text-pink-a">{error}</p>}
        <button
          disabled={!draft.trim()}
          className="w-full rounded-xl bg-violet-a px-4 py-2 text-sm font-medium text-background disabled:opacity-50"
        >
          Unlock
        </button>
      </form>
    </div>
  );
}
