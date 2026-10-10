import type { components } from "@/lib/generated";
export type Idea = components["schemas"]["IdeaOut"];
export type Revision = components["schemas"]["IdeaRevisionOut"];
export type IdeaPage = components["schemas"]["IdeaPage"];
export type RevisionPage = components["schemas"]["IdeaRevisionPage"];
export type Fields = Omit<
  components["schemas"]["IdeaCreate"],
  "project_id" | "sources" | "idempotency_key"
>;
export type Source = components["schemas"]["IdeaSourceSelection"];
export type Create = components["schemas"]["IdeaCreate"];
export type Revise = components["schemas"]["IdeaRevise"];
export type BriefPreview = components["schemas"]["IdeaBriefPreviewOut"];
export type BriefCreate = components["schemas"]["IdeaBriefCreate"];
export type BriefPreviewCreate =
  components["schemas"]["IdeaBriefPreviewCreate"];
export type BriefReceipt = components["schemas"]["IdeaBriefReceipt"];
export type TaskCreate = components["schemas"]["IdeaTaskCreate"];
export type TaskReceipt = components["schemas"]["IdeaTaskReceipt"];
export const statuses = [
  ["INBOX", "待整理"],
  ["EVALUATING", "评估中"],
  ["PROMISING", "值得推进"],
  ["EXPERIMENTING", "服务器验证中"],
  ["VALIDATED", "本人判定已验证"],
  ["REJECTED", "暂不采用"],
  ["PAPER_CANDIDATE", "论文候选"],
] as const;
export const statusLabel = (value: string | undefined) =>
  statuses.find(([key]) => key === value)?.[1] ?? value ?? "待整理";
export const detailFields = [
  ["problem", "研究问题"],
  ["hypothesis", "假设"],
  ["method", "可能的方法"],
  ["contribution", "预期贡献"],
  ["difficulty", "难度判断"],
  ["novelty", "新颖性判断"],
  ["feasibility", "可行性判断"],
  ["required_dataset", "需要的数据"],
  ["required_hardware", "服务器与硬件需求"],
  ["next_experiment", "下一步验证计划"],
  ["review_note", "本人决策与理由"],
] as const;
export type DetailKey = (typeof detailFields)[number][0];
export const errorText = (cause: unknown) =>
  cause instanceof Error ? cause.message : "操作失败，请核查后重试";
