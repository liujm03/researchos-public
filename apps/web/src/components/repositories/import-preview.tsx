import Link from "next/link";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import {
  repositoryTargetHref,
  type RepositoryImport,
} from "@/lib/repositories";
import { RepositoryConfirmForm } from "./confirm-form";
import { RepositoryMetadataView } from "./metadata-view";

export function RepositoryImportPreview({
  record,
  onConfirmed,
}: {
  record: RepositoryImport;
  onConfirmed: (result: RepositoryImport) => void;
}) {
  const warnings = [
    ...new Set([
      ...(record.candidate.warnings ?? []),
      ...(record.warnings ?? []),
    ]),
  ];
  const targetHref = repositoryTargetHref(
    record.target_entity_kind,
    record.target_entity_id,
  );
  return (
    <Card>
      <CardHeader>
        <h2 className="font-semibold">
          {record.status === "CONFIRMED" ? "已确认的来源回执" : "冻结预览"}
        </h2>
        <span className="text-xs text-[var(--muted)]">
          {record.status === "CONFIRMED" ? "已登记" : "待人工确认"}
        </span>
      </CardHeader>
      <CardContent className="space-y-5">
        {warnings.length > 0 && (
          <div
            className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3"
            role="status"
          >
            <p className="text-xs font-medium text-amber-700 dark:text-amber-300">
              来源需要核对
            </p>
            <ul className="mt-2 list-disc space-y-1 pl-4 text-xs leading-5">
              {warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          </div>
        )}
        <RepositoryMetadataView candidate={record.candidate} />
        <dl className="space-y-2 text-[10px] leading-5">
          <div>
            <dt className="text-[var(--muted)]">元数据来源 Hash</dt>
            <dd className="break-all font-mono">{record.source_hash}</dd>
          </div>
          <div>
            <dt className="text-[var(--muted)]">冻结快照 SHA-256</dt>
            <dd className="break-all font-mono">{record.snapshot_sha256}</dd>
          </div>
          <div>
            <dt className="text-[var(--muted)]">请求 Revision</dt>
            <dd className="break-all font-mono">
              {record.revision || "默认版本"}
            </dd>
          </div>
        </dl>
        {record.status === "PENDING" ? (
          <RepositoryConfirmForm
            key={record.id}
            record={record}
            onConfirmed={onConfirmed}
          />
        ) : (
          <div
            className="space-y-3 rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-4"
            role="status"
          >
            <p className="text-sm font-medium">仓库元数据已登记</p>
            <p className="text-xs leading-5 text-[var(--muted)]">
              本次保存来源说明、身份与版本。代码、权重和数据文件需在后续工作流中单独获取。
            </p>
            <dl className="space-y-1 text-xs">
              <div>
                <dt className="inline text-[var(--muted)]">目标：</dt>
                <dd className="inline break-all font-mono">
                  {record.target_entity_kind} / {record.target_entity_id}
                </dd>
              </div>
              {(record.model_version_id || record.dataset_version_id) && (
                <div>
                  <dt className="inline text-[var(--muted)]">不可变版本：</dt>
                  <dd className="inline break-all font-mono">
                    {record.model_version_id || record.dataset_version_id}
                  </dd>
                </div>
              )}
              {record.code_repository_id && (
                <div>
                  <dt className="inline text-[var(--muted)]">
                    CodeRepository：
                  </dt>
                  <dd className="inline break-all font-mono">
                    {record.code_repository_id}
                  </dd>
                </div>
              )}
            </dl>
            <div className="flex flex-wrap gap-3 text-xs text-[var(--accent)]">
              {targetHref && (
                <Link href={targetHref} className="hover:underline">
                  查看登记资源
                </Link>
              )}
              {record.source_snapshot_id && (
                <Link
                  href={`/integrations/repositories/sources/${encodeURIComponent(record.source_snapshot_id)}`}
                  className="hover:underline"
                >
                  查看冻结来源
                </Link>
              )}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
