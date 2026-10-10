"use client";
import { Suspense } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { LoadingState } from "@/components/ui/state";
import { PublicationsWorkspace } from "@/components/publications/workspace";
function Content() {
  const { id } = useParams<{ id: string }>(),
    params = useSearchParams();
  return (
    <PublicationsWorkspace
      key={id}
      projectId={id}
      initialId={params.get("publication") ?? undefined}
    />
  );
}
export default function Page() {
  return (
    <Suspense fallback={<LoadingState />}>
      <Content />
    </Suspense>
  );
}
