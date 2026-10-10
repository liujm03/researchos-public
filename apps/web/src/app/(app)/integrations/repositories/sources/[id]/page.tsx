"use client";
import { useParams } from "next/navigation";
import { RepositorySourceView } from "@/components/repositories/source-view";

export default function RepositorySourcePage() {
  const { id } = useParams<{ id: string }>();
  return <RepositorySourceView key={id} id={id} />;
}
