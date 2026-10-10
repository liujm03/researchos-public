"use client";
import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { IdeasWorkspace } from "@/components/ideas/workspace";
import { LoadingState } from "@/components/ui/state";
function IdeasContent() {
  const params = useSearchParams();
  const projectId = params.get("project_id") ?? "";
  return <IdeasWorkspace key={projectId} projectId={projectId} />;
}
export default function IdeasPage() {
  return (
    <Suspense fallback={<LoadingState label="正在加载科研灵感…" />}>
      <IdeasContent />
    </Suspense>
  );
}
