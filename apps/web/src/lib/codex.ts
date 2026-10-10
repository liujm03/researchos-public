import type { components } from "./generated";

export type CodexKind = components["schemas"]["CodexTaskKind"];
export type CodexMode = components["schemas"]["CodexTaskMode"];
export type CodexStatus = components["schemas"]["CodexTaskStatus"];
export type CodexCapabilities = components["schemas"]["CodexCapabilitiesOut"];
export type CodexWorkspace = components["schemas"]["CodexWorkspaceOut"];
export type CodexTask = components["schemas"]["CodexTaskOut"];
export type CodexTaskSummary = components["schemas"]["CodexTaskSummaryOut"];
export type CodexEvent = components["schemas"]["CodexTaskEventOut"];
export type CodexTaskCreate = components["schemas"]["CodexTaskCreate"];
export type CodexStartRequest = components["schemas"]["CodexStartRequest"];

export const codexKindLabels: Record<CodexKind, string> = {
  general: "通用代码任务",
  repository_analysis: "仓库分析",
  code_review: "代码审查",
  bug_fix: "修复缺陷",
  code_change: "修改代码",
  test_generation: "生成测试",
  experiment_script: "实验脚本",
  paper_reproduction: "论文复现准备",
  writing: "专业 Skill 写作",
};

export const codexModeLabels: Record<CodexMode, string> = {
  read_only: "只读分析",
  workspace_write: "工作区写入",
};

export const codexStatusLabels: Record<CodexStatus, string> = {
  DRAFT: "草稿，等待启动",
  QUEUED: "等待执行",
  RUNNING: "执行中",
  COMPLETED: "已完成",
  FAILED: "失败",
  CANCEL_REQUESTED: "正在取消",
  CANCELLED: "已取消",
  NEEDS_ATTENTION: "需要处理",
};

export const runningCodexStatuses: CodexStatus[] = [
  "QUEUED",
  "RUNNING",
  "CANCEL_REQUESTED",
];

export function formatCodexTime(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat("zh-CN", {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(date);
}
