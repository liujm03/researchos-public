"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowRight, RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import {
  api,
  type LiteratureProvider,
  type LiteratureProviders,
} from "@/lib/api";

const configurationLabels: Record<
  LiteratureProvider["configuration_status"],
  string
> = {
  configured: "已配置",
  disabled: "未启用",
  missing: "待配置",
  invalid: "配置异常",
  not_implemented: "尚未实现",
};

const kindLabels: Record<LiteratureProvider["kind"], string> = {
  literature: "文献元数据",
  reference_manager: "文献管理器",
  author_identity: "作者身份",
};

const capabilityLabels: Record<string, string> = {
  get_paper: "按来源 ID 查询论文",
  get_paper_by_id: "按来源 ID 查询论文",
  get_paper_by_doi: "DOI 元数据查询",
  get_paper_by_arxiv_id: "arXiv ID 元数据查询",
  search_papers: "搜索公开文献",
  connection_status: "主动连接诊断",
  list_collections: "浏览文献集合",
  search_items: "检索文献条目",
  get_item: "读取单篇条目",
  list_attachments: "列出可用附件",
  open_attachment: "按需读取附件",
  get_indexed_fulltext: "读取已索引全文",
  changes_since: "只读增量同步",
};

function localEntrypoint(value: string | null) {
  return value &&
    value.startsWith("/") &&
    !value.startsWith("//") &&
    !value.includes("\\")
    ? value
    : null;
}

export function LiteratureProviderCatalog() {
  const [catalog, setCatalog] = useState<LiteratureProviders | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showPlanned, setShowPlanned] = useState(false);

  function refresh() {
    setLoading(true);
    setError("");
    api
      .get<LiteratureProviders>("/literature/providers")
      .then(setCatalog)
      .catch((cause) =>
        setError(
          cause instanceof Error ? cause.message : "无法读取文献来源目录。",
        ),
      )
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    let active = true;
    api
      .get<LiteratureProviders>("/literature/providers")
      .then((result) => {
        if (active) setCatalog(result);
      })
      .catch((cause) => {
        if (active)
          setError(
            cause instanceof Error ? cause.message : "无法读取文献来源目录。",
          );
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  return (
    <Card>
      <CardHeader>
        <div>
          <h2 className="font-semibold">文献来源与能力</h2>
          <p className="mt-1 text-xs text-[var(--muted)]">
            读取当前适配器与配置状态，查询或同步由你在对应页面主动发起。
          </p>
        </div>
        <Button
          type="button"
          variant="secondary"
          disabled={loading}
          onClick={refresh}
        >
          <RefreshCw className="h-4 w-4" />
          刷新目录
        </Button>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-xs leading-5 text-[var(--muted)]">
          “已配置”表示服务器参数齐备；远端连接尚未验证。刷新此目录只读取服务器状态，不连接第三方服务。
        </p>
        {loading ? (
          <LoadingState label="正在读取文献来源目录…" />
        ) : error ? (
          <ErrorState message={error} onRetry={refresh} />
        ) : catalog?.providers.length ? (
          <div className="grid gap-3 lg:grid-cols-2">
            {catalog.providers
              .filter(
                (provider) =>
                  showPlanned ||
                  provider.implementation_status === "implemented",
              )
              .map((provider) => {
                const entrypoint =
                  provider.implementation_status === "implemented"
                    ? localEntrypoint(provider.entrypoint)
                    : null;
                return (
                  <div
                    key={provider.provider_key}
                    className="space-y-3 rounded-lg border border-[var(--border)] p-4"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div>
                        <h3 className="text-sm font-medium">
                          {provider.label}
                        </h3>
                        <p className="mt-1 text-xs text-[var(--muted)]">
                          {kindLabels[provider.kind]} ·{" "}
                          {provider.implementation_status === "implemented"
                            ? "已实现"
                            : "计划中"}
                        </p>
                      </div>
                      <span
                        className={
                          provider.configuration_status === "configured"
                            ? "text-xs text-emerald-600"
                            : provider.configuration_status === "invalid"
                              ? "text-xs text-red-600"
                              : "text-xs text-[var(--muted)]"
                        }
                      >
                        {configurationLabels[provider.configuration_status]}
                      </span>
                    </div>
                    <details>
                      <summary className="cursor-pointer text-xs text-[var(--muted)]">
                        来源详情与能力
                      </summary>
                      <p className="mt-2 text-xs leading-5 text-[var(--muted)]">
                        {provider.description}
                      </p>
                      {provider.capabilities.length ? (
                        <div className="flex flex-wrap gap-1.5">
                          {provider.capabilities.map((capability) => (
                            <span
                              key={capability}
                              className="rounded bg-[var(--surface-hover)] px-2 py-1 text-[11px]"
                            >
                              {capabilityLabels[capability] ?? capability}
                            </span>
                          ))}
                        </div>
                      ) : (
                        <p className="text-xs text-[var(--muted)]">
                          {provider.implementation_status === "planned"
                            ? "尚无可用接口。"
                            : "当前无已启用能力。"}
                        </p>
                      )}
                    </details>
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="text-xs text-[var(--muted)]">
                        {provider.connectivity_status === "not_tested"
                          ? "连接未验证"
                          : provider.connectivity_status}
                      </span>
                      {entrypoint && (
                        <Link
                          href={entrypoint}
                          className="inline-flex items-center gap-1 text-xs text-[var(--accent)] underline"
                        >
                          {provider.configuration_status === "configured"
                            ? "打开来源页面"
                            : "查看配置"}
                          <ArrowRight className="h-3 w-3" />
                        </Link>
                      )}
                    </div>
                  </div>
                );
              })}
          </div>
        ) : (
          <EmptyState
            title="暂无文献来源目录"
            detail="服务器尚未提供来源能力信息。"
          />
        )}
        {catalog &&
          catalog.providers.some(
            (provider) => provider.implementation_status !== "implemented",
          ) && (
            <Button
              type="button"
              variant="ghost"
              onClick={() => setShowPlanned(!showPlanned)}
            >
              {showPlanned ? "收起规划中的来源" : "查看规划中的来源"}
            </Button>
          )}
      </CardContent>
    </Card>
  );
}
