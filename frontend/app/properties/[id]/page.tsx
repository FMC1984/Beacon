"use client";

import { useParams } from "next/navigation";
import { DashboardView } from "@/components/DashboardView";

export default function PropertyPage() {
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  if (!Number.isFinite(id)) return <p className="text-muted">Unknown property.</p>;
  return <DashboardView propertyId={id} />;
}
