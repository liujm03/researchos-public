"use client";
import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { LineChart, PieChart } from "echarts/charts";
import {
  AriaComponent,
  GridComponent,
  GraphicComponent,
  LegendComponent,
  TooltipComponent,
} from "echarts/components";
import { SVGRenderer } from "echarts/renderers";
import type { components } from "@/lib/generated";
echarts.use([
  LineChart,
  PieChart,
  AriaComponent,
  GridComponent,
  GraphicComponent,
  LegendComponent,
  TooltipComponent,
  SVGRenderer,
]);
type Overview = components["schemas"]["DashboardVisualization"];
export const readingLabels: Record<string, string> = {
  unread: "未读",
  skimming: "略读",
  reading: "阅读中",
  deep_reading: "精读中",
  reproducing: "复现研究",
  completed: "完成阅读",
  archived: "已归档",
};
export default function ResearchCharts({ data }: { data: Overview }) {
  const trend = useRef<HTMLDivElement>(null);
  const distribution = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!trend.current || !distribution.current) return;
    const charts = [
      echarts.init(trend.current, undefined, { renderer: "svg" }),
      echarts.init(distribution.current, undefined, { renderer: "svg" }),
    ];
    const common = {
      backgroundColor: "transparent",
      textStyle: { color: "#eeeeee", fontSize: 14 },
      animation: false,
      aria: { enabled: true },
      tooltip: {
        confine: true,
        renderMode: "richText",
        backgroundColor: "#202020",
        borderColor: "#555",
        textStyle: { color: "#fff" },
      },
    };
    charts[0].setOption({
      ...common,
      aria: {
        enabled: true,
        label: { description: "近30天文献入库及任务完成折线图" },
      },
      color: ["#e81400", "#f5f5f5"],
      tooltip: { ...common.tooltip, trigger: "axis" },
      legend: { bottom: 0, textStyle: { color: "#eee", fontSize: 14 } },
      grid: { top: 14, left: 12, right: 18, bottom: 44, containLabel: true },
      xAxis: {
        type: "category",
        boundaryGap: false,
        data: data.activity.map((day) => day.date.slice(5)),
        axisLabel: { color: "#dcdcdc", hideOverlap: true },
        axisLine: { lineStyle: { color: "#666" } },
      },
      yAxis: {
        type: "value",
        minInterval: 1,
        axisLabel: { color: "#ddd" },
        splitLine: { lineStyle: { color: "rgba(255,255,255,.12)" } },
      },
      series: [
        {
          name: "入库文献",
          type: "line",
          data: data.activity.map((day) => day.papers_added),
          showSymbol: false,
          lineStyle: { width: 3 },
          areaStyle: { opacity: 0.12 },
        },
        {
          name: "完成任务",
          type: "line",
          data: data.activity.map((day) => day.tasks_completed),
          showSymbol: false,
          lineStyle: { width: 2, type: "dashed" },
        },
      ],
    });
    charts[1].setOption({
      ...common,
      aria: { enabled: true, label: { description: "当前文献阅读状态环形图" } },
      color: [
        "#555555",
        "#929292",
        "#d1d1d1",
        "#ffc2bb",
        "#bd6259",
        "#e81400",
        "#383838",
      ],
      tooltip: { ...common.tooltip, trigger: "item" },
      series: [
        {
          type: "pie",
          radius: ["52%", "76%"],
          center: ["50%", "47%"],
          label: { show: false },
          emphasis: { scale: false },
          data: Object.entries(data.reading_status_counts).map(
            ([status, value]) => ({
              name: readingLabels[status] ?? status,
              value,
            }),
          ),
        },
      ],
      graphic: [
        {
          type: "text",
          left: "center",
          top: "39%",
          style: {
            text: String(data.papers_total),
            fill: "#fafafa",
            fontSize: 30,
            fontWeight: 600,
          },
        },
        {
          type: "text",
          left: "center",
          top: "55%",
          style: { text: "文献总量", fill: "#ddd", fontSize: 14 },
        },
      ],
    });
    const observer = new ResizeObserver(() =>
      charts.forEach((chart) => chart.resize()),
    );
    observer.observe(trend.current);
    observer.observe(distribution.current);
    return () => {
      observer.disconnect();
      charts.forEach((chart) => chart.dispose());
    };
  }, [data]);
  return (
    <div className="dashboard-chart-grid">
      <section
        className="dashboard-chart-panel"
        aria-label="近30天科研记录趋势"
      >
        <h3 className="text-sm font-semibold">近 30 天 · 科研记录</h3>
        <p className="mt-1 text-xs text-[var(--muted)]">
          文献入库与任务完成，{data.from_date} 至 {data.to_date}
        </p>
        <div
          ref={trend}
          className="dashboard-chart"
          role="img"
          aria-label="近30天文献入库及任务完成折线图"
        />
        {data.activity.every(
          (day) => !day.papers_added && !day.tasks_completed,
        ) && <p className="text-xs">这段时间暂无入库或完成任务记录。</p>}
      </section>
      <section className="dashboard-chart-panel" aria-label="文献阅读状态分布">
        <h3 className="text-sm font-semibold">文献 · 阅读分布</h3>
        <div
          ref={distribution}
          className="dashboard-chart"
          role="img"
          aria-label="当前文献阅读状态环形图"
        />
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
          {Object.entries(data.reading_status_counts).map(([status, count]) => (
            <span key={status}>
              {readingLabels[status] ?? status}{" "}
              <strong className="tabular-nums">{count}</strong>
            </span>
          ))}
        </div>
        {data.papers_total === 0 && (
          <p className="text-xs">导入文献后显示分布。</p>
        )}
      </section>
    </div>
  );
}
