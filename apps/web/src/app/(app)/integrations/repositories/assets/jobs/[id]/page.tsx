"use client";

import { useParams } from "next/navigation";
import { AssetJobWorkspace } from "@/components/repositories/asset-job-workspace";

export default function RepositoryAssetJobPage() {
  const { id } = useParams<{ id: string }>();
  return <AssetJobWorkspace key={id} jobId={id} />;
}
