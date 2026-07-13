"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE, Company, Property, fetchCompanies, fetchProperties } from "@/lib/api";
import { Disclosure } from "@/components/MetricCard";
import { ScopeSelect } from "@/components/ScopeSelect";

type Citation = {
  property_id: number | null;
  property_name: string | null;
  date_range: string;
  source_table: string;
  source_ref: string;
};

type Gate = {
  passed: boolean;
  ai_sessions: number;
  leases: number;
  r: number;
  periods_confirmed: number;
  unmet: string[];
};

type ChatMessage = {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  disclosure?: string | null;
  gate?: Gate;
  gate_passed?: boolean | null;
  mode?: "demo" | "live";
};

type Conversation = {
  id: number;
  title: string | null;
  property_id: number | null;
  created_at: string;
};

const SOURCE_LABELS: Record<string, string> = {
  ga4_sessions_daily: "GA4 traffic",
  ai_query_signals: "AI Query Signals",
  ai_visibility: "AI Visibility",
  competitor_intelligence: "Competitor IQ",
  opportunity_engine: "Opportunities",
  gsc_performance_daily: "Search Console",
  gbp_metrics_daily: "Business Profile",
  paid_media_daily: "Paid media",
  crm_leads: "CRM leads",
};

function fmtWhen(iso: string) {
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export default function NoraPage() {
  const [properties, setProperties] = useState<Property[]>([]);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [propertyId, setPropertyId] = useState<string>("");
  const [conversationId, setConversationId] = useState<number | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [demoMode, setDemoMode] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Saved chats are scoped: a selected property shows that property's chats;
  // "All properties" shows the portfolio-wide (unscoped) ones.
  const loadConversations = useCallback(() => {
    const qs = propertyId
      ? `property_id=${propertyId}`
      : "scope=portfolio";
    fetch(`${API_BASE}/nora/conversations?${qs}`)
      .then((r) => r.json())
      .then((rows: Conversation[]) => setConversations(rows))
      .catch(() => setConversations([]));
  }, [propertyId]);

  useEffect(() => {
    fetchProperties().then(setProperties).catch(() => {});
    fetchCompanies().then(setCompanies).catch(() => {});
    fetch(`${API_BASE}/admin/status`)
      .then((r) => r.json())
      .then((s) => setDemoMode(Boolean(s.demo_mode)))
      .catch(() => {});
    // Ask-Nora handoff (Phase 17B): the Monthly Briefing links here with a
    // property and section-aware question preloaded. window.location avoids
    // the Suspense boundary useSearchParams would require; one-shot on mount.
    try {
      const params = new URLSearchParams(window.location.search);
      const q = params.get("q");
      const pid = params.get("property_id");
      if (pid && /^\d+$/.test(pid)) setPropertyId(pid);
      if (q) setQuestion(q);
    } catch {}
  }, []);

  useEffect(loadConversations, [loadConversations]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  async function send(e: React.FormEvent) {
    e.preventDefault();
    const q = question.trim();
    if (!q || busy) return;
    setMessages((m) => [...m, { role: "user", content: q }]);
    setQuestion("");
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/nora/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: q,
          property_id: propertyId ? Number(propertyId) : null,
          conversation_id: conversationId,
        }),
      });
      const body = await res.json();
      if (!res.ok) {
        setError(body.detail ?? "Nora request failed.");
      } else {
        const isNew = conversationId === null;
        setConversationId(body.conversation_id);
        setMessages((m) => [
          ...m,
          {
            role: "assistant",
            content: body.answer,
            citations: body.citations,
            disclosure: body.disclosure,
            gate: body.gate,
            mode: body.mode,
          },
        ]);
        if (isNew) loadConversations();
      }
    } catch {
      setError("Could not reach the Beacon API. Is the backend running?");
    } finally {
      setBusy(false);
    }
  }

  function newChat() {
    setConversationId(null);
    setMessages([]);
    setError(null);
  }

  function switchScope(newPropertyId: string) {
    setPropertyId(newPropertyId);
    newChat();
  }

  async function openConversation(id: number) {
    setError(null);
    try {
      const rows = await fetch(
        `${API_BASE}/nora/conversations/${id}`
      ).then((r) => r.json());
      setConversationId(id);
      setMessages(
        rows.map(
          (m: {
            role: "user" | "assistant";
            content: string;
            citations: Citation[] | null;
            gate_passed: boolean | null;
          }) => ({
            role: m.role,
            content: m.content,
            citations: m.citations ?? undefined,
            gate_passed: m.gate_passed,
          })
        )
      );
    } catch {
      setError("Could not load that conversation.");
    }
  }

  async function deleteConversation(id: number) {
    setDeletingId(null);
    try {
      const res = await fetch(`${API_BASE}/nora/conversations/${id}`, {
        method: "DELETE",
      });
      if (!res.ok && res.status !== 204) {
        setError("Could not delete that conversation.");
        return;
      }
      if (id === conversationId) newChat();
      loadConversations();
    } catch {
      setError("Could not reach the Beacon API.");
    }
  }

  return (
    <div className="flex h-[calc(100vh-8.5rem)] gap-5">
      {/* Saved chats */}
      <aside className="hidden w-64 shrink-0 flex-col rounded-2xl border border-line bg-surface p-3 md:flex">
        <div className="mb-2 flex items-center justify-between px-1">
          <h2 className="text-sm font-medium text-muted">Saved chats</h2>
          <button
            onClick={newChat}
            className="rounded-lg bg-violet-a/15 px-2 py-1 text-xs font-medium text-violet-a hover:bg-violet-a/25"
          >
            New
          </button>
        </div>
        <div className="flex-1 space-y-1 overflow-y-auto">
          {conversations.length === 0 && (
            <p className="px-1 py-2 text-xs text-muted">
              No saved chats {propertyId ? "for this property" : "at the portfolio level"} yet.
            </p>
          )}
          {conversations.map((c) => (
            <div
              key={c.id}
              className={`group flex items-center gap-1 rounded-lg px-2 py-1.5 text-sm ${
                c.id === conversationId ? "bg-surface-raised" : "hover:bg-surface-raised"
              }`}
            >
              <button
                onClick={() => openConversation(c.id)}
                className="flex-1 overflow-hidden text-left"
              >
                <span className="block truncate">{c.title || "Untitled chat"}</span>
                <span className="block text-[11px] text-muted">
                  {fmtWhen(c.created_at)}
                </span>
              </button>
              {deletingId === c.id ? (
                <span className="flex items-center gap-1 text-[11px]">
                  <button
                    onClick={() => deleteConversation(c.id)}
                    className="rounded bg-pink-a/20 px-1.5 py-0.5 font-medium text-pink-a"
                  >
                    Delete
                  </button>
                  <button
                    onClick={() => setDeletingId(null)}
                    className="rounded px-1 py-0.5 text-muted"
                  >
                    No
                  </button>
                </span>
              ) : (
                <button
                  onClick={() => setDeletingId(c.id)}
                  aria-label="Delete chat"
                  title="Delete chat"
                  className="rounded px-1 py-0.5 text-xs text-muted opacity-0 transition-opacity hover:text-pink-a group-hover:opacity-100"
                >
                  ✕
                </button>
              )}
            </div>
          ))}
        </div>
      </aside>

      {/* Chat */}
      <div className="mx-auto flex min-w-0 max-w-3xl flex-1 flex-col">
        <div className="flex items-center justify-between gap-4 pb-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Nora</h1>
            <p className="mt-1 text-sm text-muted">
              Answers only from your ingested data, with citations. Not a
              general-purpose chatbot.
            </p>
          </div>
          <ScopeSelect
            companies={companies}
            properties={properties}
            value={propertyId ? Number(propertyId) : null}
            onChange={(id) => switchScope(id ? String(id) : "")}
            allowAll
            allLabel="All properties"
          />
        </div>

        {demoMode && (
          <div className="mb-4 rounded-xl border border-amber-a/40 bg-amber-a/10 px-4 py-2.5 text-sm text-amber-a">
            Demo mode is on: answers are deterministic local summaries of your
            ingested data, not live model output. Citations, gate checks, and
            disclosures behave exactly as they will in live mode.
          </div>
        )}

        <div className="flex-1 space-y-4 overflow-y-auto rounded-2xl border border-line bg-surface p-5">
          {messages.length === 0 && (
            <p className="text-sm text-muted">
              Try: &quot;How much AI traffic did we get last month?&quot; or
              &quot;Is AI traffic turning into leases?&quot;
            </p>
          )}
          {messages.map((m, i) =>
            m.role === "user" ? (
              <div key={i} className="flex justify-end">
                <div className="max-w-[85%] rounded-2xl rounded-br-md bg-violet-a/20 px-4 py-2.5 text-sm">
                  {m.content}
                </div>
              </div>
            ) : (
              <div key={i} className="max-w-[95%] space-y-2">
                <div className="whitespace-pre-wrap rounded-2xl rounded-bl-md bg-surface-raised px-4 py-3 text-sm leading-relaxed">
                  {m.content}
                </div>
                {m.mode === "demo" && (
                  <p className="text-[11px] text-amber-a">Demo mode answer, not live model output.</p>
                )}
                {m.gate && !m.gate.passed && (
                  <p className="text-[11px] text-amber-a">
                    Correlation gate: not enough data to link AI traffic to
                    leases ({m.gate.ai_sessions} AI sessions, {m.gate.leases}{" "}
                    leases, {m.gate.periods_confirmed} shared periods).
                  </p>
                )}
                {m.gate === undefined && m.gate_passed === false && (
                  <p className="text-[11px] text-amber-a">
                    Correlation gate did not pass for this answer.
                  </p>
                )}
                {m.citations && m.citations.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {m.citations.map((c, j) => (
                      <span
                        key={j}
                        title={c.source_ref}
                        className="rounded-full border border-line bg-surface px-2.5 py-1 text-[11px] text-muted"
                      >
                        [{j + 1}] {SOURCE_LABELS[c.source_table] ?? c.source_table}
                        {c.property_name ? ` · ${c.property_name}` : ""} ·{" "}
                        {c.date_range}
                      </span>
                    ))}
                  </div>
                )}
                {m.disclosure && <Disclosure text={m.disclosure} />}
              </div>
            )
          )}
          {busy && <p className="text-sm text-muted">Nora is reading the data…</p>}
          {error && (
            <div className="rounded-xl border border-pink-a/40 bg-pink-a/10 p-3 text-sm text-pink-a">
              {error}
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        <form onSubmit={send} className="mt-4 flex gap-2">
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Ask about your ingested data…"
            className="flex-1 rounded-xl border border-line bg-surface px-4 py-2.5 text-sm"
          />
          <button
            disabled={busy || !question.trim()}
            className="rounded-xl bg-violet-a px-4 py-2 text-sm font-medium text-background disabled:opacity-50"
          >
            Ask
          </button>
        </form>
      </div>
    </div>
  );
}
