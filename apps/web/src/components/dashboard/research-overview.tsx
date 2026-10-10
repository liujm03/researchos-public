"use client";
import Link from "next/link";
import dynamic from "next/dynamic";
import { useEffect, useRef, useState } from "react";
import {
  BookOpen,
  FileText,
  FolderKanban,
  Lightbulb,
  ListTodo,
  Clock3,
  Maximize2,
  Minimize2,
  RefreshCw,
  Bot,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import type { Dashboard } from "@/lib/api";
const Charts = dynamic(() => import("./research-charts"), {
  ssr: false,
  loading: () => (
    <div className="dashboard-chart-grid" role="status">
      <div className="dashboard-chart-panel h-72">正在加载趋势图…</div>
      <div className="dashboard-chart-panel h-72">正在加载阅读分布…</div>
    </div>
  ),
});
const stages = [
  ["idea", "构思"],
  ["literature_review", "文献"],
  ["problem_definition", "问题"],
  ["baseline", "基线"],
  ["method", "方法"],
  ["experiment", "远端研究"],
  ["ablation", "对照/消融"],
  ["writing", "写作"],
  ["submission", "投稿"],
  ["revision", "修回"],
  ["accepted", "录用"],
] as const;
export function ResearchOverview({
  dashboard,
  refreshing,
  onRefresh,
}: {
  dashboard: Dashboard;
  refreshing: boolean;
  onRefresh: () => void;
}) {
  const root = useRef<HTMLElement>(null);
  const [fullscreen, setFullscreen] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [notice, setNotice] = useState("");
  const data = dashboard.visualization;
  useEffect(() => {
    const changed = () =>
      setFullscreen(document.fullscreenElement === root.current);
    document.addEventListener("fullscreenchange", changed);
    return () => document.removeEventListener("fullscreenchange", changed);
  }, []);
  async function toggleScreen() {
    setNotice("");
    if (document.fullscreenElement === root.current) {
      await document.exitFullscreen();
      return;
    }
    if (expanded) {
      setExpanded(false);
      return;
    }
    try {
      if (!root.current?.requestFullscreen)
        throw new Error("Fullscreen unavailable");
      await root.current.requestFullscreen();
    } catch {
      setExpanded(true);
      setNotice("浏览器未允许全屏，已展开大屏。可再次点击收起。");
    }
  }
  if (!data)
    return (
      <section className="dashboard-overview p-5">
        <p>科研总览暂不可用。</p>
        <Button onClick={onRefresh}>刷新统计</Button>
      </section>
    );
  const metrics = [
    {
      label: "文献库",
      value: data.papers_total,
      unit: "篇",
      href: "/papers",
      icon: BookOpen,
    },
    {
      label: "已有精读笔记",
      value: data.papers_with_notes,
      unit: "篇论文",
      href: "/inbox",
      icon: FileText,
    },
    {
      label: "活跃课题",
      value: data.projects_active,
      unit: "项",
      href: "/projects",
      icon: FolderKanban,
    },
    {
      label: "科研灵感",
      value: data.ideas_total,
      unit: "条",
      href: "/ideas",
      icon: Lightbulb,
    },
    {
      label: "未完成任务",
      value: data.tasks_open,
      unit: "项",
      href: "/tasks",
      icon: ListTodo,
    },
    {
      label: "本周已记录",
      value: (dashboard.research_minutes_week / 60).toFixed(1),
      unit: "小时",
      href: "/journal",
      icon: Clock3,
    },
  ];
  return (
    <section
      ref={root}
      className={`dashboard-overview ${expanded ? "dashboard-overview-expanded" : ""}`}
      aria-label="科研驾驶舱"
    >
      <header className="dashboard-overview-header">
        <div>
          <p className="text-xs tracking-[.18em] text-[var(--accent)]">
            RESEARCH OVERVIEW
          </p>
          <h2 className="mt-1 text-xl font-semibold">科研驾驶舱</h2>
          <p className="mt-1 text-xs text-[var(--muted)]">
            真实记录 · {dashboard.timezone} · 更新于{" "}
            {new Intl.DateTimeFormat("zh-CN", {
              timeZone: dashboard.timezone,
              hour: "2-digit",
              minute: "2-digit",
            }).format(new Date(data.observed_at))}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Link href="/ai-tasks" className="dashboard-ai-state">
            <Bot className="h-4 w-4" />
            AI 进行中 <strong>{data.ai_active}</strong>
            {data.ai_attention > 0 && (
              <span className="text-[var(--danger)]">
                · 需留意 {data.ai_attention}
              </span>
            )}
          </Link>
          <Button
            variant="secondary"
            disabled={refreshing}
            onClick={onRefresh}
            aria-label="刷新科研大屏"
          >
            <RefreshCw className="h-4 w-4" />
            {refreshing ? "刷新中" : "刷新"}
          </Button>
          <Button
            variant="secondary"
            onClick={toggleScreen}
            aria-pressed={fullscreen || expanded}
            aria-label={
              fullscreen || expanded ? "收起科研大屏" : "全屏展示科研大屏"
            }
          >
            {fullscreen || expanded ? (
              <Minimize2 className="h-4 w-4" />
            ) : (
              <Maximize2 className="h-4 w-4" />
            )}
            {fullscreen || expanded ? "收起" : "全屏展示"}
          </Button>
        </div>
      </header>
      {notice && (
        <p role="status" className="px-5 text-xs">
          {notice}
        </p>
      )}
      <div className="dashboard-metrics">
        {metrics.map(({ label, value, unit, href, icon: Icon }) => (
          <Link key={label} href={href} className="dashboard-metric">
            <div className="flex items-center justify-between gap-2 text-xs">
              <span>{label}</span>
              <Icon className="h-4 w-4 text-[var(--accent)]" />
            </div>
            <div className="mt-3 flex items-baseline gap-2">
              <strong className="dashboard-metric-value">{value}</strong>
              <span className="text-xs text-[var(--muted)]">{unit}</span>
            </div>
          </Link>
        ))}
      </div>
      <Charts data={data} />
      <div className="px-4 pb-4 sm:px-5">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-semibold">课题路线 · 当前阶段</h3>
          <Link href="/projects" className="text-xs text-[var(--accent)]">
            查看课题 →
          </Link>
        </div>
        <div className="dashboard-pipeline">
          {stages.map(([key, label]) => (
            <div
              key={key}
              className={`dashboard-stage ${data.project_stage_counts[key] ? "dashboard-stage-active" : ""}`}
            >
              <span className="text-xs">{label}</span>
              <strong className="text-sm tabular-nums">
                {data.project_stage_counts[key] ?? 0}
              </strong>
            </div>
          ))}
        </div>
        {data.projects_active === 0 && (
          <p className="mt-2 text-xs">
            暂无活跃课题。创建课题后，按已记录阶段展示。
          </p>
        )}
      </div>
      <details className="dashboard-stat-details">
        <summary>统计口径与数据</summary>
        <p className="mt-2 text-xs">
          精读覆盖按有可见笔记的论文去重，不重复累计修订版本；阅读状态来自个人记录。入库趋势不代表已读，课题阶段为当前记录，不自动确认科研结论或服务器执行。
        </p>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr>
                <th>日期</th>
                <th>入库文献</th>
                <th>完成任务</th>
              </tr>
            </thead>
            <tbody>
              {data.activity.map((day) => (
                <tr key={day.date}>
                  <td>{day.date}</td>
                  <td>{day.papers_added}</td>
                  <td>{day.tasks_completed}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </section>
  );
}
