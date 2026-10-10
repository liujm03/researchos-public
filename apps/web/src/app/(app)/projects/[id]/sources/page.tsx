"use client";

import { useParams } from "next/navigation";
import { ProjectSourcesWorkspace } from "@/components/projects/project-sources-workspace";

export default function ProjectSourcesPage() {
  const { id } = useParams<{ id: string }>();
  return <ProjectSourcesWorkspace key={id} projectId={id} />;
}
