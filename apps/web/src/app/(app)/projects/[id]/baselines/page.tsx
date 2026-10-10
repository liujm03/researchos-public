"use client";
import { useParams } from "next/navigation";
import { BaselinesWorkspace } from "@/components/baselines/workspace";
export default function ProjectBaselinesPage() {
  const { id } = useParams<{ id: string }>();
  return <BaselinesWorkspace key={id} projectId={id} />;
}
