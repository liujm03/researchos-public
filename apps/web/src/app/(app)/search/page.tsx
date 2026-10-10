"use client";

import Link from "next/link";
import { useRef, useState, type FormEvent } from "react";
import { ArrowRight, Search } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { api, type SearchResult } from "@/lib/api";

type SearchType =
  | "all"
  | "paper"
  | "project"
  | "task"
  | "note"
  | "codex_task"
  | "idea"
  | "claim";

const filters: { value: SearchType; label: string }[] = [
  { value: "all", label: "全部" },
  { value: "paper", label: "论文" },
  { value: "project", label: "课题" },
  { value: "task", label: "任务" },
  { value: "note", label: "笔记" },
  { value: "codex_task", label: "Codex" },
  { value: "idea", label: "科研灵感" },
  { value: "claim", label: "科研主张" },
];
const typeLabels: Record<string, string> = {
  paper: "论文",
  project: "课题",
  task: "任务",
  note: "笔记",
  codex_task: "Codex 任务",
  idea: "科研灵感",
  claim: "科研主张",
};
const fieldLabels: Record<string, string> = {
  title: "标题",
  name: "名称",
  abstract: "摘要",
  summary: "概述",
  description: "描述",
  body_markdown: "正文",
  prompt: "任务内容",
  body: "正文",
  full_text: "全文词项",
  doi: "DOI",
  arxiv_id: "arXiv ID",
  text: "主张原文",
  conditions: "适用条件",
  limitations: "结论局限",
};

function searchPath(query: string, type: SearchType, cursor?: string) {
  const params = new URLSearchParams({ q: query, limit: "20" });
  if (type !== "all") params.set("types", type);
  if (cursor) params.set("cursor", cursor);
  return `/search?${params.toString()}`;
}

export default function SearchPage() {
  const [query, setQuery] = useState("");
  const [activeQuery, setActiveQuery] = useState("");
  const [type, setType] = useState<SearchType>("all");
  const [result, setResult] = useState<SearchResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");
  const requestId = useRef(0);
  const pendingSearch = useRef<string | null>(null);
  const loadingMoreRef = useRef(false);

  async function runSearch(text: string, selectedType: SearchType) {
    const trimmed = text.trim();
    if (trimmed.length < 2) return;
    const key = `${selectedType}:${trimmed}`;
    if (pendingSearch.current === key) return;

    const id = ++requestId.current;
    pendingSearch.current = key;
    loadingMoreRef.current = false;
    setActiveQuery(trimmed);
    setResult(null);
    setLoading(true);
    setLoadingMore(false);
    setError("");
    try {
      const page = await api.get<SearchResult>(
        searchPath(trimmed, selectedType),
      );
      if (id === requestId.current) setResult(page);
    } catch (cause) {
      if (id === requestId.current)
        setError(cause instanceof Error ? cause.message : "搜索失败");
    } finally {
      if (id === requestId.current) {
        pendingSearch.current = null;
        setLoading(false);
      }
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    void runSearch(query, type);
  }

  function selectType(selectedType: SearchType) {
    if (selectedType === type) return;
    setType(selectedType);
    if (activeQuery) void runSearch(activeQuery, selectedType);
  }

  async function loadMore() {
    const cursor = result?.page.next_cursor;
    if (!cursor || !activeQuery || loading || loadingMoreRef.current) return;

    loadingMoreRef.current = true;
    setLoadingMore(true);
    setError("");
    const id = requestId.current;
    try {
      const page = await api.get<SearchResult>(
        searchPath(activeQuery, type, cursor),
      );
      if (id !== requestId.current) return;
      setResult((previous) => {
        if (!previous) return previous;
        const seen = new Set(
          previous.items.map((hit) => `${hit.type}:${hit.entity_id}`),
        );
        const newItems = page.items.filter((hit) => {
          const key = `${hit.type}:${hit.entity_id}`;
          if (seen.has(key)) return false;
          seen.add(key);
          return true;
        });
        return { items: [...previous.items, ...newItems], page: page.page };
      });
    } catch (cause) {
      if (id === requestId.current)
        setError(cause instanceof Error ? cause.message : "加载更多结果失败");
    } finally {
      if (id === requestId.current) {
        loadingMoreRef.current = false;
        setLoadingMore(false);
      }
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <p className="mb-1 text-xs font-medium uppercase tracking-[0.18em] text-[var(--accent)]">
          Global search
        </p>
        <h1 className="text-2xl font-semibold">全局搜索</h1>
        <p className="mt-1 text-sm text-[var(--muted)]">
          检索课题、论文、任务、Codex 任务与阅读笔记。
        </p>
      </div>

      <form onSubmit={submit} className="flex max-w-2xl gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-[var(--muted)]" />
          <Input
            required
            minLength={2}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            className="pl-9"
            placeholder="输入至少两个字符"
          />
        </div>
        <Button type="submit" disabled={loading}>
          {loading ? "搜索中…" : "搜索"}
        </Button>
      </form>

      <div
        className="flex flex-wrap gap-1.5"
        role="group"
        aria-label="筛选结果类型"
      >
        {filters.map((filter) => (
          <Button
            key={filter.value}
            type="button"
            size="sm"
            variant={type === filter.value ? "default" : "secondary"}
            aria-pressed={type === filter.value}
            onClick={() => selectType(filter.value)}
          >
            {filter.label}
          </Button>
        ))}
      </div>

      {error && (
        <ErrorState
          message={error}
          onRetry={() => {
            if (result?.items.length) void loadMore();
            else void runSearch(activeQuery, type);
          }}
        />
      )}

      {loading ? (
        <LoadingState label="正在搜索…" />
      ) : !activeQuery ? (
        <Card>
          <EmptyState
            title="输入关键词开始搜索"
            detail="例如：RGB-T、山火、baseline"
          />
        </Card>
      ) : result?.items.length ? (
        <Card>
          <div className="divide-y divide-[var(--border)]">
            {result.items.map((item) => {
              const fields = item.matched_fields;
              return (
                <Link
                  key={`${item.type}-${item.entity_id}`}
                  href={item.href}
                  className="flex items-center justify-between gap-3 px-5 py-4 hover:bg-[var(--surface-hover)]"
                >
                  <div className="min-w-0">
                    <div className="mb-1 text-[11px] text-[var(--accent)]">
                      {typeLabels[item.type] ?? item.type}
                    </div>
                    <div className="truncate text-sm font-medium">
                      {item.title}
                    </div>
                    {item.snippet && (
                      <p className="mt-1 line-clamp-2 text-xs text-[var(--muted)]">
                        {item.snippet}
                      </p>
                    )}
                    {fields?.length ? (
                      <p className="mt-1 text-[11px] text-[var(--muted)]">
                        匹配：
                        {fields
                          .map((field) => fieldLabels[field] ?? field)
                          .join("、")}
                      </p>
                    ) : null}
                  </div>
                  <ArrowRight className="h-4 w-4 shrink-0 text-[var(--muted)]" />
                </Link>
              );
            })}
          </div>
        </Card>
      ) : result ? (
        <Card>
          <EmptyState
            title="没有匹配的记录"
            detail="尝试更短的关键词，或先添加文献与课题。"
          />
        </Card>
      ) : null}

      {result && (
        <p className="text-xs text-[var(--muted)]">
          已显示 {result.items.length}
          {result.page.total != null ? ` / ${result.page.total}` : ""} 条结果
        </p>
      )}
      {result?.page.next_cursor && (
        <div className="text-center">
          <Button
            type="button"
            variant="secondary"
            disabled={loadingMore}
            onClick={() => void loadMore()}
          >
            {loadingMore ? "加载中…" : "加载更多"}
          </Button>
        </div>
      )}
    </div>
  );
}
