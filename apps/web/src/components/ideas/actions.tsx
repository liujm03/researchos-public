"use client";
import Link from "next/link";
import { useRef, useState } from "react";
import { api, type Project } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";
import { ErrorState } from "@/components/ui/state";
import { MarkdownViewer } from "@/components/markdown/markdown-viewer";
import { useActionRecovery, type ActionKind } from "./use-action-recovery";
import { briefSections } from "@/components/projects/research-brief-editor";
import {
  errorText,
  type Idea,
  type BriefPreview,
  type BriefPreviewCreate,
  type BriefCreate,
  type BriefReceipt,
  type TaskCreate,
  type TaskReceipt,
} from "./types";

export function IdeaActions({
  idea,
  projects,
  onRefresh,
}: {
  idea: Idea;
  projects: Project[];
  onRefresh: () => Promise<void>;
}) {
  const operation = useRef(false);
  const revision = idea.current;
  const recovery = useActionRecovery(idea.id);
  const [checkedMissing, setCheckedMissing] = useState<
    Partial<Record<ActionKind, boolean>>
  >({});
  const [recoveryNotice, setRecoveryNotice] = useState("");
  const [taskTitle, setTaskTitle] = useState(revision.title);
  const [description, setDescription] = useState(
    revision.next_experiment ?? revision.content ?? "",
  );
  const [taskProject, setTaskProject] = useState(idea.project_id ?? "");
  const [category, setCategory] =
    useState<NonNullable<TaskCreate["category"]>>("research");
  const [target, setTarget] = useState(idea.project_id ?? "");
  const [selected, setSelected] = useState<BriefPreviewCreate["sections"]>([
    "intent",
    "hypotheses",
    "routes",
  ]);
  const [preview, setPreview] = useState<BriefPreview | null>(null);
  const [approval, setApproval] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [task, setTask] = useState<TaskReceipt | null>(null);
  const [brief, setBrief] = useState<BriefReceipt | null>(null);
  async function lookupAction(kind: ActionKind) {
    const record = recovery.pending[kind];
    if (!record || busy) return;
    if (operation.current) return;
    operation.current = true;
    setBusy(true);
    setError("");
    setRecoveryNotice("");
    try {
      const detail = await api.get<Idea>(`/ideas/${idea.id}`);
      const key = record.body.idempotency_key;
      if (kind === "task") {
        const receipt = detail.task_actions.find(
          (row) => row.idempotency_key === key,
        );
        if (receipt) {
          setTask(receipt);
          recovery.clear(kind);
          setRecoveryNotice("已核查原待办已创建，未重复提交。");
        } else {
          setCheckedMissing((current) => ({ ...current, [kind]: true }));
          setRecoveryNotice(
            "核查时未发现原待办回执；可手动恢复相同请求，或明确放弃。原在途请求仍可能稍后完成。",
          );
        }
      } else {
        const receipt = detail.brief_actions.find(
          (row) => row.idempotency_key === key,
        );
        if (receipt) {
          setBrief(receipt);
          recovery.clear(kind);
          setRecoveryNotice("已核查原任务书草稿已保存，未重复提交。");
        } else {
          setCheckedMissing((current) => ({ ...current, [kind]: true }));
          setRecoveryNotice(
            "核查时未发现原草稿回执；可手动恢复相同请求，或明确放弃。原在途请求仍可能稍后完成。",
          );
        }
      }
    } catch (cause) {
      setError(`只读核查失败：${errorText(cause)}；未重发请求。`);
    } finally {
      operation.current = false;
      setBusy(false);
    }
  }
  async function restoreAction(kind: ActionKind) {
    const record = recovery.pending[kind];
    if (!record || busy) return;
    if (operation.current) return;
    operation.current = true;
    setBusy(true);
    setError("");
    try {
      if (kind === "task")
        setTask(
          await api.post<TaskReceipt>(`/ideas/${idea.id}/tasks`, record.body),
        );
      else
        setBrief(
          await api.post<BriefReceipt>(`/ideas/${idea.id}/briefs`, record.body),
        );
      recovery.clear(kind);
      setRecoveryNotice(
        kind === "task"
          ? "原待办请求已恢复，沿用同一操作键。"
          : "原任务书草稿请求已恢复，沿用同一操作键。",
      );
      try {
        await onRefresh();
      } catch {
        setError("原动作已恢复，列表刷新失败；请只读核查，不要重新创建。");
      }
    } catch (cause) {
      setError(`恢复失败：${errorText(cause)}；仍保留原输入与操作键。`);
    } finally {
      operation.current = false;
      setBusy(false);
    }
  }
  async function createTask() {
    if (busy || task || recovery.pending.task || !taskTitle.trim()) return;
    if (operation.current) return;
    operation.current = true;
    setBusy(true);
    setError("");
    const body: TaskCreate = {
      expected_revision_sha256: revision.sha256,
      title: taskTitle,
      description: description || null,
      category,
      project_id: taskProject || null,
      idempotency_key: "",
    };
    try {
      const frozen = recovery.freeze("task", body);
      setTask(await api.post<TaskReceipt>(`/ideas/${idea.id}/tasks`, frozen));
      recovery.clear("task");
      try {
        await onRefresh();
      } catch {
        setError("待办已创建，关联列表刷新失败；请刷新查看，不要重新创建。");
      }
    } catch (cause) {
      setError(
        `${errorText(cause)}；如调用结果未知，保留相同输入重试会沿用本次操作标识。`,
      );
    } finally {
      operation.current = false;
      setBusy(false);
    }
  }
  async function loadPreview() {
    if (busy || recovery.pending.brief || !target || !selected?.length) return;
    if (operation.current) return;
    operation.current = true;
    setBusy(true);
    setError("");
    setPreview(null);
    setApproval(false);
    const body: BriefPreviewCreate = {
      expected_revision_sha256: revision.sha256,
      target_project_id: target,
      sections: selected,
    };
    try {
      setPreview(
        await api.post<BriefPreview>(`/ideas/${idea.id}/brief-preview`, body),
      );
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      operation.current = false;
      setBusy(false);
    }
  }
  async function createBrief() {
    if (!preview || !approval || busy || brief || recovery.pending.brief)
      return;
    if (operation.current) return;
    operation.current = true;
    setBusy(true);
    setError("");
    const body: BriefCreate = {
      expected_revision_sha256: revision.sha256,
      target_project_id: preview.target_project_id,
      sections: selected,
      expected_preview_sha256: preview.preview_sha256,
      idempotency_key: "",
    };
    try {
      const frozen = recovery.freeze("brief", body);
      setBrief(
        await api.post<BriefReceipt>(`/ideas/${idea.id}/briefs`, frozen),
      );
      recovery.clear("brief");
      setApproval(false);
      try {
        await onRefresh();
      } catch {
        setError(
          "任务书草稿已保存，关联列表刷新失败；请刷新查看，不要重新创建。",
        );
      }
    } catch (cause) {
      setError(`${errorText(cause)}；输入已保留，未知结果请先核查动作记录。`);
    } finally {
      operation.current = false;
      setBusy(false);
    }
  }
  function resetPreview() {
    setPreview(null);
    setApproval(false);
  }
  const valid = revision.integrity_valid && revision.context_current;
  return (
    <section aria-label="灵感转化" className="space-y-4 border-t pt-4">
      <h3 className="font-medium">将灵感推进为任务或任务书</h3>
      {!valid && (
        <p role="alert" className="text-sm text-[var(--danger)]">
          当前版本或源笔记已经变化，请核对并保存有效新版本后转化。
        </p>
      )}
      {error && <ErrorState message={error} />}
      {recovery.warning && (
        <p role="alert" className="text-sm text-[var(--danger)]">
          {recovery.warning}
        </p>
      )}
      {recoveryNotice && (
        <p role="status" className="text-sm text-[var(--accent)]">
          {recoveryNotice}
        </p>
      )}
      {(["task", "brief"] as const).map(
        (kind) =>
          recovery.pending[kind] && (
            <section
              key={kind}
              aria-label={kind === "task" ? "待核查待办请求" : "待核查草稿请求"}
              className="space-y-2 rounded border p-3 text-sm"
            >
              <p>
                {kind === "task" ? "原待办" : "原任务书草稿"}
                输入与操作键已冻结；刷新不会自动提交。
              </p>
              <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-words text-xs">
                {JSON.stringify(recovery.pending[kind]?.body, null, 2)}
              </pre>
              <div className="flex flex-wrap gap-2">
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={busy}
                  onClick={() => void lookupAction(kind)}
                >
                  {kind === "task" ? "核查原待办请求" : "核查原草稿请求"}
                </Button>
                <Button
                  size="sm"
                  disabled={busy}
                  onClick={() => void restoreAction(kind)}
                >
                  {kind === "task" ? "恢复原待办请求" : "恢复原草稿请求"}
                </Button>
                {checkedMissing[kind] && (
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={busy}
                    onClick={() => {
                      recovery.clear(kind);
                      setCheckedMissing((current) => ({
                        ...current,
                        [kind]: false,
                      }));
                      setRecoveryNotice(
                        "本人已放弃原请求。若旧请求稍后完成，仍保留其真实回执供核查。",
                      );
                    }}
                  >
                    {kind === "task"
                      ? "明确放弃原待办请求"
                      : "明确放弃原草稿请求"}
                  </Button>
                )}
              </div>
            </section>
          ),
      )}
      <details>
        <summary className="cursor-pointer text-sm">创建科研待办任务</summary>
        <div className="mt-3 space-y-3">
          <label className="block space-y-1 text-sm">
            任务标题
            <Input
              value={taskTitle}
              maxLength={320}
              disabled={busy}
              onChange={(event) => setTaskTitle(event.target.value)}
            />
          </label>
          <label className="block space-y-1 text-sm">
            任务说明
            <Textarea
              value={description}
              maxLength={40000}
              disabled={busy}
              onChange={(event) => setDescription(event.target.value)}
            />
          </label>
          <label className="block space-y-1 text-sm">
            任务课题
            <select
              aria-label="任务课题"
              className="h-9 w-full rounded border bg-[var(--background)] px-2"
              value={taskProject}
              disabled={busy}
              onChange={(event) => setTaskProject(event.target.value)}
            >
              <option value="">不关联课题</option>
              {projects.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ))}
            </select>
          </label>
          <label className="block space-y-1 text-sm">
            任务类别
            <select
              aria-label="任务类别"
              className="h-9 w-full rounded border bg-[var(--background)] px-2"
              value={category}
              disabled={busy}
              onChange={(event) =>
                setCategory(event.target.value as typeof category)
              }
            >
              <option value="research">科研策划</option>
              <option value="reading">文献阅读</option>
              <option value="coding">代码改进</option>
              <option value="experiment">服务器验证计划</option>
            </select>
          </label>
          <Button
            type="button"
            disabled={
              busy ||
              !recovery.ready ||
              !!recovery.pending.task ||
              !!task ||
              !valid ||
              !taskTitle.trim()
            }
            onClick={() => void createTask()}
          >
            创建待办任务
          </Button>
          <p className="text-xs text-[var(--muted)]">
            只创建 todo 与原灵感版本关联，不启动科研执行或 AI。
          </p>
          {task && (
            <p role="status" className="text-sm">
              待办已创建 ·{" "}
              <Link
                className="text-[var(--accent)]"
                href={`/tasks/${task.task_id}`}
              >
                查看科研任务
              </Link>
            </p>
          )}
        </div>
      </details>
      <details>
        <summary className="cursor-pointer text-sm">形成研究任务书草稿</summary>
        <div className="mt-3 space-y-3">
          <label className="block space-y-1 text-sm">
            目标课题
            <select
              aria-label="任务书目标课题"
              className="h-9 w-full rounded border bg-[var(--background)] px-2"
              value={target}
              disabled={busy}
              onChange={(event) => {
                setTarget(event.target.value);
                resetPreview();
              }}
            >
              <option value="">选择目标课题</option>
              {projects.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ))}
            </select>
          </label>
          <fieldset disabled={busy} className="flex flex-wrap gap-3">
            <legend className="mb-2 text-sm">选择写入任务书的段落</legend>
            {briefSections.map(([key, label]) => (
              <label className="flex items-center gap-2 text-xs" key={key}>
                <input
                  type="checkbox"
                  checked={selected?.includes(key) ?? false}
                  onChange={(event) => {
                    setSelected(
                      event.target.checked
                        ? [...(selected ?? []), key]
                        : selected?.filter((value) => value !== key),
                    );
                    resetPreview();
                  }}
                />
                {label}
              </label>
            ))}
          </fieldset>
          <Button
            type="button"
            variant="secondary"
            disabled={
              busy ||
              !recovery.ready ||
              !!recovery.pending.brief ||
              !valid ||
              !target ||
              !selected?.length
            }
            onClick={() => void loadPreview()}
          >
            预览任务书草稿
          </Button>
          {preview && (
            <section
              aria-label="灵感任务书预览"
              className="space-y-3 rounded border p-3 text-sm"
            >
              <p>
                目标：
                {projects.find(
                  (project) => project.id === preview.target_project_id,
                )?.name ?? preview.target_project_id}{" "}
                · 草稿来源：灵感版本 {revision.revision}
              </p>
              <p>
                当前任务书：
                {preview.base_brief_id
                  ? `沿用 ${preview.base_brief_id}`
                  : "将创建首份草稿"}
              </p>
              {preview.sections.map((section) => (
                <div key={section.key}>
                  <h4 className="font-medium">
                    {briefSections.find(([key]) => key === section.key)?.[1] ??
                      section.key}
                  </h4>
                  <MarkdownViewer
                    content={section.content ?? ""}
                    label={`草稿${section.key}`}
                  />
                </div>
              ))}
              <details>
                <summary className="cursor-pointer text-xs">
                  核对原灵感与笔记来源快照
                </summary>
                <pre className="overflow-auto whitespace-pre-wrap break-words text-xs">
                  {JSON.stringify(preview.source_snapshot, null, 2)}
                </pre>
              </details>
              <p className="break-all text-xs text-[var(--muted)]">
                预览 SHA · {preview.preview_sha256}
              </p>
              <label className="flex gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={approval}
                  disabled={busy}
                  onChange={(event) => setApproval(event.target.checked)}
                />
                我已核对目标课题与所选段落，确认保存 DRAFT
              </label>
              <Button
                type="button"
                disabled={
                  busy ||
                  !recovery.ready ||
                  !!recovery.pending.brief ||
                  !!brief ||
                  !approval ||
                  !valid
                }
                onClick={() => void createBrief()}
              >
                确认保存任务书草稿
              </Button>
            </section>
          )}
          {brief && (
            <p role="status" className="text-sm">
              任务书草稿已保存 ·{" "}
              <Link
                className="text-[var(--accent)]"
                href={`/projects/${brief.project_id}/brief?version=${brief.brief_id}`}
              >
                查看并审阅任务书
              </Link>
            </p>
          )}
        </div>
      </details>
    </section>
  );
}
