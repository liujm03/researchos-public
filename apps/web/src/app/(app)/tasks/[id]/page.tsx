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
import { api, type Task } from "@/lib/api";
import type { components } from "@/lib/generated";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input, Textarea } from "@/components/ui/input";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { MarkdownViewer } from "@/components/markdown/markdown-viewer";
import { formatDate } from "@/lib/utils";

type Patch = components["schemas"]["TaskPatch"];
const statuses: [Task["status"], string][] = [
  ["todo", "待处理"],
  ["in_progress", "进行中"],
  ["blocked", "受阻"],
  ["done", "已完成"],
  ["cancelled", "已取消"],
];
const errorText = (cause: unknown) =>
  cause instanceof Error ? cause.message : "无法读取或更新任务";
export default function TaskDetailPage() {
  const { id } = useParams<{ id: string }>();
  return <TaskDetailWorkspace key={id} id={id} />;
}

function TaskDetailWorkspace({ id }: { id: string }) {
  const [task, setTask] = useState<Task | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [saveError, setSaveError] = useState("");
  const [notice, setNotice] = useState("");
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [status, setStatus] = useState<Task["status"]>("todo");
  const [baseVersion, setBaseVersion] = useState<number | null>(null);
  const operation = useRef(false),
    sequence = useRef(0);
  const read = useCallback(async () => {
    const seq = ++sequence.current;
    setLoading(true);
    setError("");
    try {
      const result = await api.get<Task>(`/tasks/${encodeURIComponent(id)}`);
      if (seq === sequence.current) setTask(result);
    } catch (cause) {
      if (seq === sequence.current) setError(errorText(cause));
    } finally {
      if (seq === sequence.current) setLoading(false);
    }
  }, [id]);
  useEffect(() => {
    void Promise.resolve().then(() => read());
  }, [read]);
  function edit() {
    if (!task) return;
    setTitle(task.title);
    setDescription(task.description ?? "");
    setStatus(task.status);
    setBaseVersion(task.version);
    setEditing(true);
    setSaveError("");
    setNotice("");
  }
  async function save(event: FormEvent) {
    event.preventDefault();
    if (operation.current || baseVersion === null || !title.trim()) return;
    operation.current = true;
    setBusy(true);
    setSaveError("");
    setNotice("");
    const body: Patch = { title, description: description || null, status };
    try {
      const result = await api.patch<Task>(
        `/tasks/${encodeURIComponent(id)}`,
        body,
        baseVersion,
      );
      setTask(result);
      setEditing(false);
      setBaseVersion(null);
      setNotice(`任务已保存 · 版本 ${result.version}`);
    } catch (cause) {
      setSaveError(
        `${errorText(cause)}。输入已保留；请读取最新任务核对，原编辑版本不会自动替换。`,
      );
    } finally {
      operation.current = false;
      setBusy(false);
    }
  }
  if (loading && !task) return <LoadingState label="正在读取具体任务…" />;
  return (
    <div className="space-y-5">
      <Link className="text-sm text-[var(--accent)]" href="/tasks">
        返回科研任务列表
      </Link>
      {error && <ErrorState message={error} onRetry={() => void read()} />}
      {!task ? (
        !error && <EmptyState title="此任务没有可显示的内容" />
      ) : (
        <>
          <Card>
            <CardHeader>
              <div>
                <h1 className="text-xl font-semibold">{task.title}</h1>
                <p className="mt-1 text-xs text-[var(--muted)]">
                  任务 ID · {task.id} · 版本 {task.version}
                </p>
              </div>
              <Button
                variant="secondary"
                size="sm"
                disabled={busy || editing}
                onClick={edit}
              >
                编辑任务
              </Button>
            </CardHeader>
            <CardContent className="space-y-4">
              <p className="text-sm">
                {statuses.find(([value]) => value === task.status)?.[1] ??
                  task.status}{" "}
                · {task.category} · {task.priority}
              </p>
              {task.project_id && (
                <p className="text-sm">
                  <Link
                    className="text-[var(--accent)]"
                    href={`/projects/${task.project_id}`}
                  >
                    查看关联课题
                  </Link>
                </p>
              )}
              {task.description ? (
                <MarkdownViewer label="任务说明" content={task.description} />
              ) : (
                <EmptyState title="尚未填写任务说明" />
              )}
              <p className="text-xs text-[var(--muted)]">
                更新于 {formatDate(task.updated_at)}
                {task.due_at && ` · 截止 ${formatDate(task.due_at)}`}
              </p>
              <p className="text-xs text-[var(--muted)]">
                任务状态是管理记录；保存不会执行代码、AI、实验或仿真。
              </p>
            </CardContent>
          </Card>
          {notice && (
            <p role="status" className="text-sm text-[var(--accent)]">
              {notice}
            </p>
          )}
          {editing && (
            <Card>
              <CardHeader>
                <h2 className="font-semibold">
                  编辑任务 · 基于版本 {baseVersion}
                </h2>
              </CardHeader>
              <CardContent>
                <form onSubmit={save} className="space-y-3">
                  <label className="block space-y-1 text-sm">
                    任务标题
                    <Input
                      required
                      maxLength={320}
                      disabled={busy}
                      value={title}
                      onChange={(event) => setTitle(event.target.value)}
                    />
                  </label>
                  <label className="block space-y-1 text-sm">
                    任务说明（Markdown）
                    <Textarea
                      aria-label="任务说明（Markdown）"
                      disabled={busy}
                      value={description}
                      onChange={(event) => setDescription(event.target.value)}
                    />
                  </label>
                  <label className="block space-y-1 text-sm">
                    任务状态
                    <select
                      aria-label="任务状态"
                      className="h-9 w-full rounded border bg-[var(--background)] px-2"
                      value={status}
                      disabled={busy}
                      onChange={(event) =>
                        setStatus(event.target.value as Task["status"])
                      }
                    >
                      {statuses.map(([value, label]) => (
                        <option value={value} key={value}>
                          {label}
                        </option>
                      ))}
                    </select>
                  </label>
                  {saveError && <ErrorState message={saveError} />}
                  <div className="flex flex-wrap gap-2">
                    <Button type="submit" disabled={busy || !title.trim()}>
                      {busy ? "保存中…" : "保存任务修改"}
                    </Button>
                    <Button
                      type="button"
                      variant="secondary"
                      disabled={busy || loading}
                      onClick={() => void read()}
                    >
                      读取最新任务（保留输入）
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      disabled={busy}
                      onClick={() => setEditing(false)}
                    >
                      取消编辑
                    </Button>
                  </div>
                </form>
              </CardContent>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
