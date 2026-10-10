"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { ArrowLeft } from "lucide-react";
import { ErrorState, LoadingState } from "@/components/ui/state";
import { api, getSession } from "@/lib/api";
import { NoteTrashControl } from "@/components/research-notes/trash-control";
import { NoteTrashDetails } from "@/components/research-notes/trash-details";
import type { NoteTrashEntry } from "@/components/research-notes/trash-contract";

export default function HistoricalNoteDeletionPage() {
  const { id } = useParams<{ id: string }>();
  const [entry, setEntry] = useState<NoteTrashEntry | null>(null);
  const [ownerId, setOwnerId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [result, owner] = await Promise.all([
        api.get<NoteTrashEntry>(`/note-trash/${id}`),
        getSession(),
      ]);
      setEntry(result);
      setOwnerId(owner.id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "无法加载历史删除记录");
    } finally {
      setLoading(false);
    }
  }, [id]);
  useEffect(() => {
    queueMicrotask(() => void load());
  }, [load]);
  if (loading) return <LoadingState label="正在加载历史删除记录…" />;
  if (!entry)
    return (
      <ErrorState message={error || "记录不可用"} onRetry={() => void load()} />
    );
  return (
    <div className="relative mx-auto max-w-4xl space-y-5">
      <Link
        href="/note-trash"
        className="inline-flex items-center gap-2 text-sm text-[var(--muted)]"
      >
        <ArrowLeft className="h-4 w-4" />
        返回历史删除记录
      </Link>
      <header>
        <p className="mb-1 text-xs text-[var(--accent)]">
          {entry.state === "TRASHED"
            ? "旧版回收记录 · 尚未永久删除"
            : "历史恢复记录"}
        </p>
        <h1 className="text-xl font-semibold">{entry.paper_title}</h1>
      </header>
      {error && <ErrorState message={error} onRetry={() => void load()} />}
      <section className="space-y-4 rounded-lg border border-[var(--border)] bg-[var(--surface)] p-5">
        <p className="text-sm text-[var(--muted)]">
          旧记录不会自动清空。若不再需要，可以核对范围后永久删除；此操作不可恢复。
        </p>
        <NoteTrashDetails value={entry} />
        <NoteTrashControl noteId={entry.note_id} ownerId={ownerId} />
        {entry.state === "RESTORED" && (
          <Link
            href={`/research-notes/${entry.note_id}`}
            className="block text-sm text-[var(--accent)]"
          >
            打开精读笔记 →
          </Link>
        )}
      </section>
    </div>
  );
}
