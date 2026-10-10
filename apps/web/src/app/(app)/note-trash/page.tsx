"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/utils";
import {
  scopeLabel,
  type NoteTrashEntry,
} from "@/components/research-notes/trash-contract";

const limit = 50;
export default function NoteTrashPage() {
  const [state, setState] = useState<"TRASHED" | "RESTORED">("TRASHED");
  const [offset, setOffset] = useState(0);
  const [entries, setEntries] = useState<NoteTrashEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const sequence = useRef(0);
  const load = useCallback(async () => {
    const current = ++sequence.current;
    setLoading(true);
    setError("");
    try {
      const result = await api.get<NoteTrashEntry[]>(
        `/note-trash?state=${state}&limit=${limit}&offset=${offset}`,
      );
      if (sequence.current === current) setEntries(result);
    } catch (cause) {
      if (sequence.current === current)
        setError(
          cause instanceof Error ? cause.message : "无法加载历史删除记录",
        );
    } finally {
      if (sequence.current === current) setLoading(false);
    }
  }, [state, offset]);
  useEffect(() => {
    queueMicrotask(() => void load());
    return () => {
      sequence.current += 1;
    };
  }, [load]);
  return (
    <div className="mx-auto max-w-5xl space-y-5">
      <Link
        href="/inbox"
        className="inline-flex items-center gap-2 text-sm text-[var(--muted)]"
      >
        <ArrowLeft className="h-4 w-4" />
        返回精读笔记
      </Link>
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">历史删除记录</h1>
          <p className="mt-2 text-sm text-[var(--muted)]">
            此处只保留旧版回收和恢复记录，不会自动清空。新删除为永久删除，不可恢复。
          </p>
        </div>
        <Button
          variant="secondary"
          disabled={loading}
          onClick={() => void load()}
        >
          <RefreshCw className="h-4 w-4" />
          刷新
        </Button>
      </header>
      <div className="flex gap-2">
        {(["TRASHED", "RESTORED"] as const).map((value) => (
          <Button
            key={value}
            size="sm"
            variant={state === value ? "default" : "secondary"}
            onClick={() => {
              setState(value);
              setOffset(0);
            }}
          >
            {value === "TRASHED" ? "旧版回收记录" : "历史恢复记录"}
          </Button>
        ))}
      </div>
      {error && <ErrorState message={error} onRetry={() => void load()} />}
      {loading ? (
        <LoadingState label="正在加载历史删除记录…" />
      ) : error ? null : entries.length ? (
        <div className="divide-y divide-[var(--border)] rounded-lg border border-[var(--border)] bg-[var(--surface)]">
          {entries.map((entry) => (
            <Link
              key={entry.id}
              href={`/note-trash/${entry.id}`}
              className="flex items-center justify-between gap-4 px-5 py-4 hover:bg-[var(--surface-hover)]"
            >
              <div className="min-w-0">
                <h2 className="line-clamp-2 font-medium">
                  {entry.paper_title}
                </h2>
                <p className="mt-1 text-xs text-[var(--muted)]">
                  {scopeLabel(entry.scope)} · {entry.members.length} 个版本 ·{" "}
                  {formatDate(
                    entry.state === "RESTORED"
                      ? (entry.restored_at ?? entry.created_at)
                      : entry.created_at,
                  )}
                </p>
              </div>
              <ArrowRight className="h-4 w-4 shrink-0" />
            </Link>
          ))}
        </div>
      ) : (
        <EmptyState
          title={state === "TRASHED" ? "暂无旧版回收记录" : "暂无历史恢复记录"}
          detail="新删除会移除笔记及系统管理的 Markdown 文件，不产生可恢复副本。"
        />
      )}
      {!loading && !error && (
        <div className="flex items-center gap-3 text-sm">
          <Button
            size="sm"
            variant="secondary"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - limit))}
          >
            上一页
          </Button>
          <span>第 {offset / limit + 1} 页</span>
          <Button
            size="sm"
            variant="secondary"
            disabled={entries.length < limit}
            onClick={() => setOffset(offset + limit)}
          >
            下一页
          </Button>
        </div>
      )}
    </div>
  );
}
