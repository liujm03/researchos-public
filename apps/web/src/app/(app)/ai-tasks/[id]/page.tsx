"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import {
  ArrowLeft,
  Bot,
  Clock3,
  FileDiff,
  FolderOpen,
  ShieldAlert,
} from "lucide-react";

import { MarkdownViewer } from "@/components/markdown/markdown-viewer";
import { Button } from "@/components/ui/button";
import { ReproductionContextPanel } from "@/components/papers/reproduction-context";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { api, type PaperReproductionPreview } from "@/lib/api";
import {
  codexKindLabels,
  codexModeLabels,
  codexStatusLabels,
  formatCodexTime,
  runningCodexStatuses,
  type CodexCapabilities,
  type CodexEvent,
  type CodexTask,
  type CodexStartRequest,
  type CodexWorkspace,
} from "@/lib/codex";

function isMarkdownOutput(content: string): boolean {
  const text = content.trim();
  if (
    /^(?:#!|(?:#[^\n]*\n\s*)*(?:from\s+\S+\s+import\s|import\s|def\s+\w+\s*\(|class\s+\w+\s*[:(]|(?:export\s+)?(?:function|const|let|var)\s|using\s|package\s|<\?php))/.test(
      text,
    )
  )
    return false;
  if (
    /^(?:diff --git |@@ |Index: )/.test(text) ||
    /^---[^\n]*\n\+\+\+/.test(text) ||
    /^(?:[a-f0-9]{40}|[a-f0-9]{64})$/i.test(text)
  )
    return false;
  try {
    JSON.parse(text);
    return false;
  } catch {
    /* Plain text is not a JSON receipt. */
  }
  return (
    /(?:^|\n)(?:#{1,6}\s|[-*+]\s|\d+\.\s|```|~~~|>\s|\|[^\n]+\|)/.test(text) ||
    /\*\*[^*\n]+\*\*|\[[^\]\n]+\]\([^)\n]+\)/.test(text)
  );
}

export default function CodexTaskDetailPage() {
  const { id } = useParams<{ id: string }>();
  return <CodexTaskView key={id} id={id} />;
}

function CodexTaskView({ id }: { id: string }) {
  const [task, setTask] = useState<CodexTask | null>(null);
  const [events, setEvents] = useState<CodexEvent[]>([]);
  const [workspaces, setWorkspaces] = useState<CodexWorkspace[]>([]);
  const [capabilities, setCapabilities] = useState<CodexCapabilities | null>(
    null,
  );
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [confirmedWrite, setConfirmedWrite] = useState(false);
  const [paperContext, setPaperContext] =
    useState<PaperReproductionPreview | null>(null);
  const [paperContextLoading, setPaperContextLoading] = useState(false);
  const [paperContextError, setPaperContextError] = useState("");

  const load = useCallback(async () => {
    try {
      const [taskResult, eventResult, workspaceResult, capabilityResult] =
        await Promise.allSettled([
          api.get<CodexTask>(`/codex/tasks/${encodeURIComponent(id)}`),
          api.get<CodexEvent[]>(
            `/codex/tasks/${encodeURIComponent(id)}/events`,
          ),
          api.get<CodexWorkspace[]>("/codex/workspaces"),
          api.get<CodexCapabilities>("/codex/capabilities"),
        ]);
      if (taskResult.status === "fulfilled") {
        setTask(taskResult.value);
        if (taskResult.value.kind === "paper_reproduction") {
          setPaperContextLoading(true);
          try {
            const context = await api.get<PaperReproductionPreview>(
              "/codex/tasks/" + encodeURIComponent(id) + "/paper-context",
            );
            if (context.task_id !== id)
              throw new Error("冻结的论文来源未对应当前任务。");
            setPaperContext(context);
            setPaperContextError("");
          } catch (cause) {
            setPaperContext(null);
            setPaperContextError(
              cause instanceof Error ? cause.message : "无法读取冻结的论文来源",
            );
          } finally {
            setPaperContextLoading(false);
          }
        } else {
          setPaperContext(null);
          setPaperContextError("");
        }
      }
      if (eventResult.status === "fulfilled") setEvents(eventResult.value);
      if (workspaceResult.status === "fulfilled")
        setWorkspaces(workspaceResult.value);
      if (capabilityResult.status === "fulfilled")
        setCapabilities(capabilityResult.value);
      const failures = [
        taskResult,
        eventResult,
        workspaceResult,
        capabilityResult,
      ]
        .filter(
          (result): result is PromiseRejectedResult =>
            result.status === "rejected",
        )
        .map((result) =>
          result.reason instanceof Error ? result.reason.message : "请求失败",
        );
      setError(failures.join("；"));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "无法读取 Codex 任务");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    const handle = window.setTimeout(() => {
      void load();
    }, 0);
    return () => window.clearTimeout(handle);
  }, [load]);
  useEffect(() => {
    if (!task || !runningCodexStatuses.includes(task.status)) return;
    const interval = window.setInterval(() => {
      void load();
    }, 4000);
    return () => window.clearInterval(interval);
  }, [task, load]);

  const workspace = workspaces.find((item) => item.id === task?.workspace_id);
  const canStart = Boolean(
    task?.status === "DRAFT" &&
    task.kind !== "writing" &&
    capabilities?.available &&
    workspace?.available &&
    (task.mode !== "workspace_write" || workspace.write_available) &&
    workspace.path === task.workspace_path_snapshot &&
    workspace.allowed_modes.includes(task.mode) &&
    (task.kind !== "paper_reproduction" ||
      (paperContext && !paperContextError && !paperContextLoading)),
  );
  const canCancel = Boolean(
    task &&
    capabilities?.supports_cancel &&
    ["QUEUED", "RUNNING"].includes(task.status),
  );

  async function start() {
    if (
      !task ||
      !canStart ||
      (task.mode === "workspace_write" && !confirmedWrite)
    )
      return;
    setBusy(true);
    setError("");
    try {
      setTask(
        await api.post<CodexTask>(
          `/codex/tasks/${encodeURIComponent(task.id)}/start`,
          task.mode === "workspace_write"
            ? ({ confirm_write: true } satisfies CodexStartRequest)
            : ({} satisfies CodexStartRequest),
        ),
      );
      setConfirmedWrite(false);
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "启动任务失败");
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    if (!task || !canCancel) return;
    setBusy(true);
    setError("");
    try {
      setTask(
        await api.post<CodexTask>(
          `/codex/tasks/${encodeURIComponent(task.id)}/cancel`,
          {},
        ),
      );
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "取消任务失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <Link
        href="/ai-tasks"
        className="inline-flex items-center gap-2 text-xs text-[var(--muted)] hover:text-[var(--accent)]"
      >
        <ArrowLeft className="h-4 w-4" />
        全部 Codex 任务
      </Link>
      {loading ? (
        <LoadingState label="正在加载任务与执行记录…" />
      ) : !task ? (
        <ErrorState
          message={error || "找不到这项 Codex 任务"}
          onRetry={() => {
            setLoading(true);
            void load();
          }}
        />
      ) : (
        <>
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <p className="mb-1 flex items-center gap-2 text-xs font-medium uppercase tracking-[0.18em] text-[var(--accent)]">
                <Bot className="h-4 w-4" />
                Codex AI task
              </p>
              <h1 className="text-2xl font-semibold">{task.title}</h1>
              <p className="mt-2 text-sm text-[var(--muted)]">
                {codexKindLabels[task.kind] ?? task.kind} ·{" "}
                {codexModeLabels[task.mode] ?? task.mode} ·{" "}
                {codexStatusLabels[task.status] ?? task.status}
              </p>
            </div>
            <Button
              variant="secondary"
              onClick={() => {
                void load();
              }}
              disabled={busy}
            >
              刷新任务
            </Button>
          </div>
          {error && (
            <ErrorState
              message={error}
              onRetry={() => {
                void load();
              }}
            />
          )}
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(300px,0.8fr)]">
            <div className="space-y-4">
              {task.kind === "paper_reproduction" &&
                (paperContextLoading ? (
                  <LoadingState label="正在读取冻结的论文来源…" />
                ) : paperContextError ? (
                  <ErrorState
                    message={paperContextError}
                    onRetry={() => void load()}
                  />
                ) : paperContext ? (
                  <ReproductionContextPanel context={paperContext} />
                ) : (
                  <EmptyState
                    title="尚无可读取的论文来源快照"
                    detail="读取来源后才能检查并启动这项复现准备草稿。"
                  />
                ))}
              <Card>
                <CardHeader>
                  <h2 className="font-semibold">任务范围</h2>
                  <span className="text-xs text-[var(--muted)]">
                    ID {task.id}
                  </span>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="grid gap-3 text-xs sm:grid-cols-2">
                    <div>
                      <span className="text-[var(--muted)]">
                        创建时的工作区
                      </span>
                      <p className="mt-1 font-medium">
                        {workspace?.name ?? task.workspace_id}
                      </p>
                      <p className="mt-1 break-all text-[var(--muted)]">
                        {task.workspace_path_snapshot}
                      </p>
                      {workspace &&
                        workspace.path !== task.workspace_path_snapshot && (
                          <p className="mt-2 text-[var(--danger)]">
                            服务端当前路径与创建时不同，不能启动此草稿。
                          </p>
                        )}
                    </div>
                    <div>
                      <span className="text-[var(--muted)]">执行模式</span>
                      <p className="mt-1 font-medium">
                        {codexModeLabels[task.mode] ?? task.mode}
                      </p>
                      <p className="mt-1 text-[var(--muted)]">
                        {task.mode === "read_only"
                          ? "读取与分析，返回结果；不允许修改工作区文件。"
                          : "允许在上述工作区内修改文件；需确认范围后启动。"}
                      </p>
                    </div>
                  </div>
                  <div className="border-t border-[var(--border)] pt-4">
                    <h3 className="text-xs font-semibold">
                      提交给 Codex 的说明
                    </h3>
                    <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-6">
                      {task.prompt}
                    </p>
                  </div>
                </CardContent>
              </Card>
              {task.kind === "writing" && (
                <Card>
                  <CardContent className="space-y-2 text-sm">
                    <p>
                      专业写作任务在论文工作区核对
                      Skill、资料和计划后启动。此页保留执行状态、取消和原始回复。
                    </p>
                    {task.related_project_id && (
                      <Link
                        href={`/projects/${task.related_project_id}/publications`}
                        className="text-[var(--accent)]"
                      >
                        返回论文工作区 →
                      </Link>
                    )}
                  </CardContent>
                </Card>
              )}
              {task.status === "DRAFT" && task.kind !== "writing" && (
                <Card className="border-[var(--accent)]/40">
                  <CardHeader>
                    <div className="flex items-center gap-2">
                      <ShieldAlert className="h-4 w-4 text-[var(--accent)]" />
                      <h2 className="font-semibold">启动前检查</h2>
                    </div>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <p className="text-sm leading-6 text-[var(--muted)]">
                      {task.mode === "read_only"
                        ? "启动后 Codex 会读取上方允许的工作区并执行任务。请确认任务说明没有超出预期的数据范围。"
                        : "启动后 Codex 可以修改上方工作区的文件。目标路径必须正好是受信任的 Git 仓库根目录，且已跟踪与未跟踪文件均无待处理更改；后端会在启动和执行前检查。请核对任务说明中的允许修改范围，并在完成后检查改动。"}
                    </p>
                    {capabilities && (
                      <p className="text-xs leading-5 text-[var(--muted)]">
                        {capabilities.budget_mode === "PROVIDER_QUOTA"
                          ? "跟随 Codex 账户额度；已报告用量不是剩余额度。"
                          : "本次启动将记录服务端单任务 Token 上限 " +
                            (capabilities.max_tokens_per_task?.toLocaleString() ??
                              "未记录") +
                            "。"}
                        {capabilities.budget_mode !== "PROVIDER_QUOTA" &&
                          capabilities.token_limit_is_soft &&
                          "该上限为软限制：用量事件可能滞后，实际使用量可能超出阈值。"}
                      </p>
                    )}
                    {task.mode === "workspace_write" && (
                      <label className="flex items-start gap-2 rounded-md border border-[var(--border)] bg-[var(--background)] p-3 text-sm">
                        <input
                          type="checkbox"
                          checked={confirmedWrite}
                          onChange={(event) =>
                            setConfirmedWrite(event.target.checked)
                          }
                          className="mt-1 h-4 w-4 accent-[var(--accent)]"
                        />
                        <span>
                          我已核对{" "}
                          <strong>
                            {workspace?.name ?? task.workspace_id}
                          </strong>{" "}
                          的路径与上述任务说明，同意本次任务在该工作区内写入。
                        </span>
                      </label>
                    )}
                    {!canStart && (
                      <p className="text-xs text-[var(--danger)]">
                        暂时无法启动：
                        {!capabilities?.available
                          ? capabilities?.reason || "Codex 服务不可用"
                          : task.kind === "paper_reproduction" && !paperContext
                            ? "冻结的论文来源尚未读取"
                            : !workspace
                              ? "工作区已从服务端配置移除"
                              : !workspace.available
                                ? workspace.reason || "工作区不可用"
                                : task.mode === "workspace_write" &&
                                    !workspace.write_available
                                  ? workspace.write_reason ||
                                    "工作区不满足写入条件"
                                  : workspace.path !==
                                      task.workspace_path_snapshot
                                    ? "工作区路径已改变"
                                    : "当前工作区不允许此模式"}
                        。
                      </p>
                    )}
                    {canStart && (
                      <Button
                        onClick={start}
                        disabled={
                          busy ||
                          (task.mode === "workspace_write" && !confirmedWrite)
                        }
                      >
                        {busy
                          ? "启动中…"
                          : task.mode === "read_only"
                            ? "启动只读任务"
                            : "确认并启动写入任务"}
                      </Button>
                    )}
                  </CardContent>
                </Card>
              )}
              {task.error && (
                <Card className="border-[var(--danger)]/40">
                  <CardHeader>
                    <h2 className="font-semibold text-[var(--danger)]">
                      执行错误
                    </h2>
                  </CardHeader>
                  <CardContent>
                    <p className="whitespace-pre-wrap break-words text-sm">
                      {task.error}
                    </p>
                  </CardContent>
                </Card>
              )}
              {task.final_response && (
                <Card>
                  <CardHeader>
                    <h2 className="font-semibold">Codex 最终回复</h2>
                  </CardHeader>
                  <CardContent>
                    {isMarkdownOutput(task.final_response) ? (
                      <MarkdownViewer
                        content={task.final_response}
                        label="AI 任务输出"
                      />
                    ) : (
                      <pre
                        aria-label="AI 任务原始输出"
                        className="max-h-[720px] overflow-auto whitespace-pre-wrap break-words font-mono text-sm leading-6"
                      >
                        {task.final_response}
                      </pre>
                    )}
                  </CardContent>
                </Card>
              )}
              {task.diff_summary && (
                <Card>
                  <CardHeader>
                    <div className="flex items-center gap-2">
                      <FileDiff className="h-4 w-4 text-[var(--accent)]" />
                      <h2 className="font-semibold">文件改动摘要</h2>
                    </div>
                  </CardHeader>
                  <CardContent>
                    <p className="whitespace-pre-wrap break-words text-sm leading-6">
                      {task.diff_summary}
                    </p>
                  </CardContent>
                </Card>
              )}
              {task.mode === "workspace_write" &&
                ([
                  "COMPLETED",
                  "FAILED",
                  "CANCELLED",
                  "NEEDS_ATTENTION",
                ].includes(task.status) ||
                  task.diff_patch) && (
                  <Card>
                    <CardHeader>
                      <div className="flex items-center gap-2">
                        <FileDiff className="h-4 w-4 text-[var(--accent)]" />
                        <h2 className="font-semibold">实际文件补丁</h2>
                      </div>
                      <span className="text-xs text-[var(--muted)]">
                        只供审阅
                      </span>
                    </CardHeader>
                    <CardContent className="space-y-3">
                      {task.diff_truncated && (
                        <div
                          role="alert"
                          className="rounded-md border border-[var(--danger)]/40 bg-[var(--danger)]/5 p-3 text-xs leading-5 text-[var(--danger)]"
                        >
                          补丁已截断，下面只显示服务端保留的部分。请在工作区检查完整
                          Git diff 后再使用这些改动。
                        </div>
                      )}
                      {task.diff_patch ? (
                        <div className="max-h-[720px] max-w-full overflow-auto rounded-md border border-[var(--border)] bg-[var(--background)]">
                          <pre
                            className="min-w-max p-4 font-mono text-[11px] leading-5 whitespace-pre"
                            style={{ tabSize: 4 }}
                          >
                            {task.diff_patch}
                          </pre>
                        </div>
                      ) : (
                        <div
                          role="alert"
                          className="rounded-md border border-[var(--danger)]/40 bg-[var(--danger)]/5 p-3 text-xs leading-5 text-[var(--danger)]"
                        >
                          服务端未提供可审阅的补丁。任务可能没有文件改动，也可能未记录到补丁；请在工作区检查实际文件状态。摘要不能替代完整
                          diff。
                        </div>
                      )}
                    </CardContent>
                  </Card>
                )}
            </div>
            <div className="space-y-4">
              <Card>
                <CardHeader>
                  <h2 className="font-semibold">任务状态</h2>
                  <span className="text-xs text-[var(--accent)]">
                    {task.status}
                  </span>
                </CardHeader>
                <CardContent className="space-y-3 text-xs">
                  <div className="flex items-start gap-2">
                    <Clock3 className="mt-0.5 h-3.5 w-3.5 text-[var(--muted)]" />
                    <div className="space-y-1">
                      <p>创建：{formatCodexTime(task.created_at)}</p>
                      <p>启动：{formatCodexTime(task.started_at)}</p>
                      <p>完成：{formatCodexTime(task.completed_at)}</p>
                    </div>
                  </div>
                  <div className="border-t border-[var(--border)] pt-3 text-[var(--muted)]">
                    {task.provider_key} · {task.model_key}
                    {task.reasoning_effort && (
                      <> · 推理强度 {task.reasoning_effort}</>
                    )}
                  </div>
                  <div className="border-t border-[var(--border)] pt-3 text-[var(--muted)]">
                    输入 Token：
                    {task.input_tokens === null
                      ? "未知"
                      : task.input_tokens.toLocaleString()}{" "}
                    · 输出 Token：
                    {task.output_tokens === null
                      ? "未知"
                      : task.output_tokens.toLocaleString()}
                    <p className="mt-1">
                      {task.budget_mode === "PROVIDER_QUOTA"
                        ? "本任务跟随 Codex 账户额度；已报告用量不是剩余额度。"
                        : "本任务上限："}
                      {task.budget_mode !== "PROVIDER_QUOTA" &&
                        (task.max_tokens === null
                          ? task.status === "DRAFT"
                            ? "启动时确定"
                            : "未记录"
                          : task.max_tokens.toLocaleString())}
                      {task.budget_mode !== "PROVIDER_QUOTA" &&
                        capabilities?.token_limit_is_soft &&
                        " · 软上限，用量事件可能滞后"}
                    </p>
                  </div>
                  {task.token_budget_exceeded && (
                    <div
                      role="alert"
                      className="rounded-md border border-[var(--danger)]/40 bg-[var(--danger)]/5 p-3 font-medium leading-5 text-[var(--danger)]"
                    >
                      已检测到超过本任务 Token
                      软上限。停止请求可能晚于实际消耗；请检查执行事件和最终用量。
                    </div>
                  )}
                  {task.related_project_id && (
                    <Link
                      href={`/projects/${task.related_project_id}`}
                      className="block border-t border-[var(--border)] pt-3 text-[var(--accent)] hover:underline"
                    >
                      查看关联课题
                    </Link>
                  )}
                  {task.related_research_question_id && (
                    <div className="break-all text-[var(--muted)]">
                      关联研究问题：{task.related_research_question_id}
                    </div>
                  )}
                  {task.codex_thread_id && (
                    <div className="border-t border-[var(--border)] pt-3">
                      <span className="text-[var(--muted)]">
                        Codex thread / turn
                      </span>
                      <p className="mt-1 break-all font-mono">
                        {task.codex_thread_id}
                        {task.codex_turn_id ? ` / ${task.codex_turn_id}` : ""}
                      </p>
                    </div>
                  )}
                  {task.base_commit && (
                    <div className="border-t border-[var(--border)] pt-3">
                      <span className="text-[var(--muted)]">
                        执行时的 Git commit
                      </span>
                      <p className="mt-1 break-all font-mono">
                        {task.base_commit}
                      </p>
                    </div>
                  )}
                  {canCancel && (
                    <Button
                      variant="danger"
                      size="sm"
                      onClick={cancel}
                      disabled={busy}
                    >
                      {busy ? "处理中…" : "取消任务"}
                    </Button>
                  )}
                  {runningCodexStatuses.includes(task.status) && (
                    <p className="text-[var(--muted)]">
                      执行期间每 4 秒更新状态与事件。
                    </p>
                  )}
                </CardContent>
              </Card>
              <Card>
                <CardHeader>
                  <div className="flex items-center gap-2">
                    <FolderOpen className="h-4 w-4 text-[var(--accent)]" />
                    <h2 className="font-semibold">执行事件与审计</h2>
                  </div>
                  <span className="text-xs text-[var(--muted)]">
                    {events.length} 条
                  </span>
                </CardHeader>
                <CardContent className="p-0">
                  {events.length ? (
                    <ol className="divide-y divide-[var(--border)]">
                      {events.map((event) => (
                        <li key={event.id} className="px-5 py-3">
                          <div className="flex flex-wrap items-center gap-2 text-[11px]">
                            <span className="font-mono text-[var(--accent)]">
                              #{event.sequence}
                            </span>
                            <span className="font-medium">
                              {event.event_type}
                            </span>
                            <time className="text-[var(--muted)]">
                              {formatCodexTime(event.created_at)}
                            </time>
                          </div>
                          <p className="mt-1 whitespace-pre-wrap break-words text-xs leading-5 text-[var(--muted)]">
                            {event.message}
                          </p>
                        </li>
                      ))}
                    </ol>
                  ) : (
                    <EmptyState
                      title="暂无执行事件"
                      detail="启动任务后，状态变化与执行记录会出现在这里。"
                    />
                  )}
                </CardContent>
              </Card>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
