import type { ReviewAction } from "@/lib/api";

const labels: Record<string, string> = {
  analytical_note: "精读正文",
  problem_source: "问题来源",
  research_gap: "研究缺口",
  research_question: "研究问题",
  motivation: "方法动机",
  contributions: "主要贡献",
  method_overview: "方法总览",
  architecture: "模型结构",
  dataset: "数据集",
  experiments: "实验分析",
  results: "结果分析",
  limitations: "局限",
  reproduction: "复现",
  research_inspiration: "科研启发",
};
export const feedbackLabel = (key: string) => labels[key] ?? "笔记内容";
export type PendingFeedback = {
  ownerId: string;
  noteId: string;
  paperId: string;
  revision: number;
  sectionKey: string;
  priorReviewIds: ReviewAction["id"][];
  body: {
    action: "COMMENT" | "EDIT";
    comment: string | null;
    edited_body_markdown: string | null;
  };
};
const key = (owner: string, note: string) =>
  `researchos:note-feedback:${owner}:${note}`;
export function loadPending(
  owner: string,
  note: string,
): PendingFeedback | null {
  try {
    const stored = localStorage.getItem(key(owner, note));
    if (!stored) return null;
    const value = JSON.parse(stored) as Partial<PendingFeedback>;
    return value.ownerId === owner &&
      value.noteId === note &&
      typeof value.paperId === "string" &&
      typeof value.sectionKey === "string" &&
      typeof value.revision === "number" &&
      Array.isArray(value.priorReviewIds) &&
      value.priorReviewIds.every((id) => typeof id === "string") &&
      ["COMMENT", "EDIT"].includes(value.body?.action ?? "") &&
      (value.body?.comment === null ||
        typeof value.body?.comment === "string") &&
      (value.body?.edited_body_markdown === null ||
        typeof value.body?.edited_body_markdown === "string")
      ? (value as PendingFeedback)
      : null;
  } catch {
    return null;
  }
}
export function savePending(
  owner: string,
  note: string,
  value: PendingFeedback | null,
) {
  if (value) localStorage.setItem(key(owner, note), JSON.stringify(value));
  else localStorage.removeItem(key(owner, note));
}
