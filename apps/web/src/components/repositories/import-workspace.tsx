"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { api } from "@/lib/api";
import {
  repositoryKindLabels,
  type RepositoryImport,
  type RepositoryImportPage,
  type RepositoryProviders,
} from "@/lib/repositories";
import { RepositoryLookupForm } from "./lookup-form";
import { RepositoryImportPreview } from "./import-preview";

export function RepositoryImportWorkspace() {
  const query = useSearchParams();
  const [catalog, setCatalog] = useState<RepositoryProviders | null>(null);
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [catalogError, setCatalogError] = useState("");
  const [history, setHistory] = useState<RepositoryImportPage | null>(null);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyError, setHistoryError] = useState("");
  const [offset, setOffset] = useState(0);
  const [record, setRecord] = useState<RepositoryImport | null>(null);
  const [opening, setOpening] = useState<string | null>(null);
  const [openError, setOpenError] = useState("");
  const [lastOpened, setLastOpened] = useState<string | null>(null);
  const catalogGeneration = useRef(0);
  const historyGeneration = useRef(0);
  const openGeneration = useRef(0);
  const requestedId = query.get("import");
  const loadCatalog = useCallback(async () => {
    const request = ++catalogGeneration.current;
    setCatalogLoading(true);
    setCatalogError("");
    try {
      const result = await api.get<RepositoryProviders>(
        "/repository-providers",
      );
      if (request === catalogGeneration.current) setCatalog(result);
    } catch (cause) {
      if (request === catalogGeneration.current)
        setCatalogError(
          cause instanceof Error ? cause.message : "无法读取仓库来源能力",
        );
    } finally {
      if (request === catalogGeneration.current) setCatalogLoading(false);
    }
  }, []);
  const loadHistory = useCallback(async () => {
    const request = ++historyGeneration.current;
    setHistoryLoading(true);
    setHistoryError("");
    try {
      const result = await api.get<RepositoryImportPage>(
        `/repository-imports?limit=20&offset=${offset}`,
      );
      if (request === historyGeneration.current) setHistory(result);
    } catch (cause) {
      if (request === historyGeneration.current)
        setHistoryError(
          cause instanceof Error ? cause.message : "无法读取仓库导入历史",
        );
    } finally {
      if (request === historyGeneration.current) setHistoryLoading(false);
    }
  }, [offset]);
  const openPreview = useCallback(async (id: string) => {
    const request = ++openGeneration.current;
    setLastOpened(id);
    setRecord(null);
    setOpening(id);
    setOpenError("");
    try {
      const result = await api.get<RepositoryImport>(
        `/repository-imports/${encodeURIComponent(id)}`,
      );
      if (request === openGeneration.current) setRecord(result);
    } catch (cause) {
      if (request === openGeneration.current)
        setOpenError(
          cause instanceof Error ? cause.message : "无法读取历史预览",
        );
    } finally {
      if (request === openGeneration.current) setOpening(null);
    }
  }, []);
  useEffect(() => {
    let active = true;
    const controller = catalogGeneration;
    queueMicrotask(() => {
      if (active) void loadCatalog();
    });
    return () => {
      active = false;
      controller.current++;
    };
  }, [loadCatalog]);
  useEffect(() => {
    let active = true;
    const controller = historyGeneration;
    queueMicrotask(() => {
      if (active) void loadHistory();
    });
    return () => {
      active = false;
      controller.current++;
    };
  }, [loadHistory]);
  useEffect(() => {
    let active = true;
    const controller = openGeneration;
    queueMicrotask(() => {
      if (active && requestedId) void openPreview(requestedId);
    });
    return () => {
      active = false;
      controller.current++;
    };
  }, [requestedId, openPreview]);
  function selected(result: RepositoryImport) {
    openGeneration.current++;
    setOpening(null);
    setOpenError("");
    setRecord(result);
    void loadHistory();
  }
  function confirmed(result: RepositoryImport) {
    // A confirmation may finish after the owner opens another preview.
    setRecord((current) => (current?.id === result.id ? result : current));
    void loadHistory();
  }
  return (
    <div className="space-y-6">
      <div>
        <p className="mb-1 text-xs uppercase tracking-[0.18em] text-[var(--accent)]">
          Open source repositories
        </p>
        <h1 className="text-2xl font-semibold">开源仓库</h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-[var(--muted)]">
          通过 GitHub / Hugging Face
          官方元数据接口读取公开资源，预览后由你确认登记模型、数据集或代码仓库。当前导入元数据与说明文本，实验执行在独立工作流中进行。
        </p>
      </div>
      <Card>
        <CardHeader>
          <h2 className="font-semibold">公开资源导入</h2>
          <Button
            variant="ghost"
            size="sm"
            disabled={catalogLoading}
            onClick={() => void loadCatalog()}
          >
            刷新来源状态
          </Button>
        </CardHeader>
        <CardContent>
          {catalogLoading ? (
            <LoadingState label="正在读取来源配置…" />
          ) : catalogError ? (
            <ErrorState
              message={catalogError}
              onRetry={() => void loadCatalog()}
            />
          ) : catalog?.items.length ? (
            <RepositoryLookupForm
              key={`${query.get("provider")}:${query.get("kind")}`}
              catalog={catalog}
              initialProvider={query.get("provider")}
              initialKind={query.get("kind")}
              onLookupStart={() => {
                openGeneration.current++;
                setRecord(null);
                setOpening(null);
                setOpenError("");
              }}
              onPreview={selected}
            />
          ) : (
            <EmptyState
              title="尚无可用的仓库来源"
              detail="启用服务器适配器后再读取公开元数据。"
            />
          )}
        </CardContent>
      </Card>
      {openError && (
        <ErrorState
          message={openError}
          onRetry={lastOpened ? () => void openPreview(lastOpened) : undefined}
        />
      )}
      {opening && <LoadingState label="正在读取冻结预览…" />}
      {record && (
        <RepositoryImportPreview record={record} onConfirmed={confirmed} />
      )}
      <Card>
        <CardHeader>
          <h2 className="font-semibold">导入与来源历史</h2>
          <Button
            variant="ghost"
            size="sm"
            disabled={historyLoading}
            onClick={() => void loadHistory()}
          >
            刷新历史
          </Button>
        </CardHeader>
        <CardContent className="space-y-4">
          {historyError && (
            <ErrorState
              message={historyError}
              onRetry={() => void loadHistory()}
            />
          )}
          {historyLoading ? (
            <LoadingState label="正在读取导入历史…" />
          ) : history?.items.length ? (
            <ul className="divide-y divide-[var(--border)]">
              {history.items.map((item) => (
                <li key={item.id} className="space-y-2 py-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <h3 className="text-sm font-medium">
                        {item.candidate.name}
                      </h3>
                      <p className="mt-1 text-xs text-[var(--muted)]">
                        {item.provider_key} ·{" "}
                        {repositoryKindLabels[item.repo_kind]} ·{" "}
                        {item.status === "CONFIRMED" ? "已登记" : "待确认"} ·{" "}
                        {new Date(item.created_at).toLocaleString("zh-CN")}
                      </p>
                    </div>
                    <div className="flex items-center gap-3">
                      <Button
                        variant="secondary"
                        size="sm"
                        disabled={opening !== null}
                        onClick={() => void openPreview(item.id)}
                      >
                        查看预览
                      </Button>
                      {item.source_snapshot_id && (
                        <Link
                          className="text-xs text-[var(--accent)] hover:underline"
                          href={`/integrations/repositories/sources/${encodeURIComponent(item.source_snapshot_id)}`}
                        >
                          冻结来源
                        </Link>
                      )}
                    </div>
                  </div>
                  <p className="break-all font-mono text-[10px] text-[var(--muted)]">
                    {item.repo_id} · {item.revision || "默认版本"} ·{" "}
                    {item.source_hash}
                  </p>
                </li>
              ))}
            </ul>
          ) : (
            !historyError && (
              <EmptyState
                title="尚无仓库导入记录"
                detail="输入公开仓库并获取预览；确认后保留来源与版本回执。"
              />
            )
          )}
          {history && (
            <div className="flex items-center justify-between gap-3 text-xs text-[var(--muted)]">
              <Button
                size="sm"
                variant="ghost"
                disabled={historyLoading || offset === 0}
                onClick={() => setOffset(Math.max(0, offset - 20))}
              >
                上一页导入
              </Button>
              <span>
                共 {history.total} 项 · 第 {Math.floor(offset / 20) + 1} 页
              </span>
              <Button
                size="sm"
                variant="ghost"
                disabled={
                  historyLoading ||
                  offset + history.items.length >= history.total
                }
                onClick={() => setOffset(offset + 20)}
              >
                下一页导入
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
