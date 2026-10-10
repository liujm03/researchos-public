import type { components } from "./generated";
import { api, type Page } from "./api";

export type Dataset = components["schemas"]["DatasetOut"];
export type DatasetCreate = components["schemas"]["DatasetCreate"];
export type DatasetPatch = components["schemas"]["DatasetPatch"];
export type DatasetPage = components["schemas"]["DatasetPage"];
export type DatasetVersion = components["schemas"]["DatasetVersionOut"];
export type DatasetVersionCreate =
  components["schemas"]["DatasetVersionCreate"];
export type DatasetVersionPage = components["schemas"]["DatasetVersionPage"];
export type ResearchModel = components["schemas"]["ModelOut"];
export type ModelCreate = components["schemas"]["ModelCreate"];
export type ModelPatch = components["schemas"]["ModelPatch"];
export type ModelPage = components["schemas"]["ModelPage"];
export type ModelVersion = components["schemas"]["ModelVersionOut"];
export type ModelVersionCreate = components["schemas"]["ModelVersionCreate"];
export type ModelVersionPage = components["schemas"]["ModelVersionPage"];
export type CodeRepository = components["schemas"]["CodeRepositoryOut"];
export type CodeRepositoryCreate =
  components["schemas"]["CodeRepositoryCreate"];
export type CodeRepositoryPage = components["schemas"]["CodeRepositoryPage"];
export type Hypothesis = components["schemas"]["HypothesisOut"];
export type HypothesisCreate = components["schemas"]["HypothesisCreate"];
export type HypothesisPatch = components["schemas"]["HypothesisPatch"];
export type HypothesisPage = components["schemas"]["HypothesisPage"];
export type Experiment = components["schemas"]["ExperimentOut"];
export type ExperimentCreate = components["schemas"]["ExperimentCreate"];
export type ExperimentPatch = components["schemas"]["ExperimentPatch"];
export type ExperimentPage = components["schemas"]["ExperimentPage"];
export type ExperimentRun = components["schemas"]["ExperimentRunOut"];
export type ExperimentRunCreate = components["schemas"]["ExperimentRunCreate"];
export type ExperimentRunPatch = components["schemas"]["ExperimentRunPatch"];
export type ExperimentRunPage = components["schemas"]["ExperimentRunPage"];
export type MetricDefinition = components["schemas"]["MetricDefinitionOut"];
export type MetricDefinitionCreate =
  components["schemas"]["MetricDefinitionCreate"];
export type MetricDefinitionPage =
  components["schemas"]["MetricDefinitionPage"];
export type ExperimentMetric = components["schemas"]["ExperimentMetricOut"];
export type MetricPage = components["schemas"]["ExperimentMetricPage"];
export type MetricBatch = components["schemas"]["MetricBatchCreate"];
export type MetricBatchOut = components["schemas"]["MetricBatchOut"];
export type ExperimentArtifact = components["schemas"]["ExperimentArtifactOut"];
export type ArtifactCreate = components["schemas"]["ExperimentArtifactCreate"];
export type ArtifactPage = components["schemas"]["ExperimentArtifactPage"];
export type RunCompareRequest = components["schemas"]["RunComparisonRequest"];
export type ExperimentComparison = components["schemas"]["RunComparisonOut"];
export type ArtifactUploadOut = components["schemas"]["ArtifactUploadOut"];
export type ExperimentStatusEventPage =
  components["schemas"]["ExperimentStatusEventPage"];

export const experimentStatusLabels: Record<string, string> = {
  PLANNED: "计划中",
  RUNNING: "运行中",
  COMPLETED: "已完成",
  FAILED: "失败",
  STOPPED: "已停止",
  ARCHIVED: "已归档",
};
export const experimentStatuses = [
  "PLANNED",
  "RUNNING",
  "COMPLETED",
  "FAILED",
  "STOPPED",
  "ARCHIVED",
] as const;

export function nullableText(value: string): string | null {
  return value.trim() || null;
}
export function nullableNumber(
  value: string,
  label: string,
  integer = false,
): number | null {
  if (!value.trim()) return null;
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || (integer && !Number.isInteger(parsed)))
    throw new Error(label + "需要有效" + (integer ? "整数" : "数值") + "。");
  return parsed;
}
export function requiredInteger(value: string, label: string): number {
  const parsed = nullableNumber(value, label, true);
  if (parsed === null) throw new Error(label + "不能为空。");
  return parsed;
}
export async function registryItems<T>(path: string): Promise<T[]> {
  const rows: T[] = [];
  let offset = 0;
  while (true) {
    const separator = path.includes("?") ? "&" : "?";
    const page = await api.get<Omit<DatasetPage, "items"> & { items: T[] }>(
      path + separator + "limit=100&offset=" + offset,
    );
    rows.push(...page.items);
    if (offset + page.items.length >= page.total) return rows;
    if (page.items.length === 0 || page.limit <= 0)
      throw new Error("分页结果未推进，请刷新后重试。");
    offset += page.limit;
  }
}
export async function projectItems<T>(path: string): Promise<T[]> {
  const rows: T[] = [];
  let cursor: string | null = null;
  do {
    const page: Page<T> = await api.get<Page<T>>(
      path +
        (path.includes("?") ? "&" : "?") +
        "limit=100" +
        (cursor ? "&cursor=" + encodeURIComponent(cursor) : ""),
    );
    rows.push(...page.items);
    if (page.page.next_cursor === cursor && cursor !== null)
      throw new Error("课题分页未推进。");
    cursor = page.page.next_cursor;
  } while (cursor);
  return rows;
}
