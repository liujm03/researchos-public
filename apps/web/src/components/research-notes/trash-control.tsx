"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ErrorState, LoadingState } from "@/components/ui/state";
import { api, ApiError, getSession } from "@/lib/api";
import {
  clearPendingDeletion,
  loadPendingDeletion,
  persistDeletion,
  permanentDeletionMessage,
  type GeneratedFileSettings,
  type NoteDeletionPreview,
  type NoteDeletionReceipt,
  type PendingNoteDeletion,
} from "./trash-contract";

export function NoteTrashControl({
  noteId,
  ownerId,
  blocked = false,
  recoveryOnly = false,
  onActiveChange,
}: {
  noteId: string;
  ownerId: string | null;
  blocked?: boolean;
  recoveryOnly?: boolean;
  onActiveChange?: (active: boolean) => void;
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [settings, setSettings] = useState<GeneratedFileSettings | null>(null);
  const [preview, setPreview] = useState<NoteDeletionPreview | null>(null);
  const [pending, setPending] = useState<PendingNoteDeletion | null>(null);
  const [absent, setAbsent] = useState(false);
  const [receipt, setReceipt] = useState<NoteDeletionReceipt | null>(null);
  const saving = useRef(false);
  useEffect(() => {
    onActiveChange?.(open || busy || !!pending);
  }, [open, busy, pending, onActiveChange]);
  useEffect(() => {
    queueMicrotask(() => {
      setPreview(null);
      setReceipt(null);
      setError("");
      setMessage("");
      setAbsent(false);
      const saved = ownerId ? loadPendingDeletion(ownerId, noteId) : null;
      setPending(saved);
      setOpen(!!saved);
    });
  }, [noteId, ownerId]);

  function accept(result: NoteDeletionReceipt, frozen: PendingNoteDeletion) {
    if (
      result.note_id !== noteId ||
      result.idempotency_key !== frozen.key ||
      result.preview_sha256 !== frozen.previewSha256 ||
      result.scope !== "READING_RUN"
    )
      throw new Error("删除记录与当前请求不一致，请保留页面状态并核查。");
    setReceipt(result);
    setAbsent(false);
    if (result.state === "COMPLETED") {
      clearPendingDeletion(frozen);
      setPending(null);
      setMessage("笔记及系统管理的文件已永久删除，不可恢复。");
      router.push("/inbox");
    } else {
      setMessage(
        result.state === "DELETING"
          ? "删除已受理，正在处理。请读取最新状态。"
          : "删除尚未全部完成，请查看原因后继续同一次删除。",
      );
    }
  }
  async function inspect() {
    if (!pending || saving.current) return;
    saving.current = true;
    setBusy(true);
    setError("");
    setAbsent(false);
    try {
      accept(
        await api.get<NoteDeletionReceipt>(
          `/note-deletions/by-operation?idempotency_key=${encodeURIComponent(pending.key)}`,
        ),
        pending,
      );
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 404) {
        setAbsent(true);
        setReceipt(null);
        setMessage("尚未查到这次删除。可用原请求继续，同一请求不会重复删除。");
      } else
        setError(cause instanceof Error ? cause.message : "无法核查删除结果");
    } finally {
      saving.current = false;
      setBusy(false);
    }
  }
  async function prepare() {
    if (pending || saving.current) return;
    setOpen(true);
    saving.current = true;
    setBusy(true);
    setError("");
    setMessage("");
    setPreview(null);
    try {
      const current = await api.get<GeneratedFileSettings>(
        "/settings/generated-files",
      );
      setSettings(current);
      if (current.enabled)
        setPreview(
          await api.post<NoteDeletionPreview>(
            `/research-notes/${noteId}/deletion-preview`,
            {},
          ),
        );
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "无法预览永久删除范围");
    } finally {
      saving.current = false;
      setBusy(false);
    }
  }
  async function submit(resume = false) {
    if (
      saving.current ||
      blocked ||
      (!resume && (!preview?.can_delete || pending))
    )
      return;
    saving.current = true;
    setBusy(true);
    setError("");
    setMessage("");
    let frozen: PendingNoteDeletion | null = null;
    try {
      const owner = await getSession();
      if (owner.id !== ownerId)
        throw new Error("账户状态已改变，请刷新后操作。");
      if (resume) {
        if (!pending || !absent) return;
        frozen = pending;
      } else {
        if (!preview?.can_delete) return;
        frozen = {
          ownerId: owner.id,
          noteId,
          key: crypto.randomUUID(),
          previewSha256: preview.preview_sha256,
        };
        persistDeletion(frozen);
        setPending(frozen);
      }
      setAbsent(false);
      accept(
        await api.post<NoteDeletionReceipt>(
          `/research-notes/${noteId}/delete-permanently`,
          {
            expected_preview_sha256: frozen.previewSha256,
            idempotency_key: frozen.key,
            confirm: true,
          },
        ),
        frozen,
      );
    } catch (cause) {
      if (
        frozen &&
        cause instanceof ApiError &&
        ([400, 401, 403, 404, 422].includes(cause.status) ||
          (cause.status === 409 &&
            [
              "NOTE_DELETION_PREVIEW_CHANGED",
              "NOTE_DELETION_DISABLED",
              "NOTE_DELETION_BLOCKED",
              "NOTE_READING_ACTIVE",
              "NOTE_PUBLICATION_ACTIVE",
              "NOTE_DELETION_SCOPE_RETIRED",
            ].includes(cause.code)))
      ) {
        clearPendingDeletion(frozen);
        setPending(null);
        setPreview(null);
        setAbsent(false);
      }
      setError(cause instanceof Error ? cause.message : "删除结果待核查");
    } finally {
      saving.current = false;
      setBusy(false);
    }
  }
  async function retryAdmitted() {
    if (
      !pending ||
      !receipt ||
      !["FAILED", "NEEDS_ATTENTION"].includes(receipt.state) ||
      saving.current ||
      blocked
    )
      return;
    saving.current = true;
    setBusy(true);
    setError("");
    try {
      const owner = await getSession();
      if (owner.id !== pending.ownerId)
        throw new Error("账户状态已改变，请刷新后操作。");
      accept(
        await api.post<NoteDeletionReceipt>(
          `/note-deletions/${receipt.id}/retry`,
          { confirm: true },
        ),
        pending,
      );
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "继续删除结果待核查，请先读取状态",
      );
    } finally {
      saving.current = false;
      setBusy(false);
    }
  }
  if (recoveryOnly && !pending && !receipt) return null;
  return (
    <div className="w-full sm:w-auto">
      <Button
        size="sm"
        variant="ghost"
        disabled={!ownerId || busy || blocked}
        aria-expanded={open}
        onClick={() =>
          open ? setOpen(false) : pending ? setOpen(true) : void prepare()
        }
      >
        <Trash2 className="h-3.5 w-3.5" />
        永久删除
      </Button>
      {open && (
        <section
          aria-label="永久删除精读笔记"
          className="absolute inset-x-4 z-20 mx-auto mt-2 max-h-[75vh] max-w-xl space-y-3 overflow-y-auto rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4 shadow-lg sm:inset-x-8"
        >
          <div className="flex items-center justify-between gap-3">
            <h2 className="font-semibold">永久删除 · 不可恢复</h2>
            <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
              关闭
            </Button>
          </div>
          <p className="text-sm leading-6 text-[var(--muted)]">
            {permanentDeletionMessage}
          </p>
          {error && <ErrorState message={error} />}
          {message && (
            <p role="status" className="text-sm">
              {message}
            </p>
          )}
          {busy && <LoadingState label="正在核对删除状态…" />}
          {pending ? (
            <div className="space-y-3">
              <p className="text-sm text-amber-800 dark:text-amber-300">
                {receipt
                  ? "本次删除已登记。系统不会自动发起另一笔删除。"
                  : "删除结果须核查。系统不会自动再次提交。"}
              </p>
              {receipt && (
                <p className="text-sm">
                  已处理文件 {receipt.files_deleted_count}/{receipt.files_total}
                  {receipt.error_message ? ` · ${receipt.error_message}` : ""}
                </p>
              )}
              <Button
                size="sm"
                variant="secondary"
                disabled={busy}
                onClick={() => void inspect()}
              >
                核查删除结果
              </Button>
              {absent && (
                <Button
                  size="sm"
                  variant="danger"
                  disabled={busy || blocked}
                  onClick={() => void submit(true)}
                >
                  继续原永久删除请求
                </Button>
              )}
              {receipt &&
                ["FAILED", "NEEDS_ATTENTION"].includes(receipt.state) && (
                  <Button
                    size="sm"
                    variant="danger"
                    disabled={busy || blocked}
                    onClick={() => void retryAdmitted()}
                  >
                    继续本次已批准的删除
                  </Button>
                )}
            </div>
          ) : settings?.enabled === false ? (
            <p className="text-sm">
              删除入口已关闭。
              <Link href="/settings" className="text-[var(--accent)]">
                到设置开启
              </Link>
            </p>
          ) : (
            <>
              {preview && (
                <div className="space-y-3 text-sm">
                  <p className="font-medium">{preview.paper_title}</p>
                  <p>
                    本次精读的全部笔记版本 · {preview.members.length} 个版本 ·{" "}
                    {preview.files.length} 个文件
                  </p>
                  <ul
                    aria-label="受影响笔记版本"
                    className="flex flex-wrap gap-2"
                  >
                    {preview.members.map((member) => (
                      <li
                        key={member.note_id}
                        className="rounded border border-[var(--border)] px-2 py-1"
                      >
                        v{member.revision} ·{" "}
                        {member.created_by === "AI" ? "AI 原文" : "修订版"}
                      </li>
                    ))}
                  </ul>
                  {preview.blockers.length > 0 && (
                    <div className="space-y-2 rounded border border-amber-500/30 p-3">
                      <p className="font-medium">暂不能删除，请先处理：</p>
                      {preview.blockers.map((item, index) => (
                        <p key={`${item.code}-${index}`}>
                          {item.message}
                          {item.href && (
                            <Link
                              href={item.href}
                              className="ml-2 text-[var(--accent)]"
                            >
                              查看关联资料 →
                            </Link>
                          )}
                        </p>
                      ))}
                    </div>
                  )}
                  <details className="rounded border border-[var(--border)] p-3">
                    <summary className="cursor-pointer text-xs">
                      将永久删除的文件
                    </summary>
                    <div className="mt-2 space-y-2 text-xs text-[var(--muted)]">
                      {preview.files.length ? (
                        preview.files.map((file, index) => (
                          <p
                            key={`${file.kind}-${index}`}
                            className="break-all font-mono"
                          >
                            {file.path} ·{" "}
                            {file.exists
                              ? `${file.size_bytes} 字节`
                              : "文件已不存在"}
                          </p>
                        ))
                      ) : (
                        <p>未登记系统管理的文件。</p>
                      )}
                    </div>
                  </details>
                  <div className="flex flex-wrap gap-2">
                    <Button
                      size="sm"
                      variant="danger"
                      disabled={busy || blocked || !preview.can_delete}
                      onClick={() => void submit()}
                    >
                      确认永久删除
                    </Button>
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => setOpen(false)}
                    >
                      取消
                    </Button>
                  </div>
                </div>
              )}
              {!busy && !preview && (
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => void prepare()}
                >
                  重新预览
                </Button>
              )}
            </>
          )}
        </section>
      )}
    </div>
  );
}
