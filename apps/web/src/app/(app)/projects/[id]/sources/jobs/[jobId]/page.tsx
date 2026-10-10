"use client";

import { useParams } from "next/navigation";
import { ProjectSourceJobWorkspace } from "@/components/projects/project-source-job-workspace";

export default function ProjectSourceJobPage() {
  const { id, jobId } = useParams<{ id: string; jobId: string }>();
  return <ProjectSourceJobWorkspace key={jobId} projectId={id} jobId={jobId} />;
}
