"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import * as echarts from "echarts";
import { useTheme } from "next-themes";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { api, type Analytics, type Heatmap } from "@/lib/api";

function isoDay(day: Date) {
  return `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, "0")}-${String(day.getDate()).padStart(2, "0")}`;
}

function TimeChart({ values }: { values: Record<string, number> }) {
  const ref = useRef<HTMLDivElement>(null);
  const { resolvedTheme } = useTheme();
  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current, resolvedTheme === "dark" ? "dark" : undefined, { renderer: "canvas" });
    const entries = Object.entries(values).sort((a, b) => b[1] - a[1]);
    chart.setOption({
      backgroundColor: "transparent",
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, formatter: (params: unknown) => {
        const item = Array.isArray(params) ? params[0] as { name: string; value: number } : null;
        return item ? `${item.name}: ${(item.value / 60).toFixed(1)} 小时` : "";
      } },
      grid: { left: 92, right: 28, top: 12, bottom: 24 },
      xAxis: { type: "value", axisLabel: { formatter: (value: number) => `${(value / 60).toFixed(0)}h` }, splitLine: { lineStyle: { color: resolvedTheme === "dark" ? "#263344" : "#e6ebf0" } } },
      yAxis: { type: "category", inverse: true, data: entries.map(([label]) => label), axisLabel: { color: resolvedTheme === "dark" ? "#91a1b4" : "#66778b" } },
      series: [{ type: "bar", data: entries.map(([, minutes]) => minutes), barWidth: 18, itemStyle: { color: "#4f8cff", borderRadius: [0, 4, 4, 0] } }],
    });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(ref.current);
    return () => { observer.disconnect(); chart.dispose(); };
  }, [values, resolvedTheme]);
  return <div ref={ref} className="h-72 w-full" role="img" aria-label="各类科研活动时长柱状图" />;
}

export default function AnalyticsPage() {
  const [range, setRange] = useState<30 | 90 | 365>(30);
  const [measure, setMeasure] = useState<"hours" | "activity">("hours");
  const [overview, setOverview] = useState<Analytics | null>(null);
  const [heatmap, setHeatmap] = useState<Heatmap | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    const end = new Date();
    const start = new Date(end); start.setDate(end.getDate() - range + 1);
    Promise.all([
      api.get<Analytics>(`/analytics/overview?from=${isoDay(start)}&to=${isoDay(end)}`),
      api.get<Heatmap>(`/analytics/heatmap?year=${end.getFullYear()}&measure=${measure}`),
    ]).then(([overviewResult, heatmapResult]) => { setOverview(overviewResult); setHeatmap(heatmapResult); setError(""); })
      .catch((cause) => setError(cause instanceof Error ? cause.message : "无法加载科研分析"))
      .finally(() => setLoading(false));
  }, [range, measure]);
  useEffect(load, [load]);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3"><div><p className="mb-1 text-xs font-medium uppercase tracking-[0.18em] text-[var(--accent)]">Research analytics</p><h1 className="text-2xl font-semibold">科研分析</h1><p className="mt-1 text-sm text-[var(--muted)]">按真实记录查看时间、阅读和任务进展。</p></div><div className="flex gap-1 rounded-md border border-[var(--border)] bg-[var(--surface)] p-1">{[30, 90, 365].map((days) => <Button key={days} size="sm" variant={range === days ? "default" : "ghost"} onClick={() => setRange(days as 30 | 90 | 365)}>{days} 天</Button>)}</div></div>
      {error && <ErrorState message={error} onRetry={load} />}
      {loading ? <LoadingState /> : overview && heatmap ? <><div className="grid gap-3 sm:grid-cols-3">{[["完成阅读", overview.papers_completed, "篇"], ["完成任务", overview.tasks_completed, "项"], ["活跃课题", overview.projects_active, "个"]].map(([label, value, unit]) => <Card key={label}><CardContent><div className="text-xs text-[var(--muted)]">{label}</div><div className="mt-2 text-2xl font-semibold tabular-nums">{value}<span className="ml-1 text-xs font-normal text-[var(--muted)]">{unit}</span></div></CardContent></Card>)}</div><Card><CardHeader><div><h2 className="font-semibold">科研时间分布</h2><p className="mt-1 text-xs text-[var(--muted)]">{overview.from_date} 至 {overview.to_date}</p></div></CardHeader><CardContent>{Object.keys(overview.research_minutes_by_category).length ? <TimeChart values={overview.research_minutes_by_category} /> : <EmptyState title="还没有科研时间记录" detail="在科研日志中记录时间后，这里会显示活动分布。" />}</CardContent></Card><Card><CardHeader><div><h2 className="font-semibold">{heatmap.year} 年科研热力图</h2><p className="mt-1 text-xs text-[var(--muted)]">{measure === "hours" ? "按每日科研小时" : "按每日活动次数"} · 深色表示投入更多</p></div><select className="h-8 rounded-md border border-[var(--border)] bg-[var(--background)] px-2 text-xs" value={measure} onChange={(event) => setMeasure(event.target.value as "hours" | "activity")}><option value="hours">科研时间</option><option value="activity">科研活动</option></select></CardHeader><CardContent><div className="grid grid-flow-col grid-rows-7 justify-start gap-1 overflow-x-auto pb-2" style={{ gridTemplateColumns: `repeat(${Math.ceil(heatmap.days.length / 7)}, 12px)` }}>{heatmap.days.map((day) => <div key={day.date} title={`${day.date} · ${day.value} ${heatmap.unit}`} className="h-3 w-3 rounded-[2px]" style={{ backgroundColor: ["var(--surface-hover)", "#dbeafe", "#93c5fd", "#60a5fa", "#3b82f6", "#1d4ed8"][day.level] }} />)}</div><div className="mt-3 flex items-center gap-1 text-[10px] text-[var(--muted)]">少 {Array.from({ length: 6 }, (_, index) => <span key={index} className="h-2.5 w-2.5 rounded-[2px]" style={{ backgroundColor: ["var(--surface-hover)", "#dbeafe", "#93c5fd", "#60a5fa", "#3b82f6", "#1d4ed8"][index] }} />)} 多</div></CardContent></Card></> : null}
    </div>
  );
}
