"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { ErrorState, LoadingState } from "@/components/ui/state";
import { api } from "@/lib/api";
import {
  repositoryTargetHref,
  type RepositorySource,
} from "@/lib/repositories";
import { RepositoryMetadataView } from "./metadata-view";
import { RepositoryAssetsPanel } from "./repository-assets-panel";

export function RepositorySourceView({ id }: { id: string }) {
  const [source, setSource] = useState<RepositorySource | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const generation = useRef(0);
  const load = useCallback(async () => {
    const request = ++generation.current;
    setLoading(true);
    setError("");
    try {
      const result = await api.get<RepositorySource>(
        `/repository-sources/${encodeURIComponent(id)}`,
      );
      if (request === generation.current) setSource(result);
    } catch (cause) {
      if (request === generation.current)
        setError(
          cause instanceof Error ? cause.message : "无法读取冻结仓库来源",
        );
    } finally {
      if (request === generation.current) setLoading(false);
    }
  }, [id]);
  useEffect(() => {
    let active = true;
    const controller = generation;
    queueMicrotask(() => {
      if (active) void load();
    });
    return () => {
      active = false;
      controller.current++;
    };
  }, [load]);
  const targetHref = source
    ? repositoryTargetHref(source.target_entity_kind, source.target_entity_id)
    : null;
  return (
    <div className="space-y-6">
      <Link
        href="/integrations/repositories"
        className="text-xs text-[var(--accent)] hover:underline"
      >
        返回开源仓库
      </Link>
      <div>
        <h1 className="text-2xl font-semibold">仓库冻结来源</h1>
        <p className="mt-2 text-sm text-[var(--muted)]">
          核对当时导入的原始说明、身份、哈希及关联版本。来源区读取已保存回执；资产清单预览与下载需在下方分别明确操作。
        </p>
      </div>
      {error && <ErrorState message={error} onRetry={() => void load()} />}
      {loading ? (
        <LoadingState label="正在读取来源快照…" />
      ) : (
        source && (
          <>
            <Card>
              <CardHeader>
                <h2 className="font-semibold">来源与登记版本</h2>
                {targetHref && (
                  <Link
                    href={targetHref}
                    className="text-xs text-[var(--accent)] hover:underline"
                  >
                    查看登记资源
                  </Link>
                )}
              </CardHeader>
              <CardContent className="space-y-6">
                <dl className="grid gap-3 text-xs sm:grid-cols-2">
                  {[
                    ["来源快照 ID", source.id],
                    [
                      "关联目标",
                      `${source.target_entity_kind} / ${source.target_entity_id}`,
                    ],
                    ["Binding ID", source.binding_id],
                    ["请求 Revision", source.revision || "默认版本"],
                    ["Commit", source.commit_sha || "未提供"],
                    [
                      "登记时间",
                      new Date(source.created_at).toLocaleString("zh-CN"),
                    ],
                    ["ModelVersion", source.model_version_id || "不适用"],
                    ["DatasetVersion", source.dataset_version_id || "不适用"],
                    ["CodeRepository", source.code_repository_id || "不适用"],
                    ["元数据来源 Hash", source.source_hash],
                    ["冻结快照 SHA-256", source.snapshot_sha256],
                  ].map(([label, value]) => (
                    <div key={label}>
                      <dt className="text-[var(--muted)]">{label}</dt>
                      <dd className="mt-1 break-all font-mono leading-5">
                        {value}
                      </dd>
                    </div>
                  ))}
                </dl>
                {(source.candidate.warnings ?? []).length > 0 && (
                  <ul className="list-disc space-y-1 rounded-lg bg-amber-500/5 p-4 pl-7 text-xs leading-5">
                    {[...new Set(source.candidate.warnings)].map((warning) => (
                      <li key={warning}>{warning}</li>
                    ))}
                  </ul>
                )}
                <RepositoryMetadataView candidate={source.candidate} />
              </CardContent>
            </Card>
            <RepositoryAssetsPanel sourceId={source.id} />
          </>
        )
      )}
    </div>
  );
}
