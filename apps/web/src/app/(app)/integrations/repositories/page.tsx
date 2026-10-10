import { Suspense } from "react";
import { RepositoryImportWorkspace } from "@/components/repositories/import-workspace";
import { LoadingState } from "@/components/ui/state";

export default function RepositoriesPage() {
  return (
    <Suspense fallback={<LoadingState label="正在读取仓库工作区…" />}>
      <RepositoryImportWorkspace />
    </Suspense>
  );
}
