"use client";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, type Project, type ProjectQuestion } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardContent } from "@/components/ui/card";
import { LoadingState, ErrorState, EmptyState } from "@/components/ui/state";
import { ClaimEditor } from "./editor";
import { ClaimDetail } from "./detail";
import { EvidenceBundles } from "./bundles";
import { useClaimPending, type ClaimPending } from "./use-pending";
import {
  message,
  type Claim,
  type ClaimPage,
  type Revision,
  type Evidence,
  type Fields,
} from "./types";
export function ClaimsWorkspace({
  projectId,
  initialClaimId,
}: {
  projectId: string;
  initialClaimId?: string;
}) {
  const recovery = useClaimPending(projectId);
  const [project, setProject] = useState<Project | null>(null),
    [questions, setQuestions] = useState<ProjectQuestion[]>([]),
    [page, setPage] = useState<ClaimPage | null>(null),
    [detail, setDetail] = useState<Claim | null>(null),
    [base, setBase] = useState<Revision | null>(null);
  const [loading, setLoading] = useState(true),
    [listBusy, setListBusy] = useState(false),
    [detailBusy, setDetailBusy] = useState(false),
    [busy, setBusy] = useState(false),
    [editing, setEditing] = useState(false),
    [editorKey, setEditorKey] = useState(0),
    [error, setError] = useState(""),
    [detailError, setDetailError] = useState(""),
    [saveError, setSaveError] = useState(""),
    [notice, setNotice] = useState("");
  const listSeq = useRef(0),
    detailSeq = useRef(0),
    writing = useRef(false);
  const [canAbandon, setCanAbandon] = useState(false),
    [abandonAck, setAbandonAck] = useState(false);
  const load = useCallback(
    async (cursor?: string | null) => {
      const at = ++listSeq.current;
      setListBusy(true);
      setError("");
      try {
        const value = await api.get<ClaimPage>(
          `/claims?project_id=${projectId}&limit=20${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
        );
        if (at === listSeq.current) setPage(value);
      } catch (cause) {
        if (at === listSeq.current) setError(message(cause));
      } finally {
        if (at === listSeq.current) {
          setListBusy(false);
          setLoading(false);
        }
      }
    },
    [projectId],
  );
  useEffect(() => {
    void Promise.resolve().then(() => load());
    void Promise.all([
      api.get<Project>(`/projects/${projectId}`),
      api.get<ProjectQuestion[]>(`/projects/${projectId}/questions`),
    ])
      .then(([p, q]) => {
        setProject(p);
        setQuestions(q);
      })
      .catch((cause) => setError(message(cause)));
  }, [load, projectId]);
  const open = useCallback(
    async (id: string) => {
      const at = ++detailSeq.current;
      setDetailBusy(true);
      setDetailError("");
      try {
        const value = await api.get<Claim>(`/claims/${id}`);
        if (value.project_id !== projectId)
          throw new Error("此主张不属于当前课题，请从对应课题打开。");
        if (at === detailSeq.current) {
          setDetail(value);
          setEditing(false);
        }
      } catch (cause) {
        if (at === detailSeq.current) setDetailError(message(cause));
      } finally {
        if (at === detailSeq.current) setDetailBusy(false);
      }
    },
    [projectId],
  );
  const initialOpened = useRef(false);
  useEffect(() => {
    if (initialClaimId && !initialOpened.current) {
      initialOpened.current = true;
      void Promise.resolve().then(() => open(initialClaimId));
    }
  }, [initialClaimId, open]);
  async function transmit(record: ClaimPending) {
    if (record.path.endsWith("/reviews")) {
      await api.post(record.path, record.body);
      recovery.clear();
      setNotice("本人审阅已保存；正在只读刷新详情。");
      try {
        return await api.get<Claim>(`/claims/${record.path.split("/")[2]}`);
      } catch (cause) {
        setDetailError(
          `本人审阅已保存，但详情刷新失败：${message(cause)}。请重新打开主张核查历史。`,
        );
        return null;
      }
    }
    return record.method === "PATCH"
      ? api.patch<Claim>(record.path, record.body)
      : api.post<Claim>(record.path, record.body);
  }
  async function send(
    path: string,
    body: Record<string, unknown>,
    label: string,
    method: "POST" | "PATCH" = "POST",
  ) {
    if (writing.current) return;
    writing.current = true;
    setBusy(true);
    setSaveError("");
    setNotice("");
    setCanAbandon(false);
    setAbandonAck(false);
    let stored: Claim | null = null;
    try {
      const request = recovery.freeze(path, body, label, method);
      stored = await transmit(request);
      recovery.clear();
      if (stored) {
        setDetail(stored);
        setEditing(false);
      }
      setNotice(`${label}已保存；未启动AI或科研运行。`);
    } catch (cause) {
      if (
        cause instanceof ApiError &&
        cause.details &&
        typeof cause.details === "object" &&
        "committed" in cause.details &&
        cause.details.committed === false
      )
        recovery.clear();
      setSaveError(`${message(cause)}；输入保持，请只读核查或继续原请求。`);
    } finally {
      writing.current = false;
      setBusy(false);
    }
    if (stored) await load();
  }
  async function lookup() {
    if (!recovery.pending || writing.current) return;
    writing.current = true;
    setBusy(true);
    setSaveError("");
    try {
      const record = recovery.pending;
      const path =
        record.path === "/claims"
          ? `/claims/lookup?key=${encodeURIComponent(record.body.idempotency_key)}`
          : `/claims/${record.path.split("/")[2]}/operations/lookup?key=${encodeURIComponent(record.body.idempotency_key)}`;
      const value = await api.get<Claim>(path);
      if (value.project_id !== projectId)
        throw new Error("核查结果不属于当前课题，未显示或继续操作。");
      recovery.clear();
      if (value) {
        setDetail(value);
        setEditing(false);
      }
      setNotice("已核查原请求保存成功，没有重复执行。");
      await load();
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 404) {
        setCanAbandon(true);
        setNotice("核查时未找到原请求，可继续原内容与原幂等键；未自动重发。");
      } else setSaveError(`核查失败：${message(cause)}；未重发请求。`);
    } finally {
      writing.current = false;
      setBusy(false);
    }
  }
  async function resume() {
    if (!recovery.pending || writing.current) return;
    writing.current = true;
    setBusy(true);
    setSaveError("");
    try {
      const value = await transmit(recovery.pending);
      if (value && value.project_id !== projectId)
        throw new Error("原请求回执不属于当前课题，请检查原输入。");
      recovery.clear();
      if (value) {
        setDetail(value);
        setEditing(false);
      }
      setNotice("原请求已确认保存。");
      await load();
    } catch (cause) {
      setSaveError(`${message(cause)}；原请求保持，未更换幂等键。`);
      if (
        cause instanceof ApiError &&
        cause.details &&
        typeof cause.details === "object" &&
        "committed" in cause.details &&
        cause.details.committed === false
      )
        recovery.clear();
    } finally {
      writing.current = false;
      setBusy(false);
    }
  }
  function newClaim() {
    setBase(null);
    setEditorKey((k) => k + 1);
    setEditing(true);
    setSaveError("");
  }
  async function review(
    rev: Revision,
    decision: string,
    conclusion: string,
    ack: boolean,
  ) {
    if (!detail) return;
    await send(
      `/claims/${detail.id}/reviews`,
      {
        revision_id: rev.id,
        expected_revision_sha256: rev.sha256,
        expected_evidence_sha256: rev.evidence_sha256,
        decision,
        conclusion,
        acknowledge_gaps: ack,
      },
      "本人审阅",
    );
  }
  if (loading && !page) return <LoadingState label="正在读取科研主张…" />;
  return (
    <div className="space-y-5">
      <Link
        className="text-sm text-[var(--muted)]"
        href={`/projects/${projectId}`}
      >
        ← 返回课题
      </Link>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">科研主张与证据</h1>
          <p className="mt-1 text-sm text-[var(--muted)]">
            {project?.name} ·
            将假设、发现、局限与支持或反证关联，保留适用条件和本人结论。
          </p>
        </div>
        <Button
          disabled={busy || !!recovery.pending || !recovery.ready}
          onClick={newClaim}
        >
          新增科研主张
        </Button>
      </div>
      {error && <ErrorState message={error} onRetry={() => void load()} />}{" "}
      {recovery.warning && <p role="alert">{recovery.warning}</p>}
      {notice && (
        <p role="status" className="text-sm text-[var(--accent)]">
          {notice}
        </p>
      )}
      {saveError && (
        <p role="alert" className="text-sm text-[var(--danger)]">
          {saveError}
        </p>
      )}
      {recovery.pending && (
        <Card>
          <CardContent>
            <p className="text-sm font-medium">
              待核查原请求：{recovery.pending.label}
            </p>
            <p className="text-xs text-[var(--muted)]">
              已冻结内容与幂等键，刷新不会自动重发；确认原请求后才可提交不同输入。
            </p>
            <details>
              <summary>核对冻结输入</summary>
              <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-all text-xs">
                {JSON.stringify(recovery.pending.body, null, 2)}
              </pre>
            </details>
            <div className="mt-2 flex gap-2">
              <Button
                variant="secondary"
                disabled={busy}
                onClick={() => void lookup()}
              >
                只读核查原请求
              </Button>
              <Button disabled={busy} onClick={() => void resume()}>
                继续原请求
              </Button>
            </div>
            {canAbandon && (
              <div className="mt-3 space-y-2">
                <label className="flex gap-2 text-xs">
                  <input
                    type="checkbox"
                    checked={abandonAck}
                    disabled={busy}
                    onChange={(e) => setAbandonAck(e.target.checked)}
                  />
                  核查未发现原请求；我已核对列表及审阅历史，放弃原请求后修正输入
                </label>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={busy || !abandonAck}
                  onClick={() => {
                    recovery.clear();
                    setCanAbandon(false);
                    setAbandonAck(false);
                    setNotice(
                      "原请求已放弃，未删除已保存历史；现在可修正输入。",
                    );
                  }}
                >
                  放弃原请求并修正
                </Button>
              </div>
            )}
          </CardContent>
        </Card>
      )}
      {editing && (
        <Card>
          <CardContent>
            <ClaimEditor
              key={editorKey}
              projectId={projectId}
              base={base}
              questions={questions}
              busy={busy || !!recovery.pending}
              onCancel={() => setEditing(false)}
              onSave={async (fields: Fields, evidence: Evidence[]) => {
                if (base)
                  await send(
                    `/claims/${base.claim_id}`,
                    {
                      ...fields,
                      evidence,
                      expected_revision_sha256: base.sha256,
                    },
                    "主张修订",
                    "PATCH",
                  );
                else
                  await send(
                    "/claims",
                    { ...fields, evidence, project_id: projectId },
                    "科研主张",
                  );
              }}
            />
          </CardContent>
        </Card>
      )}
      <div className="grid gap-4 xl:grid-cols-[minmax(220px,1fr)_minmax(0,3fr)]">
        <Card>
          <CardHeader>
            <h2 className="font-semibold">课题主张</h2>
            <Button
              size="sm"
              variant="ghost"
              disabled={listBusy || busy}
              onClick={() => void load()}
            >
              刷新主张
            </Button>
          </CardHeader>
          <CardContent className="space-y-2">
            {listBusy && <p role="status">读取列表中…</p>}
            {page && !page.items.length && (
              <EmptyState
                title="尚未记录科研主张"
                detail="先记录待验证假设，再逐步连接精读笔记与服务器证据。"
              />
            )}
            {page?.items.map((row) => (
              <button
                className={`block w-full rounded border p-3 text-left text-sm ${detail?.id === row.id ? "border-[var(--accent)]" : ""}`}
                key={row.id}
                disabled={busy || detailBusy}
                onClick={() => void open(row.id)}
              >
                {row.title}
                <small className="mt-1 block text-[var(--muted)]">
                  版本 {row.revision}
                </small>
              </button>
            ))}
            {page?.page.next_cursor && (
              <Button
                disabled={listBusy || busy}
                onClick={() => void load(page.page.next_cursor)}
              >
                下一页主张
              </Button>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardContent>
            {detailBusy ? (
              <LoadingState label="正在读取主张详情…" />
            ) : detail ? (
              <ClaimDetail
                key={`${detail.id}:${detail.current.sha256}:${detail.current.reviews.length}`}
                claim={detail}
                busy={busy || !!recovery.pending}
                onEdit={() => {
                  setBase(detail.current);
                  setEditorKey((k) => k + 1);
                  setEditing(true);
                }}
                onReview={review}
              />
            ) : (
              <EmptyState title="选择一个主张查看证据与版本" />
            )}
            {detailError && <ErrorState message={detailError} />}
          </CardContent>
        </Card>
      </div>
      <EvidenceBundles projectId={projectId} />
    </div>
  );
}
