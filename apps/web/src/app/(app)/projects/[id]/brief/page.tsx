"use client";

import { useParams } from "next/navigation";
import { ResearchBriefWorkspace } from "@/components/projects/research-brief-workspace";

export default function ProjectBriefPage() {
  const { id } = useParams<{ id: string }>();
  return <ResearchBriefWorkspace key={id} projectId={id} />;
}
