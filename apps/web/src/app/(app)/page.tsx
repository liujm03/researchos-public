"use client";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowRight } from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { api, type Dashboard } from "@/lib/api";
import { formatDate } from "@/lib/utils";
import { ResearchOverview } from "@/components/dashboard/research-overview";

export default function DashboardPage() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const pending = useRef(false);
  const load = useCallback(() => {
    if (pending.current) return;
    pending.current = true;
    setLoading(true);
    setError("");
    api
      .get<Dashboard>("/dashboard")
      .then(setData)
      .catch((cause) =>
        setError(cause instanceof Error ? cause.message : "无法加载首页"),
      )
      .finally(() => {
        pending.current = false;
        setLoading(false);
      });
  }, []);
  useEffect(() => {
    queueMicrotask(load);
  }, [load]);
  if (loading && !data) return <LoadingState label="正在读取近期科研记录…" />;
  if (error && !data) return <ErrorState message={error} onRetry={load} />;
  if (!data) return null;
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">首页</h1>
          <p className="mt-1 text-sm text-[var(--muted)]">
            {data.date} · 继续阅读和推进课题
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link
            href="/integrations/zotero"
            className="rounded-md border border-[var(--border)] px-3 py-2 text-sm"
          >
            浏览 Zotero
          </Link>
          <Link
            href="/inbox"
            className="rounded-md bg-[var(--accent)] px-3 py-2 text-sm text-white"
          >
            查看精读笔记
          </Link>
        </div>
      </div>
      {error && (
        <div
          role="alert"
          className="rounded-lg border border-[var(--border)] p-3 text-sm"
        >
          暂未刷新成功，以下仍为上次数据：{error}
        </div>
      )}
      <ResearchOverview
        dashboard={data}
        refreshing={loading}
        onRefresh={load}
      />
      <div className="grid gap-4 xl:grid-cols-[1.3fr_1fr]">
        <Card>
          <CardHeader>
            <h2 className="font-semibold">最近文献</h2>
            <Link href="/papers" className="text-xs text-[var(--accent)]">
              全部文献 →
            </Link>
          </CardHeader>
          <CardContent className="p-0">
            {data.recent_papers.length ? (
              <div className="divide-y divide-[var(--border)]">
                {data.recent_papers.map((paper) => (
                  <Link
                    key={paper.id}
                    href={`/papers/${paper.id}/analysis`}
                    className="flex items-center justify-between gap-3 px-5 py-4 hover:bg-[var(--surface-hover)]"
                  >
                    <div className="min-w-0">
                      <p className="line-clamp-2 text-sm font-medium">
                        {paper.title}
                      </p>
                      <p className="mt-1 text-xs text-[var(--muted)]">
                        {paper.year ?? "年份未知"} ·{" "}
                        {paper.last_read_at
                          ? `阅读记录：${formatDate(paper.last_read_at)}`
                          : "暂无阅读记录"}
                      </p>
                    </div>
                    <ArrowRight className="h-4 w-4 shrink-0" />
                  </Link>
                ))}
              </div>
            ) : (
              <EmptyState
                title="还没有文献"
                detail="从 Zotero 或文献中心选择第一篇论文。"
              />
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <h2 className="font-semibold">近期课题</h2>
            <Link href="/projects" className="text-xs text-[var(--accent)]">
              全部课题 →
            </Link>
          </CardHeader>
          <CardContent className="p-0">
            {data.current_projects.length ? (
              <div className="divide-y divide-[var(--border)]">
                {data.current_projects.map((project) => (
                  <Link
                    key={project.id}
                    href={`/projects/${project.id}`}
                    className="flex items-center justify-between gap-3 px-5 py-4 text-sm hover:bg-[var(--surface-hover)]"
                  >
                    <span className="truncate font-medium">{project.name}</span>
                    <ArrowRight className="h-4 w-4 shrink-0" />
                  </Link>
                ))}
              </div>
            ) : (
              <EmptyState
                title="还没有活跃课题"
                detail="在研究课题中记录问题和目标。"
              />
            )}
          </CardContent>
        </Card>
      </div>
      {(data.today_tasks.length > 0 ||
        data.tasks_open > 0 ||
        data.research_minutes_week > 0) && (
        <Card>
          <CardHeader>
            <h2 className="font-semibold">今天的任务</h2>
            <Link href="/tasks" className="text-xs text-[var(--accent)]">
              查看任务 →
            </Link>
          </CardHeader>
          <CardContent>
            {data.today_tasks.length ? (
              <ul className="divide-y divide-[var(--border)]">
                {data.today_tasks.map((task) => (
                  <li key={task.id} className="py-2">
                    <Link
                      href="/tasks"
                      className="text-sm hover:text-[var(--accent)]"
                    >
                      {task.title}
                    </Link>
                    <span className="ml-3 text-xs text-[var(--muted)]">
                      {task.status === "done"
                        ? "已完成"
                        : task.status === "blocked"
                          ? "受阻"
                          : task.status === "in_progress"
                            ? "进行中"
                            : "待处理"}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-[var(--muted)]">今天没有截止任务。</p>
            )}
            <div className="mt-4 flex flex-wrap justify-between gap-3 border-t border-[var(--border)] pt-3 text-xs text-[var(--muted)]">
              <span>
                本周已记录科研时间{" "}
                {(data.research_minutes_week / 60).toFixed(1)} 小时 · 待处理任务{" "}
                {data.tasks_open}
              </span>
              <Link href="/journal" className="text-[var(--accent)]">
                记录今天 →
              </Link>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
