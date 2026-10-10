"use client";

import { useParams } from "next/navigation";
import { ResearchPlanningWorkspace } from "@/components/projects/research-planning-workspace";

export default function ProjectPlanningPage() {
  const { id } = useParams<{ id: string }>();
  return <ResearchPlanningWorkspace key={id} projectId={id} />;
}
