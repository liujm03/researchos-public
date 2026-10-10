"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { RegistryMetadataForm } from "./metadata-form";
import { DatasetVersionForm } from "./dataset-version-form";
import { ModelVersionForm } from "./model-version-form";
import { NumberCell } from "./fields";
import { api } from "@/lib/api";
import type {
  Dataset,
  DatasetVersion,
  DatasetVersionPage,
  ResearchModel,
  ModelVersion,
  ModelVersionPage,
} from "@/lib/experiments";

function DatasetVersionView({ version }: { version: DatasetVersion }) {
  const classes = version.classes ?? [];
  const splits = version.splits ?? [];
  return (
    <details className="rounded border border-[var(--border)] p-4">
      <summary className="cursor-pointer text-sm font-medium">
        {version.version} · <NumberCell value={version.number_images} /> 图像
      </summary>
      <div className="mt-4 space-y-4 text-xs">
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            版本 ID：<span className="break-all font-mono">{version.id}</span>
          </div>
          <div>分辨率：{version.resolution ?? "未记录"}</div>
          <div>标注格式：{version.annotation_format ?? "未记录"}</div>
          <div>
            创建：{new Date(version.created_at).toLocaleString("zh-CN")}
          </div>
        </div>
        <p className="break-all font-mono">
          清单 SHA-256：{version.manifest_sha256 ?? "未记录"}
        </p>
        <div>
          <h4 className="mb-2 font-semibold">类别</h4>
          {classes.length ? (
            <div className="flex flex-wrap gap-2">
              {classes.map((item) => (
                <span
                  key={item.class_index}
                  className="rounded border border-[var(--border)] px-2 py-1"
                >
                  {item.class_index} · {item.name}
                </span>
              ))}
            </div>
          ) : (
            <p className="text-[var(--muted)]">未记录类别。</p>
          )}
        </div>
        <div>
          <h4 className="mb-2 font-semibold">数据划分</h4>
          {splits.length ? (
            <div className="overflow-x-auto">
              <table className="w-full text-left">
                <thead className="text-[var(--muted)]">
                  <tr>
                    <th className="py-2">划分</th>
                    <th>样本量</th>
                    <th>清单</th>
                  </tr>
                </thead>
                <tbody>
                  {splits.map((split) => (
                    <tr
                      key={split.split_name}
                      className="border-t border-[var(--border)]"
                    >
                      <td className="py-2">{split.split_name}</td>
                      <td>
                        <NumberCell value={split.sample_count} />
                      </td>
                      <td className="break-all">
                        {split.manifest_uri ?? "未记录"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-[var(--muted)]">
              未记录 Train / Validation / Test。
            </p>
          )}
        </div>
        <div>
          <h4 className="mb-2 font-semibold">数据位置</h4>
          {version.locations.length ? (
            <div className="space-y-2">
              {version.locations.map((location) => (
                <div
                  key={location.id}
                  className="rounded border border-[var(--border)] p-2"
                >
                  <p className="break-all">
                    {location.storage_provider} · {location.uri}
                  </p>
                  {location.mount_hint && (
                    <p className="mt-1 text-[var(--muted)]">
                      {location.mount_hint}
                    </p>
                  )}
                  <p className="mt-1 text-[var(--muted)]">
                    验证时间：
                    {location.verified_at
                      ? new Date(location.verified_at).toLocaleString("zh-CN")
                      : "尚未验证"}
                  </p>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-[var(--muted)]">未记录数据位置。</p>
          )}
        </div>
      </div>
    </details>
  );
}
function ModelVersionView({ version }: { version: ModelVersion }) {
  return (
    <details className="rounded border border-[var(--border)] p-4">
      <summary className="cursor-pointer text-sm font-medium">
        {version.version} · 参数量 <NumberCell value={version.parameters} />
      </summary>
      <div className="mt-4 space-y-4 text-xs">
        <div className="grid gap-3 sm:grid-cols-2">
          <div>输入尺寸：{version.input_size ?? "未记录"}</div>
          <div>
            FLOPs：
            <NumberCell value={version.flops} />
          </div>
          <div>
            FPS：
            <NumberCell value={version.fps} />
          </div>
          <div>
            创建：{new Date(version.created_at).toLocaleString("zh-CN")}
          </div>
        </div>
        <p className="break-all font-mono">版本 ID：{version.id}</p>
        <p className="break-all font-mono">
          代码仓库：{version.code_repository_id ?? "未关联"} · Commit：
          {version.git_commit ?? "未记录"}
        </p>
        {version.checkpoint_attachment_id && (
          <a
            href={
              "/api/v1/attachments/" +
              version.checkpoint_attachment_id +
              "/download"
            }
            className="inline-block text-[var(--accent)] hover:underline"
          >
            下载关联 Checkpoint →
          </a>
        )}
        <div>
          <h4 className="mb-2 font-semibold">
            Backbone / Neck / Head / Fusion / Loss
          </h4>
          {version.components.length ? (
            <div className="space-y-2">
              {version.components.map((component) => (
                <div
                  key={component.id}
                  className="rounded border border-[var(--border)] p-2"
                >
                  <p className="font-medium">
                    {component.sort_order} · {component.component_type} ·{" "}
                    {component.name}
                  </p>
                  {component.description && (
                    <p className="mt-1 whitespace-pre-wrap text-[var(--muted)]">
                      {component.description}
                    </p>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <p className="text-[var(--muted)]">未记录结构模块。</p>
          )}
        </div>
      </div>
    </details>
  );
}

export function RegistryDetailView({
  kind,
  id,
}: {
  kind: "datasets" | "models";
  id: string;
}) {
  const [record, setRecord] = useState<Dataset | ResearchModel | null>(null);
  const [versions, setVersions] = useState<
    DatasetVersionPage | ModelVersionPage | null
  >(null);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [archiving, setArchiving] = useState(false);
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [metadata, versionPage] = await Promise.all([
        api.get<Dataset | ResearchModel>(
          "/" + kind + "/" + encodeURIComponent(id),
        ),
        api.get<DatasetVersionPage | ModelVersionPage>(
          "/" +
            kind +
            "/" +
            encodeURIComponent(id) +
            "/versions?limit=20&offset=" +
            offset,
        ),
      ]);
      setRecord(metadata);
      setVersions(versionPage);
      setError("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "无法读取版本化资源");
    } finally {
      setLoading(false);
    }
  }, [id, kind, offset]);
  useEffect(() => {
    queueMicrotask(() => void load());
  }, [load]);
  async function created() {
    setMessage("新版本已登记，原版本保留。");
    if (offset !== 0) setOffset(0);
    else await load();
  }
  async function toggleArchive() {
    if (!record) return;
    setArchiving(true);
    setError("");
    try {
      if (record.archived_at)
        await api.patch("/" + kind + "/" + encodeURIComponent(id), {
          archived: false,
        });
      else await api.delete("/" + kind + "/" + encodeURIComponent(id));
      await load();
      setMessage(
        record.archived_at
          ? "资源已恢复。"
          : "资源已归档，版本与实验关联保留。",
      );
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "更新归档状态失败");
    } finally {
      setArchiving(false);
    }
  }
  if (loading && !record) return <LoadingState />;
  if (!record)
    return (
      <ErrorState message={error || "资源不存在"} onRetry={() => void load()} />
    );
  return (
    <div className="space-y-6">
      <Link
        href={"/" + kind}
        className="inline-flex items-center gap-2 text-xs text-[var(--muted)] hover:text-[var(--accent)]"
      >
        <ArrowLeft className="h-4 w-4" />
        返回{kind === "datasets" ? "数据集" : "模型"}管理
      </Link>
      <div>
        <h1 className="text-2xl font-semibold">{record.name}</h1>
        <p className="mt-2 text-sm text-[var(--muted)]">
          {record.task} ·{" "}
          {(record.modalities ?? []).join(" / ") || "模态未记录"}
        </p>
        {record.archived_at && (
          <p className="mt-2 text-xs text-amber-700 dark:text-amber-300">
            此资源已归档；历史版本仍可核对。
          </p>
        )}
      </div>
      {error && <ErrorState message={error} onRetry={() => void load()} />}
      {message && (
        <p role="status" className="text-sm text-[var(--accent)]">
          {message}
        </p>
      )}
      <Card>
        <CardHeader>
          <h2 className="font-semibold">注册信息</h2>
          <Button
            size="sm"
            variant="ghost"
            disabled={archiving}
            onClick={() => void toggleArchive()}
          >
            {archiving
              ? "更新中…"
              : record.archived_at
                ? "恢复资源"
                : "归档资源"}
          </Button>
        </CardHeader>
        <CardContent>
          <RegistryMetadataForm
            key={record.id + "-" + record.updated_at}
            kind={kind}
            record={record}
            onSaved={(updated) => {
              setRecord(updated);
              setMessage("注册信息已保存。");
            }}
          />
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <h2 className="font-semibold">登记不可变版本</h2>
        </CardHeader>
        <CardContent>
          {kind === "datasets" ? (
            <DatasetVersionForm
              datasetId={id}
              onCreated={() => void created()}
            />
          ) : (
            <ModelVersionForm modelId={id} onCreated={() => void created()} />
          )}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <h2 className="font-semibold">版本记录</h2>
          <Button
            size="sm"
            variant="ghost"
            disabled={loading}
            onClick={() => void load()}
          >
            刷新版本
          </Button>
        </CardHeader>
        <CardContent className="space-y-3">
          {versions?.items.length
            ? kind === "datasets"
              ? (versions.items as DatasetVersion[]).map((version) => (
                  <DatasetVersionView key={version.id} version={version} />
                ))
              : (versions.items as ModelVersion[]).map((version) => (
                  <ModelVersionView key={version.id} version={version} />
                ))
            : !error && (
                <EmptyState
                  title="尚无版本记录"
                  detail="实验运行需要关联明确的数据集与模型版本。"
                />
              )}
          {versions && (
            <div className="flex items-center justify-between gap-3 text-xs text-[var(--muted)]">
              <Button
                size="sm"
                variant="ghost"
                disabled={loading || offset === 0}
                onClick={() => setOffset(Math.max(0, offset - versions.limit))}
              >
                上一页版本
              </Button>
              <span>共 {versions.total} 个版本</span>
              <Button
                size="sm"
                variant="ghost"
                disabled={loading || offset + versions.limit >= versions.total}
                onClick={() => setOffset(offset + versions.limit)}
              >
                下一页版本
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
