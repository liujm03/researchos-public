"use client";
import { useParams } from "next/navigation";
import { RegistryDetailView } from "@/components/registries/detail-view";
export default function ModelDetailPage() {
  const { id } = useParams<{ id: string }>();
  return <RegistryDetailView key={id} kind="models" id={id} />;
}
