"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  getSession,
  type InboxItem,
  type ResearchNote,
  type ReviewAction,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/input";
import { ErrorState, LoadingState } from "@/components/ui/state";
import { feedbackLabel } from "./feedback";

export function NoteReviewPanel({
  note,
  onNote,
}: {
  note: ResearchNote;
  onNote: (note: ResearchNote) => void;
}) {
  const [history, setHistory] = useState<ReviewAction[]>([]);
  const [inbox, setInbox] = useState<InboxItem | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [error, setError] = useState("");
  const [comment, setComment] = useState("");
  const [ownerId, setOwnerId] = useState<string | null>(null);
  const sending = useRef(false);
  const pendingKey = (owner: string) =>
    `researchos:manual-note-review:${owner}:${note.id}:${note.revision}`;
  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [actions, items, owner] = await Promise.all([
        api.get<ReviewAction[]>(`/research-notes/${note.id}/reviews`),
        api.get<InboxItem[]>("/research-inbox"),
        getSession(),
      ]);
      setOwnerId(owner.id);
      setHistory(actions);
      const currentInbox =
        items.find((item) => item.note_id === note.id) ?? null;
      setInbox(currentInbox);
      const key = `researchos:manual-note-review:${owner.id}:${note.id}:${note.revision}`;
      const raw = localStorage.getItem(key);
      if (raw) {
        setUncertain(true);
        const pending = JSON.parse(raw) as {
          action: string;
          sectionKey: string | null;
          comment: string | null;
          priorIds: string[];
          inboxId: string | null;
        };
        const receipt =
          Array.isArray(pending.priorIds) &&
          actions.filter(
            (row) =>
              !pending.priorIds.includes(row.id) &&
              row.action === pending.action &&
              row.section_key === pending.sectionKey &&
              row.comment === pending.comment &&
              row.reviewed_revision === note.revision,
          ).length === 1;
        const inboxReceipt =
          pending.inboxId === currentInbox?.id &&
          ((pending.action === "ACCEPT" &&
            currentInbox.status === "ACCEPTED") ||
            (pending.action === "REJECT_NOTE" &&
              currentInbox.status === "REJECTED" &&
              receipt));
        if (receipt || inboxReceipt) {
          localStorage.removeItem(key);
          setUncertain(false);
        } else setUncertain(true);
      } else setUncertain(false);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "无法读取核实记录");
    } finally {
      setLoading(false);
    }
  }, [note.id, note.revision]);
  useEffect(() => {
    queueMicrotask(() => void load());
  }, [load]);
  async function mutate(path: string, body?: unknown, isInbox = false) {
    if (uncertain || !ownerId || sending.current) return;
    sending.current = true;
    setBusy(true);
    setError("");
    try {
      const request = body as { action?: string; comment?: string } | undefined;
      const sectionKey =
        path.match(/\/sections\/([^/]+)\/review$/)?.[1] ?? null;
      localStorage.setItem(
        pendingKey(ownerId),
        JSON.stringify({
          action:
            isInbox && request?.action === "REJECT"
              ? "REJECT_NOTE"
              : (request?.action ?? "VERIFY_NOTE"),
          sectionKey,
          comment: request?.comment ?? null,
          priorIds: history.map((row) => row.id),
          inboxId: isInbox ? (inbox?.id ?? null) : null,
        }),
      );
      if (isInbox) setInbox(await api.post<InboxItem>(path, body));
      else onNote(await api.post<ResearchNote>(path, body));
      localStorage.removeItem(pendingKey(ownerId));
      // A saved response is authoritative even when refreshing the history fails.
      await load();
    } catch (cause) {
      setUncertain(true);
      setError(cause instanceof Error ? cause.message : "核实提交结果待确认");
    } finally {
      sending.current = false;
      setBusy(false);
    }
  }
  const content = note.sections.filter((section) => section.body_markdown);
  const verified = content.filter(
    (section) => section.review_status === "VERIFIED",
  ).length;
  return (
    <section
      aria-label="高级核实与记录"
      className="space-y-4 rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4 text-sm"
    >
      <div>
        <h2 className="font-semibold">人工核实（可选）</h2>
        <p className="mt-1 text-xs text-[var(--muted)]">
          保存真实人工核对记录，不影响日常阅读。自动检查与人工确认分别保留。
        </p>
      </div>
      {loading && <LoadingState label="正在读取核实记录…" />}
      {error && <ErrorState message={error} onRetry={() => void load()} />}
      {uncertain && (
        <div className="space-y-2">
          <p className="text-xs text-amber-700 dark:text-amber-300">
            提交结果待核查，已暂停本页重复操作。关闭或刷新页面不会重新提交。
          </p>
          <Button
            size="sm"
            variant="secondary"
            disabled={loading || busy}
            onClick={() => void load()}
          >
            只读核查人工记录
          </Button>
        </div>
      )}
      <p>
        已确认 {verified} / {content.length} 个有内容章节 · 原人工状态：
        {note.review_status}
      </p>
      <div className="flex flex-wrap gap-2">
        {content.map((section) => (
          <Button
            key={section.id}
            size="sm"
            variant="secondary"
            disabled={
              loading ||
              !ownerId ||
              busy ||
              uncertain ||
              section.review_status === "VERIFIED"
            }
            onClick={() =>
              void mutate(
                `/research-notes/${note.id}/sections/${section.section_key}/review`,
                { action: "CONFIRM" },
              )
            }
          >
            确认{feedbackLabel(section.section_key)}
          </Button>
        ))}
        <Button
          size="sm"
          variant="secondary"
          disabled={
            busy ||
            uncertain ||
            note.review_status === "VERIFIED" ||
            !content.length ||
            verified !== content.length
          }
          onClick={() => void mutate(`/research-notes/${note.id}/verify`)}
        >
          核实整篇笔记
        </Button>
      </div>
      {!loading && (
        <div className="space-y-2 border-t border-[var(--border)] pt-3">
          <p className="text-xs text-[var(--muted)]">
            Inbox 状态：{inbox?.status ?? "无当前记录"}
          </p>
          {inbox &&
            !["ACCEPTED", "REJECTED", "SUPERSEDED"].includes(inbox.status) && (
              <>
                <Button
                  size="sm"
                  disabled={
                    busy || uncertain || note.review_status !== "VERIFIED"
                  }
                  onClick={() =>
                    void mutate(
                      `/research-inbox/${inbox.id}/decision`,
                      { action: "ACCEPT", comment: null },
                      true,
                    )
                  }
                >
                  接受此版本
                </Button>
                <Textarea
                  aria-label="拒绝笔记原因"
                  value={comment}
                  onChange={(event) => setComment(event.target.value)}
                  placeholder="需要拒绝此版本时填写原因"
                />
                <Button
                  size="sm"
                  variant="danger"
                  disabled={
                    loading || !ownerId || busy || uncertain || !comment.trim()
                  }
                  onClick={() =>
                    void mutate(
                      `/research-inbox/${inbox.id}/decision`,
                      { action: "REJECT", comment: comment.trim() },
                      true,
                    )
                  }
                >
                  拒绝此版本
                </Button>
              </>
            )}
          <Link
            href="/inbox"
            className="inline-block text-xs text-[var(--accent)] hover:underline"
          >
            查看 Research Inbox →
          </Link>
        </div>
      )}
      <details className="border-t border-[var(--border)] pt-3">
        <summary className="cursor-pointer text-xs">
          反馈与核实历史（{history.length}）
        </summary>
        <div className="mt-2 space-y-2 text-xs">
          {history.length ? (
            history.map((action) => (
              <div
                key={action.id}
                className="border-b border-[var(--border)] pb-2"
              >
                <p>
                  {action.action} ·{" "}
                  {action.section_key
                    ? feedbackLabel(action.section_key)
                    : "整篇笔记"}{" "}
                  · v{action.reviewed_revision}
                </p>
                {action.comment && (
                  <p className="mt-1 whitespace-pre-wrap text-[var(--muted)]">
                    {action.comment}
                  </p>
                )}
                <p className="mt-1 text-[var(--muted)]">
                  {new Date(action.reviewed_at).toLocaleString("zh-CN")}
                </p>
              </div>
            ))
          ) : (
            <p className="text-[var(--muted)]">暂无人工核实或反馈记录。</p>
          )}
        </div>
      </details>
    </section>
  );
}
