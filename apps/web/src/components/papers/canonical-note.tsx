"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { ErrorState, LoadingState } from "@/components/ui/state";
import { api, ApiError, type CanonicalNote } from "@/lib/api";

const saveLabels: Record<string, string> = {
  PENDING: "等待文件保存",
  SAVING: "正在保存 Markdown",
  SAVED: "Markdown 已保存",
  CONFLICT: "文件冲突，等待核对",
  FAILED: "文件保存失败",
};

export function CanonicalNotePanel({
  jobId,
  researchNoteId,
  attentionOnly = false,
}: {
  jobId: string;
  researchNoteId?: string;
  attentionOnly?: boolean;
}) {
  const [note, setNote] = useState<CanonicalNote | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [observedAt, setObservedAt] = useState(0);
  const inFlight = useRef(false);
  const load = useCallback(
    async (quiet = false) => {
      if (inFlight.current) return;
      inFlight.current = true;
      if (!quiet) setLoading(true);
      setError("");
      try {
        setNote(
          await api.get<CanonicalNote>(
            `/analysis-jobs/${encodeURIComponent(jobId)}/canonical-note`,
          ),
        );
        setObservedAt(Date.now());
      } catch (cause) {
        if (cause instanceof ApiError && cause.status === 404) setNote(null);
        else
          setError(
            cause instanceof Error
              ? cause.message
              : "无法读取最终 Markdown 笔记",
          );
      } finally {
        inFlight.current = false;
        setLoading(false);
      }
    },
    [jobId],
  );
  useEffect(() => {
    queueMicrotask(() => void load());
  }, [load]);
  const leaseActive =
    !!note?.export_lease_expires_at &&
    new Date(note.export_lease_expires_at).getTime() > observedAt;
  const scheduled = !!note?.export_next_retry_at;
  const automatic =
    !!note &&
    ((["PENDING", "SAVING"].includes(note.export_status) &&
      (leaseActive || note.export_auto_retry_enabled)) ||
      (note.export_status === "FAILED" &&
        note.export_auto_retry_enabled &&
        note.export_retryable &&
        (scheduled || leaseActive)));
  const manualSaveAllowed =
    !!note?.export_manual_retry_allowed &&
    ["PENDING", "FAILED"].includes(note.export_status) &&
    !automatic &&
    !leaseActive;
  const pendingManual = manualSaveAllowed && note?.export_status === "PENDING";
  useEffect(() => {
    if (!automatic || error || saving) return;
    const timer = setTimeout(() => void load(true), 3000);
    return () => clearTimeout(timer);
  }, [automatic, error, saving, note, load]);
  async function save() {
    if (!manualSaveAllowed || saving) return;
    setSaving(true);
    setError("");
    try {
      setNote(
        await api.post<CanonicalNote>(
          `/analysis-jobs/${encodeURIComponent(jobId)}/canonical-note/save`,
        ),
      );
      setObservedAt(Date.now());
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Markdown 文件保存失败",
      );
    } finally {
      setSaving(false);
    }
  }
  function download() {
    if (!note) return;
    const blob = new Blob([note.markdown], {
      type: "text/markdown;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download =
      note.output_path.split(/[\\/]/).pop() || "analytical-note.md";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  if (
    attentionOnly &&
    !error &&
    (loading || !note || note.export_status === "SAVED")
  )
    return null;
  return (
    <section
      className="space-y-3 rounded border border-[var(--border)] p-3"
      aria-label="最终模板 Markdown 笔记"
    >
      <h4 className="text-sm font-medium">最终模板 Markdown 笔记</h4>
      {researchNoteId && (
        <Link
          href={`/research-notes/${encodeURIComponent(researchNoteId)}`}
          className="inline-flex text-sm font-medium text-[var(--accent)] hover:underline"
        >
          打开精读笔记 →
        </Link>
      )}
      {attentionOnly && (
        <p className="break-all text-xs text-[var(--muted)]">
          本篇 Skill 精读任务：{jobId} · 文件仍需处理
        </p>
      )}
      {loading ? (
        <LoadingState label="正在读取最终笔记与保存回执…" />
      ) : note ? (
        <>
          <p role="status" className="text-xs">
            {saveLabels[note.export_status] ?? note.export_status} ·
            内容待人工审阅
          </p>
          <p className="break-all font-mono text-xs">{note.output_path}</p>
          <details>
            <summary className="cursor-pointer text-xs text-[var(--accent)]">
              文件保存记录
            </summary>
            <div className="mt-2 space-y-2">
              <p className="break-all font-mono text-[10px] text-[var(--muted)]">
                Markdown SHA-256：{note.sha256}
              </p>
              {note.exported_at && (
                <p className="text-xs text-[var(--muted)]">
                  保存时间：{new Date(note.exported_at).toLocaleString("zh-CN")}
                </p>
              )}
              {note.export_attempt_count > 0 && (
                <p className="text-xs text-[var(--muted)]">
                  文件保存尝试：{note.export_attempt_count} 次（不调用 AI）
                </p>
              )}
            </div>
          </details>
          {automatic && (
            <p className="text-xs leading-5 text-[var(--muted)]">
              {leaseActive
                ? "文件保存执行中，正在更新回执。"
                : note.export_status === "SAVING"
                  ? "文件保存租约已到期，系统将恢复文件发布并更新回执。"
                  : note.export_status === "PENDING"
                    ? "系统将自动保存文件，正在等待文件发布任务。"
                    : `系统将自动重试文件保存${note.export_next_retry_at ? "，下次检查：" + new Date(note.export_next_retry_at).toLocaleString("zh-CN") : ""}。`}
              已完成的精读内容保留；保存成功前不会标记为已保存。
            </p>
          )}
          {pendingManual && (
            <p className="text-xs text-[var(--muted)]">
              自动文件发布未启用，可保存已生成的完整笔记；此操作不调用 AI。
            </p>
          )}
          {note.export_status === "FAILED" && !note.export_retryable && (
            <p className="text-xs leading-5 text-amber-700 dark:text-amber-300">
              此错误不能自动重试，请核对保存配置或目标文件。完整笔记仍可查看和导出。
            </p>
          )}
          {note.export_status === "CONFLICT" && (
            <p className="text-xs leading-5 text-amber-700 dark:text-amber-300">
              目标文件与批准时的状态不同，或不属于平台管理的文件。请核对现有笔记；系统保留已完成精读内容，不会覆盖人工修改。
            </p>
          )}
          {note.export_error && (
            <p role="alert" className="text-xs text-[var(--danger)]">
              {note.export_error}
            </p>
          )}
          {!researchNoteId && (
            <p className="text-xs text-[var(--muted)]">
              笔记详情暂不可用，请刷新页面；已保存的 Markdown 仍可导出。
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="secondary" onClick={download}>
              导出本版 Markdown
            </Button>
            {manualSaveAllowed && (
              <Button
                size="sm"
                variant="secondary"
                disabled={saving || loading}
                onClick={() => void save()}
              >
                {saving
                  ? "保存中…"
                  : pendingManual
                    ? "保存文件（不调用 AI）"
                    : "重试文件保存（不调用 AI）"}
              </Button>
            )}
            <Button
              size="sm"
              variant="ghost"
              disabled={saving || loading}
              onClick={() => void load()}
            >
              刷新保存回执
            </Button>
          </div>
        </>
      ) : (
        <p className="text-xs text-[var(--muted)]">
          尚无最终模板笔记；原始页阅读回执不等同于完整精读结果。
        </p>
      )}
      {error && <ErrorState message={error} onRetry={() => void load()} />}
    </section>
  );
}
