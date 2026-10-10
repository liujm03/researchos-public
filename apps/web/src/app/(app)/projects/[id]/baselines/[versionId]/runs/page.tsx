"use client";
import { useParams } from "next/navigation";
import { BaselineRunsWorkspace } from "@/components/baseline-runs/workspace";
export default function BaselineRunsPage() {
  const { id, versionId } = useParams<{ id: string; versionId: string }>();
  return (
    <BaselineRunsWorkspace
      key={`${id}:${versionId}`}
      projectId={id}
      versionId={versionId}
    />
  );
}
