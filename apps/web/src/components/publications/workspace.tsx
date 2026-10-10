"use client";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, type Project } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { PublicationEditor } from "./editor";
import { PublicationDetail } from "./detail";
import { PublicationWriting } from "./writing/workspace";
import { PublicationBuilds } from "./builds/workspace";
import { requestHash } from "./request-hash";
import { usePublicationPending, type PublicationPending } from "./use-pending";
import {
  message,
  type Publication,
  type PublicationPage,
  type Revision,
} from "./types";
export function PublicationsWorkspace({
  projectId,
  initialId,
}: {
  projectId: string;
  initialId?: string;
}) {
  const endpoint = `/projects/${projectId}/publications`,
    recovery = usePublicationPending(projectId);
  const [project, setProject] = useState<Project | null>(null),
    [page, setPage] = useState<PublicationPage | null>(null),
    [detail, setDetail] = useState<Publication | null>(null),
    [base, setBase] = useState<Revision | null>(null),
    [editing, setEditing] = useState(false),
    [editorKey, setEditorKey] = useState(0),
    [loading, setLoading] = useState(true),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [canAbandon, setCanAbandon] = useState(false),
    [abandonAck, setAbandonAck] = useState(false);
  const [writingLocked, setWritingLocked] = useState(false);
  const [buildLocked, setBuildLocked] = useState(false);
  const operating = useRef(false),
    listSeq = useRef(0),
    openSeq = useRef(0);
  const load = useCallback(
    async (cursor?: string | null) => {
      const sequence = ++listSeq.current;
      try {
        const value = await api.get<PublicationPage>(
          `${endpoint}?limit=20${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
        );
        if (sequence === listSeq.current) setPage(value);
      } catch (cause) {
        if (sequence === listSeq.current) setError(message(cause));
      } finally {
        if (sequence === listSeq.current) setLoading(false);
      }
    },
    [endpoint],
  );
  const open = useCallback(
    async (id: string) => {
      const sequence = ++openSeq.current;
      setBusy(true);
      setError("");
      try {
        const value = await api.get<Publication>(`${endpoint}/${id}`);
        if (value.project_id !== projectId)
          throw new Error("论文不属于当前课题。");
        if (sequence === openSeq.current) {
          setDetail(value);
          setEditing(false);
        }
      } catch (cause) {
        if (sequence === openSeq.current) setError(message(cause));
      } finally {
        if (sequence === openSeq.current) setBusy(false);
      }
    },
    [endpoint, projectId],
  );
  useEffect(() => {
    void Promise.resolve().then(() => load());
    void api
      .get<Project>(`/projects/${projectId}`)
      .then(setProject)
      .catch((cause) => setError(message(cause)));
  }, [load, projectId]);
  const initialOpened = useRef(false);
  useEffect(() => {
    if (initialId && !initialOpened.current) {
      initialOpened.current = true;
      void Promise.resolve().then(() => open(initialId));
    }
  }, [initialId, open]);
  async function action(fn: () => Promise<void>) {
    if (operating.current) return;
    operating.current = true;
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (cause) {
      setError(message(cause));
      if (
        cause instanceof ApiError &&
        cause.details &&
        typeof cause.details === "object" &&
        "committed" in cause.details &&
        cause.details.committed === false
      )
        recovery.clear();
    } finally {
      operating.current = false;
      setBusy(false);
    }
  }
  async function transmit(record: PublicationPending) {
    if (record.path.endsWith("/reviews")) {
      await api.post(record.path, record.body);
      recovery.clear();
      setNotice("本人审阅已保存；正在只读刷新版本。");
      try {
        return await api.get<Publication>(record.path.slice(0, -8));
      } catch (cause) {
        setError(
          `审阅已保存，详情刷新失败：${message(cause)}。请只读重新打开论文。`,
        );
        return null;
      }
    }
    return api.post<Publication>(record.path, record.body);
  }
  async function send(
    path: string,
    body: Record<string, unknown>,
    label: string,
  ) {
    await action(async () => {
      setCanAbandon(false);
      setAbandonAck(false);
      const frozen = recovery.freeze(path, body, label);
      const value = await transmit(frozen);
      if (value && value.project_id !== projectId)
        throw new Error("保存回执不属于当前课题。");
      recovery.clear();
      if (value) {
        setDetail(value);
        setEditing(false);
      }
      setNotice(`${label}已保存。`);
      await load();
    });
  }
  async function lookup() {
    if (!recovery.pending) return;
    await action(async () => {
      const pending = recovery.pending!;
      const parent =
          pending.path === endpoint
            ? endpoint
            : pending.path.replace(/\/(reviews|revisions)$/, ""),
        path =
          parent === endpoint
            ? `${endpoint}/lookup`
            : `${parent}/operations/lookup`;
      try {
        const value = await api.get<Publication>(
          `${path}?key=${encodeURIComponent(pending.body.idempotency_key)}${parent === endpoint ? "" : `&kind=${pending.path.endsWith("/reviews") ? "review" : "revision"}`}`,
        );
        if (value.project_id !== projectId)
          throw new Error("核查回执不属于当前课题。");
        const kind =
          parent === endpoint
            ? "create"
            : pending.path.endsWith("/reviews")
              ? "review"
              : "revision";
        if (
          !value.operation_receipt ||
          value.operation_receipt.kind !== kind ||
          value.operation_receipt.idempotency_key !==
            pending.body.idempotency_key ||
          value.operation_receipt.request_sha256 !==
            (await requestHash(pending.body))
        )
          throw new Error(
            "原请求回执的类型、幂等键或输入 SHA 不一致；保留冻结请求，请核查原版本。",
          );
        setDetail(value);
        setEditing(false);
        recovery.clear();
        setNotice("原请求已保存，核查没有重复执行。");
        await load();
      } catch (cause) {
        if (cause instanceof ApiError && cause.status === 404) {
          setCanAbandon(true);
          setNotice("未找到原请求；可以继续原内容与原键，未自动重发。");
        } else throw cause;
      }
    });
  }
  async function resume() {
    if (!recovery.pending) return;
    await action(async () => {
      const value = await transmit(recovery.pending!);
      if (value && value.project_id !== projectId)
        throw new Error("原回执不属于当前课题。");
      recovery.clear();
      if (value) {
        setDetail(value);
        setEditing(false);
      }
      setNotice("原请求已确认保存。");
      await load();
    });
  }
  if (loading && !page) return <LoadingState label="正在读取论文工作区…" />;
  const disabled = busy || !!recovery.pending || !recovery.ready;
  return (
    <div className="space-y-5">
      <Link
        href={`/projects/${projectId}`}
        className="text-sm text-[var(--muted)]"
      >
        ← 返回课题
      </Link>
      <div className="flex flex-wrap justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">论文工作区</h1>
          <p className="mt-1 text-sm text-[var(--muted)]">
            {project?.name} · 证据进入骨架、章节与本人审阅，保留每个原文版本。
          </p>
        </div>
        <Button
          disabled={disabled || writingLocked || buildLocked}
          onClick={() => {
            setBase(null);
            setEditing(true);
            setEditorKey((k) => k + 1);
          }}
        >
          新建论文
        </Button>
      </div>
      {error && (
        <ErrorState
          message={error}
          onRetry={() => {
            setError("");
            void load();
          }}
        />
      )}
      {notice && (
        <p role="status" className="text-sm">
          {notice}
        </p>
      )}
      {recovery.warning && <p role="alert">{recovery.warning}</p>}
      {recovery.pending && (
        <Card>
          <CardContent className="space-y-2">
            <p>待核查原请求：{recovery.pending.label}</p>
            <p className="text-xs">
              内容与幂等键已冻结；刷新不会自动重发。先只读核查，再决定是否继续。
            </p>
            <details>
              <summary>查看冻结输入</summary>
              <pre className="max-h-52 overflow-auto whitespace-pre-wrap break-all text-xs">
                {JSON.stringify(recovery.pending.body, null, 2)}
              </pre>
            </details>
            <div className="flex gap-2">
              <Button
                disabled={busy}
                variant="secondary"
                onClick={() => void lookup()}
              >
                只读核查原请求
              </Button>
              <Button disabled={busy} onClick={() => void resume()}>
                继续原请求
              </Button>
            </div>
            {canAbandon && (
              <>
                <label className="flex gap-2 text-xs">
                  <input
                    type="checkbox"
                    disabled={busy}
                    checked={abandonAck}
                    onChange={(e) => setAbandonAck(e.target.checked)}
                  />
                  核查未发现原请求；我已检查论文列表与历史，放弃冻结请求后修正输入
                </label>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={busy || !abandonAck}
                  onClick={() => {
                    recovery.clear();
                    setCanAbandon(false);
                    setAbandonAck(false);
                  }}
                >
                  放弃原请求并修正
                </Button>
              </>
            )}
          </CardContent>
        </Card>
      )}
      {editing && (
        <Card>
          <CardContent>
            <PublicationEditor
              key={editorKey}
              projectId={projectId}
              base={base}
              busy={disabled}
              onCancel={() => setEditing(false)}
              onSave={async (value, preview, ack) => {
                await send(
                  base
                    ? `${endpoint}/${base.publication_id}/revisions`
                    : endpoint,
                  {
                    ...value,
                    expected_preview_sha256: preview.preview_sha256,
                    acknowledge_gaps: ack,
                    ...(base ? { expected_revision_sha256: base.sha256 } : {}),
                  },
                  base ? "论文修订" : "论文工作区",
                );
              }}
            />
          </CardContent>
        </Card>
      )}
      <div className="grid gap-4 xl:grid-cols-[minmax(200px,1fr)_minmax(0,3fr)]">
        <Card>
          <CardContent className="space-y-2">
            <h2 className="font-medium">本课题论文</h2>
            <Button
              size="sm"
              variant="ghost"
              disabled={busy}
              onClick={() => void load()}
            >
              刷新论文列表
            </Button>
            {page && !page.items.length && (
              <EmptyState
                title="尚无论文工作区"
                detail="先整理骨架；已有证据包可以固定关联到章节。"
              />
            )}
            {page?.items.map((row) => (
              <button
                key={row.id}
                disabled={busy || editing || writingLocked || buildLocked}
                onClick={() => void open(row.id)}
                className={`block w-full rounded border p-3 text-left text-sm ${detail?.id === row.id ? "border-[var(--accent)]" : ""}`}
              >
                {row.title}
                <small className="block text-[var(--muted)]">
                  版本 {row.revision}
                </small>
              </button>
            ))}
            {page?.page.next_cursor && (
              <Button
                size="sm"
                disabled={busy}
                onClick={() => void load(page.page.next_cursor)}
              >
                下一页论文
              </Button>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardContent>
            {detail ? (
              <PublicationDetail
                key={`${detail.id}:${detail.current.sha256}:${detail.current.reviews.length}`}
                publication={detail}
                busy={disabled || editing || writingLocked || buildLocked}
                onEdit={() => {
                  setBase(detail.current);
                  setEditorKey((k) => k + 1);
                  setEditing(true);
                }}
                onReview={async (row, decision, conclusion, ack) =>
                  send(
                    `${endpoint}/${detail.id}/reviews`,
                    {
                      revision_id: row.id,
                      expected_revision_sha256: row.sha256,
                      decision,
                      conclusion,
                      acknowledge_gaps: ack,
                    },
                    "论文审阅",
                  )
                }
              />
            ) : (
              <EmptyState title="选择论文查看正文与来源" />
            )}
          </CardContent>
        </Card>
      </div>
      {detail && (
        <Card>
          <CardContent>
            <PublicationWriting
              key={detail.id}
              publication={detail}
              disabled={disabled || editing || buildLocked}
              onLock={setWritingLocked}
              onAdopt={async () => {
                await open(detail.id);
                await load();
              }}
            />
          </CardContent>
        </Card>
      )}
      {detail && (
        <Card>
          <CardContent>
            <PublicationBuilds
              key={detail.id}
              publication={detail}
              disabled={disabled || editing || writingLocked}
              onLock={setBuildLocked}
            />
          </CardContent>
        </Card>
      )}
    </div>
  );
}
