"use client";
import { useParams, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { LoadingState } from "@/components/ui/state";
import { ClaimsWorkspace } from "@/components/claims/workspace";
function Content() {
  const { id } = useParams<{ id: string }>();
  const params = useSearchParams();
  return (
    <ClaimsWorkspace
      key={id}
      projectId={id}
      initialClaimId={params.get("claim") ?? undefined}
    />
  );
}
export default function ProjectEvidencePage() {
  return (
    <Suspense fallback={<LoadingState />}>
      <Content />
    </Suspense>
  );
}
