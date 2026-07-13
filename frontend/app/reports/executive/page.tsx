import { ExecutiveReport } from "@/components/reports/ExecutiveReport";
import { SourceStatusPanel } from "@/components/reports/PlannedReport";

export default function ExecutiveReportPage() {
  return (
    <div className="space-y-6">
      <ExecutiveReport />
      <SourceStatusPanel />
    </div>
  );
}
