"use client";
import { useParams } from "next/navigation";
import { RegistryDetailView } from "@/components/registries/detail-view";
export default function DatasetDetailPage() {
  const { id } = useParams<{ id: string }>();
  return <RegistryDetailView key={id} kind="datasets" id={id} />;
}
