"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import {
  ArrowRight,
  Bot,
  FolderOpen,
  Plus,
  ShieldCheck,
  ShieldAlert,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input, Textarea } from "@/components/ui/input";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { api, type Page, type Project, type ProjectQuestion } from "@/lib/api";
import {
  codexKindLabels,
  codexModeLabels,
  codexStatusLabels,
  formatCodexTime,
  type CodexCapabilities,
  type CodexKind,
  type CodexTask,
  type CodexTaskCreate,
  type CodexTaskSummary,
  type CodexWorkspace,
} from "@/lib/codex";

export default function CodexTasksPage() {
  const router = useRouter();
  const [capabilities, setCapabilities] = useState<CodexCapabilities | null>(
    null,
  );
  const [workspaces, setWorkspaces] = useState<CodexWorkspace[]>([]);
  const [tasks, setTasks] = useState<CodexTaskSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [createMounted, setCreateMounted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [title, setTitle] = useState("");
  const [prompt, setPrompt] = useState("");
  const [kind, setKind] = useState<CodexKind>("general");
  const mode = "read_only" as const;
  const [workspaceId, setWorkspaceId] = useState("");
  const [projects, setProjects] = useState<Project[]>([]);
  const [questions, setQuestions] = useState<ProjectQuestion[]>([]);
  const [projectId, setProjectId] = useState("");
  const [questionId, setQuestionId] = useState("");
  const [projectError, setProjectError] = useState("");
  const pendingCreate = useRef<{ signature: string; key: string } | null>(null);

  const load = useCallback(async () => {
    setError("");
    try {
      const [capabilityResult, workspaceResult, taskResult] =
        await Promise.allSettled([
          api.get<CodexCapabilities>("/codex/capabilities"),
          api.get<CodexWorkspace[]>("/codex/workspaces"),
          api.get<CodexTaskSummary[]>("/codex/tasks"),
        ]);
      if (capabilityResult.status === "fulfilled")
        setCapabilities(capabilityResult.value);
      if (workspaceResult.status === "fulfilled") {
        setWorkspaces(workspaceResult.value);
        setWorkspaceId(
          (current) =>
            current ||
            workspaceResult.value.find(
              (item) =>
                item.available && item.allowed_modes.includes("read_only"),
            )?.id ||
            "",
        );
      }
      if (taskResult.status === "fulfilled") setTasks(taskResult.value);
      const failures = [capabilityResult, workspaceResult, taskResult]
        .filter(
          (result): result is PromiseRejectedResult =>
            result.status === "rejected",
        )
        .map((result) =>
          result.reason instanceof Error ? result.reason.message : "请求失败",
        );
      if (failures.length) setError(failures.join("；"));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "无法加载 Codex 任务");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const handle = window.setTimeout(() => {
      void load();
    }, 0);
    return () => window.clearTimeout(handle);
  }, [load]);
  useEffect(() => {
    let active = true;
    api
      .get<Page<Project>>("/projects?limit=100")
      .then((result) => {
        if (active) setProjects(result.items);
      })
      .catch((cause) => {
        if (active)
          setProjectError(
            cause instanceof Error ? cause.message : "课题关联暂不可用",
          );
      });
    return () => {
      active = false;
    };
  }, []);
  useEffect(() => {
    if (!projectId) return;
    let active = true;
    api
      .get<ProjectQuestion[]>(
        `/projects/${encodeURIComponent(projectId)}/questions`,
      )
      .then((result) => {
        if (active) setQuestions(result);
      })
      .catch((cause) => {
        if (active)
          setProjectError(
            cause instanceof Error ? cause.message : "研究问题暂不可用",
          );
      });
    return () => {
      active = false;
    };
  }, [projectId]);

  const selectedWorkspace = workspaces.find((item) => item.id === workspaceId);
  const availableWorkspaces = workspaces.filter((item) => item.available);
  const draftKindLabels: Partial<Record<CodexKind, string>> = {
    general: "研究策划草稿",
    repository_analysis: "仓库分析建议",
    code_review: "代码审查建议",
    bug_fix: "缺陷修复建议",
    code_change: "代码改进建议",
    test_generation: "软件测试代码建议",
  };
  const canCreate = Boolean(
    selectedWorkspace?.available &&
    selectedWorkspace.allowed_modes.includes(mode) &&
    kind in draftKindLabels,
  );

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canCreate) return;
    setBusy(true);
    setError("");
    try {
      const body: CodexTaskCreate = {
        title: title.trim(),
        prompt: prompt.trim(),
        kind,
        mode,
        workspace_id: workspaceId,
        related_project_id: projectId || null,
        related_research_question_id: questionId || null,
      };
      const signature = JSON.stringify(body);
      if (pendingCreate.current?.signature !== signature)
        pendingCreate.current = { signature, key: crypto.randomUUID() };
      const task = await api.post<CodexTask>("/codex/tasks", {
        ...body,
        idempotency_key: pendingCreate.current.key,
      });
      pendingCreate.current = null;
      router.push(`/ai-tasks/${task.id}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "创建任务失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="mb-1 text-xs font-medium uppercase tracking-[0.18em] text-[var(--accent)]">
            Codex AI tasks
          </p>
          <h1 className="flex items-center gap-2 text-2xl font-semibold">
            <Bot className="h-6 w-6 text-[var(--accent)]" />
            Codex AI 任务
          </h1>
          <p className="mt-1 text-sm text-[var(--muted)]">
            保存研究策划与代码建议草稿，保留历史任务记录。实验、训练、评价与仿真交由课题组服务器执行。
          </p>
        </div>
        {!loading && (
          <Button
            variant="secondary"
            onClick={() => {
              setLoading(true);
              void load();
            }}
          >
            刷新状态
          </Button>
        )}
      </div>

      {loading ? (
        <LoadingState label="正在加载 Codex 能力和任务…" />
      ) : (
        <>
          {error && (
            <ErrorState
              message={error}
              onRetry={() => {
                setLoading(true);
                void load();
              }}
            />
          )}
          {capabilities && (
            <>
              <p className="text-sm">
                {capabilities.available ? "Codex 可用" : "Codex 暂不可用"} ·{" "}
                {capabilities.model_key || "模型未配置"}
                {capabilities.reason ? ` · ${capabilities.reason}` : ""}
              </p>
              <details className="rounded-md border border-[var(--border)]">
                <summary className="cursor-pointer px-4 py-3 text-sm">
                  查看接入与运行限制
                </summary>{" "}
                <Card>
                  <CardContent className="flex flex-wrap items-start gap-3">
                    <span
                      className={`mt-1 flex h-8 w-8 items-center justify-center rounded-lg ${capabilities.available ? "bg-emerald-500/10 text-emerald-500" : "bg-[var(--surface-hover)] text-[var(--muted)]"}`}
                    >
                      {capabilities.available ? (
                        <ShieldCheck className="h-4 w-4" />
                      ) : (
                        <ShieldAlert className="h-4 w-4" />
                      )}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="text-sm font-semibold">
                        {capabilities.available
                          ? "Codex 任务服务可用"
                          : capabilities.enabled
                            ? "Codex 任务服务暂不可用"
                            : "Codex 任务服务未启用"}
                      </div>
                      <p className="mt-1 text-xs leading-5 text-[var(--muted)]">
                        Provider：{capabilities.provider} · 模型：
                        {capabilities.model_key || "未配置"}
                        {capabilities.reasoning_effort && (
                          <> · 推理强度 {capabilities.reasoning_effort}</>
                        )}{" "}
                        · {availableWorkspaces.length} 个可用工作区。
                        {capabilities.reason ? ` ${capabilities.reason}` : ""}
                      </p>
                      <p className="mt-1 text-xs leading-5 text-[var(--muted)]">
                        {capabilities.budget_mode === "PROVIDER_QUOTA"
                          ? "跟随 Codex 账户额度；已报告用量不是剩余额度"
                          : "单任务 Token 上限：" +
                            (capabilities.max_tokens_per_task?.toLocaleString() ??
                              "未记录")}
                        {capabilities.budget_mode !== "PROVIDER_QUOTA" &&
                          capabilities.token_limit_is_soft &&
                          "（软上限；用量事件可能滞后，实际用量可能短暂超出）"}
                        。
                      </p>
                      {!capabilities.available && (
                        <p className="mt-2 text-xs leading-5 text-[var(--muted)]">
                          以服务端返回的能力与原因决定是否可启动；修改配置不能绕过本地科研执行禁令。需要
                          AI 研究策划时，请从课题进入已限制工具的研究规划。
                        </p>
                      )}
                    </div>
                  </CardContent>
                </Card>
              </details>
            </>
          )}
          {availableWorkspaces.length === 0 && (
            <Card>
              <CardContent>
                <EmptyState
                  title="尚无可用的 Codex 工作区"
                  detail={
                    workspaces.length
                      ? "配置的目录目前不存在；修复服务端路径后即可创建草稿。"
                      : "请在服务端配置允许的工作区与执行权限；任务不会接受浏览器输入的任意路径。"
                  }
                />
              </CardContent>
            </Card>
          )}

          <Card>
            <CardHeader>
              <h2 className="font-semibold">最近任务记录</h2>
              <span className="text-xs text-[var(--muted)]">
                最多显示 100 项 · 当前 {tasks.length} 项
              </span>
            </CardHeader>
            <CardContent className="p-0">
              {tasks.length ? (
                <div className="divide-y divide-[var(--border)]">
                  {tasks.map((task) => (
                    <Link
                      key={task.id}
                      href={`/ai-tasks/${task.id}`}
                      className="flex items-start justify-between gap-4 px-5 py-4 hover:bg-[var(--surface-hover)]"
                    >
                      <div className="min-w-0">
                        <h3 className="truncate text-sm font-medium">
                          {task.title}
                        </h3>
                        <p className="mt-1 text-xs text-[var(--muted)]">
                          {codexKindLabels[task.kind] ?? task.kind} ·{" "}
                          {codexModeLabels[task.mode] ?? task.mode} ·{" "}
                          {task.workspace_id}
                        </p>
                        <p className="mt-2 text-xs text-[var(--muted)]">
                          {formatCodexTime(task.created_at)} ·{" "}
                          {codexStatusLabels[task.status] ?? task.status}
                        </p>
                        {task.error && (
                          <p className="mt-1 line-clamp-1 text-xs text-[var(--danger)]">
                            {task.error}
                          </p>
                        )}
                      </div>
                      <ArrowRight className="mt-1 h-4 w-4 shrink-0 text-[var(--muted)]" />
                    </Link>
                  ))}
                </div>
              ) : (
                <EmptyState
                  title="暂无 Codex 任务"
                  detail="配置工作区后，可在这里创建首个任务草稿。"
                />
              )}
            </CardContent>
          </Card>
          {availableWorkspaces.length > 0 && (
            <details
              className="rounded-md border border-[var(--border)] bg-[var(--surface)]"
              onToggle={(event) => {
                if (event.currentTarget.open) setCreateMounted(true);
              }}
            >
              <summary className="cursor-pointer px-4 py-3 text-sm font-medium">
                新建任务草稿
              </summary>
              {createMounted && (
                <>
                  <Card>
                    <CardHeader>
                      <div className="flex items-center gap-2">
                        <Plus className="h-4 w-4 text-[var(--accent)]" />
                        <h2 className="font-semibold">新建任务草稿</h2>
                      </div>
                      <span className="text-xs text-[var(--muted)]">
                        创建后需再次确认启动
                      </span>
                    </CardHeader>
                    <CardContent>
                      <form
                        onSubmit={create}
                        className="grid gap-4 lg:grid-cols-2"
                      >
                        <label className="space-y-1.5 text-xs font-medium lg:col-span-2">
                          任务名称
                          <Input
                            required
                            maxLength={160}
                            value={title}
                            onChange={(event) => setTitle(event.target.value)}
                            placeholder="例如：梳理输电线路山火检测实验差异"
                          />
                        </label>
                        <label className="space-y-1.5 text-xs font-medium">
                          任务类型
                          <select
                            aria-label="任务类型"
                            value={kind}
                            onChange={(event) =>
                              setKind(event.target.value as CodexKind)
                            }
                            className="h-9 w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-3 text-sm"
                          >
                            {(Object.keys(draftKindLabels) as CodexKind[]).map(
                              (item) => (
                                <option key={item} value={item}>
                                  {draftKindLabels[item]}
                                </option>
                              ),
                            )}
                          </select>
                        </label>
                        <div className="space-y-1.5 text-xs font-medium">
                          <p>资料处理模式</p>
                          <p className="rounded-md border border-[var(--border)] px-3 py-2">
                            只读策划与代码建议
                          </p>
                        </div>
                        <label className="space-y-1.5 text-xs font-medium lg:col-span-2">
                          <span className="inline-flex items-center gap-1">
                            <FolderOpen className="h-3.5 w-3.5" />
                            允许的工作区
                          </span>
                          <select
                            required
                            value={workspaceId}
                            onChange={(event) =>
                              setWorkspaceId(event.target.value)
                            }
                            className="h-9 w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-3 text-sm"
                          >
                            <option value="">选择工作区</option>
                            {availableWorkspaces
                              .filter((workspace) =>
                                workspace.allowed_modes.includes(mode),
                              )
                              .map((workspace) => (
                                <option key={workspace.id} value={workspace.id}>
                                  {workspace.name} — {workspace.path}
                                </option>
                              ))}
                          </select>
                        </label>
                        <label className="space-y-1.5 text-xs font-medium">
                          关联课题（可选）
                          <select
                            value={projectId}
                            onChange={(event) => {
                              setProjectId(event.target.value);
                              setQuestionId("");
                              setQuestions([]);
                              setProjectError("");
                            }}
                            className="h-9 w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-3 text-sm"
                          >
                            <option value="">不关联课题</option>
                            {projects.map((project) => (
                              <option key={project.id} value={project.id}>
                                {project.name}
                              </option>
                            ))}
                          </select>
                        </label>
                        <label className="space-y-1.5 text-xs font-medium">
                          关联研究问题（可选）
                          <select
                            value={questionId}
                            onChange={(event) =>
                              setQuestionId(event.target.value)
                            }
                            disabled={!projectId}
                            className="h-9 w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-3 text-sm"
                          >
                            <option value="">不关联研究问题</option>
                            {questions.map((question) => (
                              <option key={question.id} value={question.id}>
                                {question.question}
                              </option>
                            ))}
                          </select>
                        </label>
                        {projectError && (
                          <p className="text-xs text-[var(--danger)] lg:col-span-2">
                            {projectError}。可清除关联后继续创建任务。
                          </p>
                        )}
                        <label className="space-y-1.5 text-xs font-medium lg:col-span-2">
                          任务说明
                          <Textarea
                            required
                            minLength={10}
                            maxLength={20000}
                            className="min-h-36"
                            value={prompt}
                            onChange={(event) => setPrompt(event.target.value)}
                            placeholder="写明研究问题、允许引用的资料、希望得到的策划或代码建议；实际实验交由课题组服务器。"
                          />
                        </label>
                        <div className="lg:col-span-2 rounded-md border border-[var(--border)] bg-[var(--background)] p-3 text-xs leading-5 text-[var(--muted)]">
                          这里只保存只读策划与代码建议草稿。实际文件应用暂未支持；没有工作区写入或本地实验入口。创建草稿不会调用
                          AI，后续启动仍以服务端真实能力和本人批准为准。
                          {!capabilities?.available &&
                            " 当前通用任务服务不可启动，草稿仍可保存。"}
                          {capabilities && (
                            <p className="mt-2">
                              {capabilities.budget_mode === "PROVIDER_QUOTA"
                                ? "跟随 Codex 账户额度；已报告用量不是剩余额度。"
                                : "启动时使用服务端单任务 Token 上限 " +
                                  (capabilities.max_tokens_per_task?.toLocaleString() ??
                                    "未记录") +
                                  "。"}
                              {capabilities.budget_mode !== "PROVIDER_QUOTA" &&
                                capabilities.token_limit_is_soft &&
                                "这是软上限：用量事件可能滞后，达到阈值时只能请求停止，不能保证精确截断。"}
                            </p>
                          )}
                        </div>
                        <div className="lg:col-span-2">
                          <Button
                            type="submit"
                            disabled={
                              busy ||
                              !canCreate ||
                              !title.trim() ||
                              prompt.trim().length < 10
                            }
                          >
                            {busy ? "创建中…" : "创建任务草稿"}
                          </Button>
                        </div>
                      </form>
                    </CardContent>
                  </Card>
                </>
              )}
            </details>
          )}
        </>
      )}
    </div>
  );
}
