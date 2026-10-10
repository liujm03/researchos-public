"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowRight, Inbox, ShieldCheck } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { api, type InboxItem } from "@/lib/api";
import { formatDate } from "@/lib/utils";
import {
  ClassificationEditor,
  ClassificationFilters,
  ProjectLabels,
  ZoteroSourceLabels,
  RefreshZoteroFolders,
  classificationQuery,
  emptyClassificationFilter,
  readClassificationFilter,
  type ClassificationOptions,
  type ClassificationFilterValue,
} from "@/components/literature/classification";

const reviewLabels: Record<string, string> = {
  UNREVIEWED: "待审核",
  PENDING: "待审核",
  REVIEWING: "审核中",
  VERIFIED: "已核实",
  ACCEPTED: "已接受",
  REJECTED: "已拒绝",
  SUPERSEDED: "已有新版本",
};
const filters = [
  ["PENDING", "待审核"],
  ["REVIEWING", "审核中"],
  ["ACCEPTED", "已接受"],
  ["REJECTED", "已拒绝"],
] as const;

export default function ResearchInboxPage() {
  const [filter, setFilter] = useState<string>("PENDING");
  const [items, setItems] = useState<InboxItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [classification, setClassification] =
    useState<ClassificationFilterValue>(emptyClassificationFilter);
  const [options, setOptions] = useState<ClassificationOptions | null>(null);
  const [optionsLoading, setOptionsLoading] = useState(true);
  const [optionsError, setOptionsError] = useState("");
  const [filtersReady, setFiltersReady] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [moreLoading, setMoreLoading] = useState(false);
  const sequence = useRef(0);
  const loadOptions = useCallback(() => {
    setOptionsLoading(true);
    api
      .get<ClassificationOptions>("/literature-classification-options")
      .then((value) => {
        setOptions(value);
        setOptionsError("");
      })
      .catch((cause) =>
        setOptionsError(
          cause instanceof Error ? cause.message : "无法加载分类",
        ),
      )
      .finally(() => setOptionsLoading(false));
  }, []);
  useEffect(() => {
    queueMicrotask(() => {
      setClassification(readClassificationFilter());
      const status = new URLSearchParams(window.location.search).get("status");
      if (filters.some(([value]) => value === status)) setFilter(status!);
      setFiltersReady(true);
      loadOptions();
    });
  }, [loadOptions]);

  const load = useCallback(() => {
    if (!filtersReady) return;
    const current = ++sequence.current;
    setLoading(true);
    setItems([]);
    setHasMore(false);
    api
      .get<InboxItem[]>(
        `/research-inbox?status=${encodeURIComponent(filter)}&limit=100&offset=0${classificationQuery(classification)}`,
      )
      .then((result) => {
        if (sequence.current !== current) return;
        setItems(result);
        setHasMore(result.length === 100);
        setError("");
      })
      .catch((cause) => {
        if (sequence.current === current)
          setError(cause instanceof Error ? cause.message : "无法加载精读笔记");
      })
      .finally(() => {
        if (sequence.current === current) setLoading(false);
      });
  }, [filter, filtersReady, classification]);
  useEffect(() => {
    queueMicrotask(load);
  }, [load]);
  async function loadMore() {
    if (moreLoading || !hasMore) return;
    const current = sequence.current;
    setMoreLoading(true);
    try {
      const result = await api.get<InboxItem[]>(
        `/research-inbox?status=${encodeURIComponent(filter)}&limit=100&offset=${items.length}${classificationQuery(classification)}`,
      );
      if (sequence.current !== current) return;
      setItems((previous) => [...previous, ...result]);
      setHasMore(result.length === 100);
    } catch (cause) {
      if (sequence.current === current)
        setError(cause instanceof Error ? cause.message : "加载更多失败");
    } finally {
      setMoreLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="mb-1 text-xs font-medium uppercase tracking-[0.18em] text-[var(--accent)]">
            Research inbox
          </p>
          <h1 className="text-2xl font-semibold">精读笔记</h1>
          <p className="mt-1 text-sm text-[var(--muted)]">
            AI 分析内容先在这里核对；接受后才算已审核，不会自动批准实验。
          </p>
        </div>
        <Link
          href="/note-trash"
          className="inline-flex h-9 items-center rounded-md border border-[var(--border)] px-3 text-sm text-[var(--accent)] hover:bg-[var(--surface-hover)]"
        >
          历史删除记录 →
        </Link>
      </div>
      <div className="flex flex-wrap gap-2">
        {filters.map(([value, label]) => (
          <Button
            key={value}
            variant={filter === value ? "default" : "secondary"}
            size="sm"
            onClick={() => {
              setLoading(true);
              setFilter(value);
            }}
          >
            {label}
          </Button>
        ))}
      </div>
      <ClassificationFilters
        value={classification}
        onChange={setClassification}
        options={options}
        loading={optionsLoading}
        error={optionsError}
        onRetry={loadOptions}
      />
      <RefreshZoteroFolders
        onRefreshed={() => {
          loadOptions();
          load();
        }}
      />
      {error && <ErrorState message={error} onRetry={load} />}
      {loading ? (
        <LoadingState label="正在加载精读笔记…" />
      ) : error && !items.length ? null : items.length ? (
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Inbox className="h-4 w-4 text-[var(--accent)]" />
              <h2 className="font-semibold">
                {filters.find(([value]) => value === filter)?.[1]}
              </h2>
            </div>
            <span className="text-xs text-[var(--muted)]">
              已加载 {items.length} 条{hasMore ? " · 还有更多" : ""}
            </span>
          </CardHeader>
          <div className="divide-y divide-[var(--border)]">
            {items.map((item) => (
              <div key={item.id} className="space-y-2 px-5 py-4">
                <Link
                  href={`/research-notes/${item.note_id}`}
                  className="flex items-center justify-between gap-4 hover:text-[var(--accent)]"
                >
                  <div className="min-w-0">
                    <div className="mb-1 flex items-center gap-2 text-[11px] text-[var(--accent)]">
                      <ShieldCheck className="h-3.5 w-3.5" />
                      {reviewLabels[item.note_review_status] ??
                        item.note_review_status}
                    </div>
                    <div className="line-clamp-1 text-sm font-medium">
                      {item.paper_title}
                    </div>
                    <div className="mt-1 text-xs text-[var(--muted)]">
                      笔记修订 v{item.note_revision} ·{" "}
                      {formatDate(item.created_at)}
                    </div>
                  </div>
                  <ArrowRight className="h-4 w-4 shrink-0 text-[var(--muted)]" />
                </Link>
                <ProjectLabels
                  projects={item.note_classification?.projects}
                  mode={item.note_classification?.mode}
                />
                <ZoteroSourceLabels context={item.literature_context} />
                <ClassificationEditor
                  paperId={item.paper_id}
                  noteId={item.note_id}
                  onSaved={load}
                />
              </div>
            ))}
          </div>
        </Card>
      ) : (
        <Card>
          <CardContent>
            <EmptyState
              title="当前分组与分类没有笔记"
              detail="可调整研究课题或 Zotero 文件夹筛选。"
            />
          </CardContent>
        </Card>
      )}
      {hasMore && !loading && (
        <Button
          variant="secondary"
          disabled={moreLoading}
          onClick={() => void loadMore()}
        >
          {moreLoading ? "加载中…" : "加载更多笔记"}
        </Button>
      )}
    </div>
  );
}
