"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { CalendarClock, LayoutGrid, List, Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input, Textarea } from "@/components/ui/input";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { api, type Page, type Project, type Task } from "@/lib/api";
import { formatDate } from "@/lib/utils";

const columns = [
  { key: "todo", label: "待处理", color: "#94a3b8" },
  { key: "in_progress", label: "进行中", color: "#3b82f6" },
  { key: "blocked", label: "受阻", color: "#ef6b6b" },
  { key: "done", label: "已完成", color: "#22c55e" },
] as const;

const categories = ["reading", "learning", "coding", "experiment", "dataset", "writing", "meeting", "research", "other"];

export default function TasksPage() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [view, setView] = useState<"list" | "board">("list");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState("research");
  const [priority, setPriority] = useState("medium");
  const [projectId, setProjectId] = useState("");
  const [dueAt, setDueAt] = useState("");

  const load = useCallback(() => {
    Promise.all([api.get<Page<Task>>("/tasks?limit=100"), api.get<Page<Project>>("/projects?limit=100")])
      .then(([taskResult, projectResult]) => { setTasks(taskResult.items); setCursor(taskResult.page.next_cursor); setProjects(projectResult.items); setError(""); })
      .catch((cause) => setError(cause instanceof Error ? cause.message : "无法加载任务"))
      .finally(() => setLoading(false));
  }, []);
  useEffect(load, [load]);

  async function create(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      await api.post<Task>("/tasks", {
        title, description: description || null, category, priority,
        project_id: projectId || null, due_at: dueAt ? new Date(dueAt).toISOString() : null,
      });
      setTitle(""); setDescription(""); setDueAt(""); setShowForm(false); load();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "任务创建失败"); }
    finally { setBusy(false); }
  }

  async function move(task: Task, status: Task["status"]) {
    setError("");
    try {
      const updated = await api.patch<Task>(`/tasks/${task.id}`, { status }, task.version);
      setTasks((previous) => previous.map((item) => item.id === task.id ? updated : item));
    } catch (cause) { setError(cause instanceof Error ? cause.message : "状态更新失败"); }
  }

  async function loadMore() {
    if (!cursor) return;
    try {
      const result = await api.get<Page<Task>>(`/tasks?limit=100&cursor=${encodeURIComponent(cursor)}`);
      setTasks((previous) => [...previous, ...result.items]); setCursor(result.page.next_cursor);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "加载失败"); }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3"><div><p className="mb-1 text-xs font-medium uppercase tracking-[0.18em] text-[var(--accent)]">Research tasks</p><h1 className="text-2xl font-semibold">科研任务</h1><p className="mt-1 text-sm text-[var(--muted)]">阅读、编码、实验与写作，共用一套任务状态。</p></div><div className="flex gap-2"><div className="flex rounded-md border border-[var(--border)] bg-[var(--surface)] p-0.5"><Button variant={view === "list" ? "secondary" : "ghost"} size="icon" aria-label="列表视图" onClick={() => setView("list")}><List className="h-4 w-4" /></Button><Button variant={view === "board" ? "secondary" : "ghost"} size="icon" aria-label="看板视图" onClick={() => setView("board")}><LayoutGrid className="h-4 w-4" /></Button></div><Button onClick={() => setShowForm(!showForm)}><Plus className="h-4 w-4" />新建任务</Button></div></div>
      {showForm && <Card><CardHeader><h2 className="font-semibold">新建任务</h2></CardHeader><CardContent><form onSubmit={create} className="grid gap-4 md:grid-cols-3"><label className="space-y-1.5 text-xs font-medium md:col-span-2">任务标题<Input required value={title} onChange={(event) => setTitle(event.target.value)} placeholder="例如：完成 YOLO baseline 复现" /></label><label className="space-y-1.5 text-xs font-medium">截止时间<Input type="datetime-local" value={dueAt} onChange={(event) => setDueAt(event.target.value)} /></label><label className="space-y-1.5 text-xs font-medium">类别<select className="h-9 w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-3 text-sm" value={category} onChange={(event) => setCategory(event.target.value)}>{categories.map((item) => <option key={item} value={item}>{item}</option>)}</select></label><label className="space-y-1.5 text-xs font-medium">优先级<select className="h-9 w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-3 text-sm" value={priority} onChange={(event) => setPriority(event.target.value)}>{["low", "medium", "high", "urgent"].map((item) => <option key={item} value={item}>{item}</option>)}</select></label><label className="space-y-1.5 text-xs font-medium">课题<select className="h-9 w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-3 text-sm" value={projectId} onChange={(event) => setProjectId(event.target.value)}><option value="">不关联课题</option>{projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label><label className="space-y-1.5 text-xs font-medium md:col-span-3">说明<Textarea value={description} onChange={(event) => setDescription(event.target.value)} placeholder="验收标准或下一步" /></label><div className="md:col-span-3"><Button type="submit" disabled={busy}>{busy ? "创建中…" : "创建任务"}</Button></div></form></CardContent></Card>}
      {error && <ErrorState message={error} onRetry={load} />}
      {loading ? <LoadingState /> : tasks.length === 0 ? <Card><EmptyState title="还没有任务" detail="创建一项具体的科研行动。" /></Card> : view === "list" ? <Card><div className="divide-y divide-[var(--border)]">{tasks.map((task) => <div key={task.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3"><div className="min-w-0"><div className={`text-sm font-medium ${task.status === "done" ? "text-[var(--muted)] line-through" : ""}`}>{task.title}</div><div className="mt-1 flex items-center gap-3 text-xs text-[var(--muted)]"><span>{task.category}</span><span>{task.priority}</span>{task.due_at && <span className="inline-flex items-center gap-1"><CalendarClock className="h-3 w-3" />{formatDate(task.due_at)}</span>}</div></div><select aria-label={`${task.title} 状态`} value={task.status} onChange={(event) => move(task, event.target.value as Task["status"])} className="h-8 rounded-md border border-[var(--border)] bg-[var(--background)] px-2 text-xs">{columns.map((column) => <option key={column.key} value={column.key}>{column.label}</option>)}<option value="cancelled">已取消</option></select></div>)}</div></Card> : <div className="grid gap-3 lg:grid-cols-4">{columns.map((column) => <Card key={column.key} className="min-h-72"><CardHeader><div className="flex items-center gap-2 text-sm font-semibold"><span className="h-2 w-2 rounded-full" style={{ background: column.color }} />{column.label}</div><span className="text-xs text-[var(--muted)]">{tasks.filter((task) => task.status === column.key).length}</span></CardHeader><CardContent className="space-y-2 p-3">{tasks.filter((task) => task.status === column.key).map((task) => <div key={task.id} className="rounded-lg border border-[var(--border)] bg-[var(--background)] p-3"><div className="text-sm font-medium">{task.title}</div><div className="mt-2 text-xs text-[var(--muted)]">{task.category} · {task.priority}</div><select aria-label={`${task.title} 移动到`} value={task.status} onChange={(event) => move(task, event.target.value as Task["status"])} className="mt-3 h-8 w-full rounded-md border border-[var(--border)] bg-[var(--surface)] px-2 text-xs">{columns.map((destination) => <option key={destination.key} value={destination.key}>{destination.label}</option>)}</select></div>)}{tasks.filter((task) => task.status === column.key).length === 0 && <p className="px-2 py-4 text-center text-xs text-[var(--muted)]">暂无任务</p>}</CardContent></Card>)}</div>}
      {cursor && <div className="text-center"><Button variant="secondary" onClick={loadMore}>加载更多</Button></div>}
    </div>
  );
}
