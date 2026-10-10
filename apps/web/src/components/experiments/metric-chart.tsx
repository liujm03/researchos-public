"use client";

import { useEffect, useRef } from "react";
import * as echarts from "echarts";
import { useTheme } from "next-themes";

export type MetricSeries = {
  name: string;
  points: [number | string, number | null][];
};

export function MetricChart({
  title,
  unit,
  axisLabel,
  series,
  kind = "line",
}: {
  title: string;
  unit: string | null;
  axisLabel: string;
  series: MetricSeries[];
  kind?: "line" | "bar";
}) {
  const ref = useRef<HTMLDivElement>(null);
  const { resolvedTheme } = useTheme();
  const ariaLabel = `${title}${unit ? `（${unit}）` : ""}${kind === "line" ? "曲线" : "柱状图"}，缺失值不绘制`;

  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(
      ref.current,
      resolvedTheme === "dark" ? "dark" : undefined,
      { renderer: "canvas" },
    );
    const categories =
      kind === "bar"
        ? series[0]?.points.map(([name]) => String(name))
        : undefined;
    chart.setOption({
      backgroundColor: "transparent",
      aria: {
        enabled: true,
        label: { description: ariaLabel },
        decal: { show: true },
      },
      color: ["#2563eb", "#16a34a", "#d97706", "#9333ea", "#dc2626"],
      tooltip: { trigger: "axis", confine: true, renderMode: "richText" },
      legend: { type: "scroll", bottom: 0 },
      grid: { left: 64, right: 24, top: 24, bottom: 76 },
      xAxis: {
        type: kind === "bar" ? "category" : "value",
        data: categories,
        name: axisLabel,
        nameLocation: "middle",
        nameGap: 34,
        axisLabel: { hideOverlap: true },
        minInterval: kind === "line" ? 1 : undefined,
      },
      yAxis: {
        type: "value",
        name: unit || title,
        scale: kind === "line",
        splitLine: {
          lineStyle: {
            color: resolvedTheme === "dark" ? "#263344" : "#e6ebf0",
          },
        },
      },
      series: series.map((item) => ({
        name: item.name,
        type: kind,
        data:
          kind === "bar" ? item.points.map(([, value]) => value) : item.points,
        connectNulls: false,
        showSymbol: true,
        symbolSize: 6,
        smooth: false,
        barMaxWidth: 42,
      })),
    });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(ref.current);
    return () => {
      observer.disconnect();
      chart.dispose();
    };
  }, [title, unit, axisLabel, series, kind, resolvedTheme, ariaLabel]);

  return (
    <div ref={ref} className="h-80 w-full" role="img" aria-label={ariaLabel} />
  );
}
