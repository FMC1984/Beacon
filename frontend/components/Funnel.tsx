import type { CRMSection } from "@/lib/api";
import { fmtNum } from "@/lib/format";

const STAGES: { key: keyof CRMSection["funnel"]; label: string; color: string }[] = [
  { key: "lead", label: "Leads", color: "var(--accent-cyan)" },
  { key: "tour", label: "Tours", color: "var(--accent-violet)" },
  { key: "application", label: "Applications", color: "var(--accent-amber)" },
  { key: "lease", label: "Leases", color: "var(--accent-emerald)" },
  { key: "lost", label: "Lost", color: "var(--muted)" },
];

export function Funnel({ crm }: { crm: CRMSection }) {
  const max = Math.max(1, ...STAGES.map((s) => crm.funnel[s.key]));
  return (
    <div className="space-y-3">
      {STAGES.map((stage) => {
        const value = crm.funnel[stage.key];
        return (
          <div key={stage.key} className="flex items-center gap-3">
            <span className="w-28 shrink-0 text-sm text-muted">{stage.label}</span>
            <div className="h-6 flex-1 overflow-hidden rounded-lg bg-surface-raised">
              <div
                className="h-full rounded-lg transition-all"
                style={{
                  width: `${Math.max(2, (value / max) * 100)}%`,
                  background: stage.color,
                  opacity: value === 0 ? 0.15 : 0.85,
                }}
              />
            </div>
            <span className="w-10 text-right text-sm font-medium">{fmtNum(value)}</span>
          </div>
        );
      })}
    </div>
  );
}
