"use client";
import { useParams } from "next/navigation";
import { IdeasWorkspace } from "@/components/ideas/workspace";
export default function IdeaPage() {
  const { id } = useParams<{ id: string }>();
  return <IdeasWorkspace key={id} projectId="" initialIdeaId={id} />;
}
