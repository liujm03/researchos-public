"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Textarea } from "@/components/ui/input";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { api } from "@/lib/api";
import type { components } from "@/lib/generated";

type Options = components["schemas"]["CodeChangeOptions"];
type Preview = components["schemas"]["CodeChangePreview"];
type Plan = components["schemas"]["CodeChangeOut"];
type Page = components["schemas"]["CodeChangePage"];
type Create = components["schemas"]["CodeChangeCreate"];
type Apply = components["schemas"]["CodeChangeApply"];
type Import = components["schemas"]["CodeChangeImport"];
type Reconciliation = components["schemas"]["CodeChangeReconciliation"];
type Abandon = components["schemas"]["CodeChangeAbandon"];
type Pending = { path: string; body: Create | Apply | Import | Abandon };
const labels: Record<string, string> = {
  DRAFT: "建议草稿",
  PROPOSED: "等待核对变更",
  APPLYING: "正在应用",
  APPLIED: "已核验文件",
  PARTIAL: "部分应用，需核查",
  NEEDS_ATTENTION: "结果待核查",
  ABANDONED: "已保留现状并结束应用",
};
const failure = (cause: unknown) =>
  cause instanceof Error ? cause.message : "请求失败";

export default function CodeChangesPage() {
  const { id } = useParams<{ id: string }>();
  return <Workspace key={id} projectId={id} />;
}
function Workspace({ projectId }: { projectId: string }) {
  const base = `/projects/${projectId}/code-changes`;
  const [options, setOptions] = useState<Options | null>(null);
  const [history, setHistory] = useState<Page | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [paths, setPaths] = useState("");
  const [instructions, setInstructions] = useState("");
  const [pending, setPending] = useState<Pending | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [applyConfirmed, setApplyConfirmed] = useState(false);
  const [unknownConfirmed, setUnknownConfirmed] = useState(false);
  const [observed, setObserved] = useState<Reconciliation | null>(null);
  const [abandonConfirmed, setAbandonConfirmed] = useState(false);
  const busyRef = useRef(false);
  const historySequence = useRef(0);
  const [historyLoading, setHistoryLoading] = useState(false);
  const pendingKey = `researchos:code-change-pending:${projectId}`;
  function beginAction() {
    if (busyRef.current) return false;
    busyRef.current = true;
    setBusy(true);
    return true;
  }
  function endAction() {
    busyRef.current = false;
    setBusy(false);
  }
  const loadHistory = useCallback(
    async (cursor?: string) => {
      const sequence = ++historySequence.current;
      setHistoryLoading(true);
      try {
        const saved = await api.get<Page>(
          `${base}/plans?limit=20${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
        );
        if (sequence === historySequence.current) setHistory(saved);
      } finally {
        if (sequence === historySequence.current) setHistoryLoading(false);
      }
    },
    [base],
  );
  const load = useCallback(async () => {
    setError("");
    try {
      const [opts, saved] = await Promise.all([
        api.get<Options>(`${base}/options`),
        api.get<Page>(`${base}/plans?limit=20`),
      ]);
      setOptions(opts);
      setHistory(saved);
    } catch (cause) {
      setError(failure(cause));
    } finally {
      setLoading(false);
    }
  }, [base]);
  useEffect(() => {
    const timer = setTimeout(() => {
      try {
        const raw = sessionStorage.getItem(pendingKey);
        if (raw) {
          const record: unknown = JSON.parse(raw);
          if (
            typeof record === "object" &&
            record !== null &&
            "path" in record &&
            "body" in record &&
            typeof record.path === "string" &&
            typeof record.body === "object" &&
            record.body !== null &&
            "idempotency_key" in record.body &&
            typeof record.body.idempotency_key === "string" &&
            record.body.idempotency_key.length <= 120 &&
            (record.path === `${base}/plans` ||
              new RegExp(
                `^${base}/plans/[0-9a-f-]{36}/(import-result|apply|abandon)$`,
              ).test(record.path))
          ) {
            setPending(record as Pending);
          } else setError("保存的待核查请求格式不可用，请先核对改进历史。");
        }
      } catch {
        setError("无法读取已保存的待核查请求，请先核对改进历史。");
      }
      void load();
    }, 0);
    return () => clearTimeout(timer);
  }, [load, pendingKey, base]);
  async function refresh(planId: string) {
    if (!beginAction()) return;
    setObserved(null);
    setAbandonConfirmed(false);
    setError("");
    try {
      setPlan(await api.get<Plan>(`${base}/plans/${planId}`));
      setApplyConfirmed(false);
      setUnknownConfirmed(false);
      await loadHistory();
    } catch (cause) {
      setError(failure(cause));
    } finally {
      endAction();
    }
  }
  async function makePreview(event: FormEvent) {
    event.preventDefault();
    if (!options?.binding_id || !beginAction()) return;
    setError("");
    setPreview(null);
    try {
      setPreview(
        await api.post<Preview>(`${base}/preview`, {
          binding_id: options.binding_id,
          paths: paths
            .split(/\r?\n/)
            .map((p) => p.trim())
            .filter(Boolean),
          instructions,
        }),
      );
    } catch (cause) {
      setError(failure(cause));
    } finally {
      endAction();
    }
  }
  async function mutate(request: Pending) {
    if (!beginAction()) return;
    try {
      sessionStorage.setItem(pendingKey, JSON.stringify(request));
    } catch {
      setError(
        "无法保存同一请求的恢复依据；尚未提交操作。请允许本地会话存储后重试。",
      );
      endAction();
      return;
    }
    setObserved(null);
    setAbandonConfirmed(false);
    setPending(request);
    setError("");
    try {
      const result = await api.post<Plan>(request.path, request.body);
      setPlan(result);
      setPending(null);
      sessionStorage.removeItem(pendingKey);
      setPreview(null);
      setApplyConfirmed(false);
      setUnknownConfirmed(false);
      await loadHistory();
    } catch (cause) {
      setError(
        `${failure(cause)}。请核查历史或恢复同一请求；不自动重复调用或写入。`,
      );
    } finally {
      endAction();
    }
  }
  async function inspectApplication() {
    if (!plan || !beginAction()) return;
    setError("");
    setObserved(null);
    setAbandonConfirmed(false);
    try {
      setObserved(
        await api.post<Reconciliation>(
          `${base}/plans/${plan.id}/inspect-application`,
        ),
      );
    } catch (cause) {
      setError(failure(cause));
    } finally {
      endAction();
    }
  }
  async function inspectPendingCreate() {
    if (!pending || pending.path !== `${base}/plans` || !beginAction()) return;
    setError("");
    try {
      const result = await api.get<Plan>(
        `${base}/plans/lookup?idempotency_key=${encodeURIComponent(pending.body.idempotency_key)}`,
      );
      setPlan(result);
      sessionStorage.removeItem(pendingKey);
      setPending(null);
      setPreview(null);
      await loadHistory();
    } catch (cause) {
      setError(`${failure(cause)}。原请求及同一幂等键保留；没有创建新请求。`);
    } finally {
      endAction();
    }
  }
  if (loading) return <LoadingState label="加载代码改进工作区…" />;
  if (!options)
    return (
      <ErrorState
        message={error || "无法加载课题"}
        onRetry={() => void load()}
      />
    );
  const unknown =
    plan && ["APPLYING", "PARTIAL", "NEEDS_ATTENTION"].includes(plan.status);
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Link href={`/projects/${projectId}`}>← 返回课题</Link>
        <Link href={`/projects/${projectId}/archive`}>私有版本归档 →</Link>
      </div>
      <div>
        <h1 className="text-2xl font-semibold">代码改进</h1>
        <p className="mt-2 text-sm text-[var(--muted)]">
          选择实际代码文件，生成无执行工具的建议，核对差异后应用。实验和仿真交课题组服务器。
        </p>
      </div>
      {error && <ErrorState message={error} />}
      {!options.enabled && (
        <p role="status">
          本机受限文件修改尚未启用，请在服务端配置 CODE_CHANGES_ENABLED。
        </p>
      )}
      {!options.binding_id && (
        <EmptyState
          title="先绑定此课题的独立私有仓库"
          detail="在私有版本页选择本机项目目录和私有仓库，再选择代码文件。"
        />
      )}
      {pending && (
        <Card>
          <CardContent className="space-y-3">
            <p>本次请求尚待核查，原请求与幂等键保留；没有自动重放。</p>
            <div className="flex gap-2">
              <Button disabled={busy} onClick={() => void mutate(pending)}>
                恢复同一请求
              </Button>
              {pending.path === `${base}/plans` && (
                <Button
                  variant="secondary"
                  disabled={busy}
                  onClick={() => void inspectPendingCreate()}
                >
                  只读核查本次草稿
                </Button>
              )}
              <Button
                variant="secondary"
                disabled={busy || historyLoading}
                onClick={() =>
                  void loadHistory().catch((c) => setError(failure(c)))
                }
              >
                核查历史
              </Button>
            </div>
          </CardContent>
        </Card>
      )}
      {options.enabled && options.binding_id && (
        <Card>
          <CardHeader>
            <h2 className="font-semibold">选择文件和改进目标</h2>
            <span className="text-xs text-[var(--muted)]">
              {options.repository} · {options.workspace_key}
            </span>
          </CardHeader>
          <CardContent>
            <form className="space-y-4" onSubmit={makePreview}>
              <fieldset disabled={busy || !!pending} className="space-y-4">
                <label className="block space-y-2 text-sm">
                  相对文件路径（每行一个，最多20个）
                  <Textarea
                    aria-label="相对文件路径（每行一个，最多20个）"
                    required
                    value={paths}
                    onChange={(e) => {
                      setPaths(e.target.value);
                      setPreview(null);
                    }}
                    placeholder={"src/model.py\nREADME.md"}
                  />
                </label>
                <p className="text-xs text-[var(--muted)]">
                  仅选定文本；新文件的父目录必须已存在。PDF、数据、权重和凭据不能作为代码输入。
                </p>
                <label className="block space-y-2 text-sm">
                  改进目标
                  <Textarea
                    aria-label="改进目标"
                    required
                    maxLength={12000}
                    value={instructions}
                    onChange={(e) => {
                      setInstructions(e.target.value);
                      setPreview(null);
                    }}
                  />
                </label>
                <Button type="submit">预览所选原文与外发范围</Button>
              </fieldset>
            </form>
            {preview && (
              <div className="mt-5 space-y-3">
                <p className="text-sm">
                  下列文件全文将进入 Codex
                  草稿。此预览尚未调用AI、运行或修改文件。
                </p>
                {preview.files.map((file) => (
                  <details
                    key={file.path}
                    className="rounded border border-[var(--border)] p-3"
                  >
                    <summary>
                      {file.path} · {file.exists ? "现有文件" : "新文件"} ·{" "}
                      {file.size_bytes} bytes
                    </summary>
                    <p className="my-2 break-all font-mono text-xs">
                      原SHA：{file.sha256 ?? "不存在"}
                    </p>
                    <pre className="max-h-80 overflow-auto whitespace-pre-wrap text-xs">
                      {file.content}
                    </pre>
                  </details>
                ))}
                <Button
                  disabled={busy || !!pending}
                  onClick={() =>
                    void mutate({
                      path: `${base}/plans`,
                      body: {
                        selection: preview.selection,
                        preview_sha256: preview.preview_sha256,
                        approve_source_transfer: true,
                        idempotency_key: crypto.randomUUID(),
                      } satisfies Create,
                    })
                  }
                >
                  批准所选代码外发并保存建议草稿
                </Button>
              </div>
            )}
          </CardContent>
        </Card>
      )}
      {plan && (
        <Card>
          <CardHeader>
            <h2 className="font-semibold">
              {labels[plan.status] ?? plan.status}
            </h2>
            <Button
              size="sm"
              variant="secondary"
              disabled={busy}
              onClick={() => void refresh(plan.id)}
            >
              刷新任务与文件状态
            </Button>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-sm">
              AI任务：{plan.task_status} ·{" "}
              <Link
                className="text-[var(--accent)] underline"
                href={`/ai-tasks/${plan.task_id}`}
              >
                查看并明确启动代码建议
              </Link>
            </p>
            <p className="text-xs text-[var(--muted)]">
              保存草稿不启动AI。任务输出不会执行代码或仿真；应用操作另行批准。
            </p>
            {plan.task_status === "COMPLETED" &&
              plan.task_result_sha256 &&
              !plan.proposal_sha256 && (
                <Button
                  disabled={busy || !!pending}
                  onClick={() =>
                    void mutate({
                      path: `${base}/plans/${plan.id}/import-result`,
                      body: {
                        expected_task_result_sha256: plan.task_result_sha256!,
                        idempotency_key: crypto.randomUUID(),
                      } satisfies Import,
                    })
                  }
                >
                  读取已完成的建议为变更候选
                </Button>
              )}
            {plan.rationale && (
              <p className="whitespace-pre-wrap text-sm">{plan.rationale}</p>
            )}
            {plan.proposal_files.map((file) => (
              <details
                key={file.path}
                open
                className="rounded border border-[var(--border)] p-3"
              >
                <summary>
                  {file.path} · {file.size_bytes} bytes
                </summary>
                <p className="my-2 break-all font-mono text-xs">
                  原SHA：{file.before_sha256 ?? "新文件"}
                  <br />
                  新SHA：{file.after_sha256}
                </p>
                <pre className="max-h-96 overflow-auto whitespace-pre-wrap bg-[var(--surface)] p-3 text-xs">
                  {file.diff}
                </pre>
                <details className="mt-3">
                  <summary>完整新文本</summary>
                  <pre className="max-h-80 overflow-auto whitespace-pre-wrap text-xs">
                    {file.after_text}
                  </pre>
                </details>
              </details>
            ))}
            {plan.proposal_sha256 &&
              !["APPLIED", "ABANDONED"].includes(plan.status) && (
                <div className="space-y-3">
                  <label className="flex items-start gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={applyConfirmed}
                      disabled={busy || !!pending}
                      onChange={(e) => setApplyConfirmed(e.target.checked)}
                    />
                    我已核对具体差异，批准修改这些文件
                  </label>
                  {unknown && (
                    <label className="flex items-start gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={unknownConfirmed}
                        disabled={busy || !!pending}
                        onChange={(e) => setUnknownConfirmed(e.target.checked)}
                      />
                      我已核查之前的部分或未知应用，批准复核同一变更并继续；冲突文件不得覆盖
                    </label>
                  )}
                  <Button
                    disabled={
                      busy ||
                      !!pending ||
                      !applyConfirmed ||
                      (!!unknown && !unknownConfirmed)
                    }
                    onClick={() =>
                      void mutate({
                        path: `${base}/plans/${plan.id}/apply`,
                        body: {
                          proposal_sha256: plan.proposal_sha256!,
                          approve_apply: true,
                          acknowledge_unknown: !!unknown && unknownConfirmed,
                          idempotency_key: crypto.randomUUID(),
                        } satisfies Apply,
                      })
                    }
                  >
                    {unknown ? "核查并恢复同一变更" : "批准应用并核验文件"}
                  </Button>
                </div>
              )}
            {unknown && (
              <div className="space-y-3 rounded border border-[var(--border)] p-3">
                <Button
                  variant="secondary"
                  disabled={busy || !!pending}
                  onClick={() => void inspectApplication()}
                >
                  只读核查实际文件
                </Button>
                {observed && (
                  <>
                    <p className="text-sm">
                      以下是实际文件状态，尚未修改或结束应用。
                    </p>
                    {observed.files.map((file) => (
                      <details key={file.path}>
                        <summary>
                          {file.path} · {file.exists ? file.sha256 : "不存在"}
                        </summary>
                        <pre className="max-h-64 overflow-auto whitespace-pre-wrap text-xs">
                          {file.content}
                        </pre>
                      </details>
                    ))}
                    <label className="flex items-start gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={abandonConfirmed}
                        disabled={busy || !!pending}
                        onChange={(e) => setAbandonConfirmed(e.target.checked)}
                      />
                      我选择保留这些实际文件，结束本次应用，不再写入剩余变更
                    </label>
                    <Button
                      variant="secondary"
                      disabled={busy || !!pending || !abandonConfirmed}
                      onClick={() =>
                        void mutate({
                          path: `${base}/plans/${plan.id}/abandon`,
                          body: {
                            observed_sha256: observed.observed_sha256,
                            approve_abandon: true,
                            idempotency_key: crypto.randomUUID(),
                          } satisfies Abandon,
                        })
                      }
                    >
                      保留现状并结束本次应用
                    </Button>
                  </>
                )}
              </div>
            )}
            {plan.status === "ABANDONED" && (
              <p role="status">
                已核对实际文件并保留现状；没有宣称剩余变更完成。可以重新选择当前文件或进入私有归档。
              </p>
            )}
            {plan.status === "APPLIED" && (
              <p role="status">
                已收到文件字节核验回执。可进入私有版本页归档；这不代表科研实验或复现已通过。
              </p>
            )}
            {plan.attempts.map((attempt) => (
              <details
                key={attempt.id}
                className="rounded border border-[var(--border)] p-3"
              >
                <summary>应用回执 · {attempt.status}</summary>
                {attempt.error_code && (
                  <p className="my-2 text-sm text-[var(--danger)]">
                    {attempt.error_code}
                  </p>
                )}
                {attempt.receipts.map((receipt) => (
                  <p key={receipt.path} className="mt-2 break-all text-xs">
                    {receipt.path} ·{" "}
                    {receipt.reused ? "已存在字节复核" : "实际写入核验"} ·{" "}
                    {receipt.after_sha256}
                  </p>
                ))}
                {attempt.observations.map((file) => (
                  <p key={file.path} className="mt-2 break-all text-xs">
                    保留现状观察：{file.path} ·{" "}
                    {file.exists ? file.sha256 : "不存在"}
                  </p>
                ))}
              </details>
            ))}
            <details>
              <summary>冻结的原文件（恢复依据）</summary>
              {plan.files.map((file) => (
                <div key={file.path} className="my-3">
                  <h3>{file.path}</h3>
                  <pre className="max-h-64 overflow-auto whitespace-pre-wrap text-xs">
                    {file.content}
                  </pre>
                </div>
              ))}
            </details>
          </CardContent>
        </Card>
      )}
      <Card>
        <CardHeader>
          <h2 className="font-semibold">已有代码改进</h2>
        </CardHeader>
        <CardContent className="space-y-2">
          {historyLoading && <p role="status">正在读取改进历史…</p>}
          {history?.items.length ? (
            history.items.map((item) => (
              <Button
                key={item.id}
                variant="secondary"
                className="w-full justify-between"
                disabled={busy}
                onClick={() => void refresh(item.id)}
              >
                <span>{labels[item.status] ?? item.status}</span>
                <span className="text-xs">
                  {new Date(item.created_at).toLocaleString("zh-CN")}
                </span>
              </Button>
            ))
          ) : (
            <EmptyState title="暂无代码改进记录" />
          )}
          {history?.page.next_cursor && (
            <Button
              variant="secondary"
              disabled={busy || historyLoading}
              onClick={() =>
                void loadHistory(history.page.next_cursor ?? undefined).catch(
                  (c) => setError(failure(c)),
                )
              }
            >
              下一页改进记录
            </Button>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
