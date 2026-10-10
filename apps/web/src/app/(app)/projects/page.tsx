"use client";

import Link from "next/link";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { ArrowRight, FolderPlus, Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input, Textarea } from "@/components/ui/input";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { api, type Page, type Project } from "@/lib/api";
import { formatDate } from "@/lib/utils";

const stageLabels: Record<string, string> = {
  idea: "Idea", literature_review: "文献调研", problem_definition: "问题定义",
  baseline: "Baseline", method: "方法设计", experiment: "实验", ablation: "消融实验",
  writing: "论文写作", submission: "投稿", revision: "返修", accepted: "录用",
};

export default function ProjectsPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [problem, setProblem] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api.get<Page<Project>>("/projects?limit=50")
      .then((result) => { setProjects(result.items); setCursor(result.page.next_cursor); setError(""); })
      .catch((cause) => setError(cause instanceof Error ? cause.message : "无法加载课题"))
      .finally(() => setLoading(false));
  }, []);
  useEffect(load, [load]);

  async function create(event: FormEvent) {
    event.preventDefault();
    setBusy(true); setError("");
    try {
      await api.post<Project>("/projects", { name, problem: problem || null });
      setName(""); setProblem(""); setShowForm(false); load();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "创建失败"); }
    finally { setBusy(false); }
  }

  async function loadMore() {
    if (!cursor) return;
    try {
      const result = await api.get<Page<Project>>(`/projects?limit=50&cursor=${encodeURIComponent(cursor)}`);
      setProjects((previous) => [...previous, ...result.items]); setCursor(result.page.next_cursor);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "加载失败"); }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3"><div><p className="mb-1 text-xs font-medium uppercase tracking-[0.18em] text-[var(--accent)]">Research projects</p><h1 className="text-2xl font-semibold">研究课题</h1><p className="mt-1 text-sm text-[var(--muted)]">把研究问题、文献和任务组织在同一条路线中。</p></div><Button onClick={() => setShowForm(!showForm)}><Plus className="h-4 w-4" />新建课题</Button></div>
      {showForm && <Card><CardHeader><h2 className="font-semibold">新建研究课题</h2></CardHeader><CardContent><form onSubmit={create} className="grid gap-4 md:grid-cols-[1fr_1fr_auto]"><label className="space-y-1.5 text-xs font-medium">课题名称<Input required value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：输电线路山火三维感知" /></label><label className="space-y-1.5 text-xs font-medium">研究问题概述<Textarea className="min-h-9" value={problem} onChange={(event) => setProblem(event.target.value)} placeholder="希望解决什么实际问题？" /></label><div className="flex items-end"><Button disabled={busy} type="submit">{busy ? "创建中…" : "创建"}</Button></div></form></CardContent></Card>}
      {error && <ErrorState message={error} onRetry={load} />}
      {loading ? <LoadingState /> : projects.length ? <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{projects.map((project) => <Link key={project.id} href={`/projects/${project.id}`}><Card className="h-full transition-colors hover:border-[var(--accent)]/60 hover:bg-[var(--surface-hover)]"><CardContent className="flex h-full flex-col p-5"><div className="mb-4 flex items-start justify-between gap-3"><div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[var(--accent)]/10 text-[var(--accent)]"><FolderPlus className="h-4 w-4" /></div><span className="rounded-full border border-[var(--border)] px-2 py-0.5 text-[11px] text-[var(--muted)]">{stageLabels[project.pipeline_stage] ?? project.pipeline_stage}</span></div><h2 className="line-clamp-2 text-sm font-semibold leading-6">{project.name}</h2><p className="mt-2 line-clamp-2 min-h-9 text-xs leading-5 text-[var(--muted)]">{project.problem || project.summary || "尚未填写研究问题"}</p><div className="mt-auto flex items-center justify-between border-t border-[var(--border)] pt-4 text-xs text-[var(--muted)]"><span>更新于 {formatDate(project.updated_at)}</span><ArrowRight className="h-4 w-4" /></div></CardContent></Card></Link>)}</div> : <Card><EmptyState title="还没有研究课题" detail="创建第一个课题，开始整理问题与证据。" /></Card>}
      {cursor && <div className="text-center"><Button variant="secondary" onClick={loadMore}>加载更多</Button></div>}
    </div>
  );
}
