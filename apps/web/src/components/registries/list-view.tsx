"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { RegistryMetadataForm } from "./metadata-form";
import { api } from "@/lib/api";
import type { DatasetPage, ModelPage } from "@/lib/experiments";

export function RegistryListView({ kind }: { kind: "datasets" | "models" }) {
  const router = useRouter();
  const [page, setPage] = useState<DatasetPage | ModelPage | null>(null);
  const [offset, setOffset] = useState(0);
  const [createMounted, setCreateMounted] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    setLoading(true);
    try {
      setPage(
        await api.get<DatasetPage | ModelPage>(
          "/" + kind + "?limit=20&offset=" + offset,
        ),
      );
      setError("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "无法读取注册表");
    } finally {
      setLoading(false);
    }
  }, [kind, offset]);
  useEffect(() => {
    queueMicrotask(() => void load());
  }, [load]);
  const title = kind === "datasets" ? "数据集管理" : "模型管理";
  return (
    <div className="space-y-6">
      <div>
        <p className="mb-1 text-xs uppercase tracking-[0.18em] text-[var(--accent)]">
          {kind === "datasets" ? "Dataset registry" : "Model registry"}
        </p>
        <h1 className="text-2xl font-semibold">{title}</h1>
        <p className="mt-1 text-sm text-[var(--muted)]">
          登记研究资源，并为实验保留不可覆盖的明确版本。
        </p>
        <Link
          href={`/integrations/repositories?provider=huggingface&kind=${kind === "datasets" ? "dataset" : "model"}`}
          className="mt-3 inline-block text-xs text-[var(--accent)] hover:underline"
        >
          从 Hugging Face 导入{kind === "datasets" ? "数据集" : "模型"}元数据
        </Link>
      </div>
      {error && <ErrorState message={error} onRetry={() => void load()} />}

      <Card>
        <CardHeader>
          <h2 className="font-semibold">已登记资源</h2>
          <Button
            size="sm"
            variant="ghost"
            disabled={loading}
            onClick={() => void load()}
          >
            刷新
          </Button>
        </CardHeader>
        <CardContent>
          {loading && !page ? (
            <LoadingState />
          ) : page?.items.length ? (
            <div className="divide-y divide-[var(--border)]">
              {page.items.map((record) => (
                <Link
                  key={record.id}
                  href={"/" + kind + "/" + record.id}
                  className="block py-3 hover:text-[var(--accent)]"
                >
                  <div className="text-sm font-medium">{record.name}</div>
                  <div className="mt-1 text-xs text-[var(--muted)]">
                    {record.task} ·{" "}
                    {(record.modalities ?? []).join(" / ") || "模态未记录"}
                  </div>
                </Link>
              ))}
            </div>
          ) : (
            !error && (
              <EmptyState
                title="尚无登记资源"
                detail="先登记资源，再在详情中创建研究使用的版本。"
              />
            )
          )}
          {page && (
            <div className="mt-4 flex items-center justify-between gap-3 text-xs text-[var(--muted)]">
              <Button
                size="sm"
                variant="ghost"
                disabled={loading || offset === 0}
                onClick={() => setOffset(Math.max(0, offset - page.limit))}
              >
                上一页资源
              </Button>
              <span>
                共 {page.total} 项 · 第 {Math.floor(offset / page.limit) + 1} 页
              </span>
              <Button
                size="sm"
                variant="ghost"
                disabled={loading || offset + page.limit >= page.total}
                onClick={() => setOffset(offset + page.limit)}
              >
                下一页资源
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
      <details
        className="rounded-md border border-[var(--border)] bg-[var(--surface)]"
        onToggle={(event) => {
          if (event.currentTarget.open) setCreateMounted(true);
        }}
      >
        <summary className="cursor-pointer px-4 py-3 text-sm font-medium">
          {kind === "datasets" ? "新增数据集" : "新增模型"}
        </summary>
        {createMounted && (
          <>
            {" "}
            <Card>
              <CardHeader>
                <h2 className="font-semibold">
                  新增{kind === "datasets" ? "数据集" : "模型"}
                </h2>
              </CardHeader>
              <CardContent>
                <RegistryMetadataForm
                  kind={kind}
                  onSaved={(record) =>
                    router.push("/" + kind + "/" + record.id)
                  }
                />
              </CardContent>
            </Card>
          </>
        )}
      </details>
    </div>
  );
}
