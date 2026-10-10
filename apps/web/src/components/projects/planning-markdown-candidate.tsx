"use client";

import { useState } from "react";
import { MarkdownViewer } from "@/components/markdown/markdown-viewer";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState } from "@/components/ui/state";

export function PlanningMarkdownCandidate({
  markdown,
  sha256,
  disposition = "AVAILABLE",
}: {
  markdown: string | null | undefined;
  sha256: string | null | undefined;
  disposition?: "AVAILABLE" | "QUARANTINED";
}) {
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  async function copy() {
    if (!markdown) return;
    setError("");
    setMessage("");
    try {
      await navigator.clipboard.writeText(markdown);
      setMessage(
        disposition === "QUARANTINED"
          ? "已复制隔离保留的原始 Markdown，仅供核对审计。"
          : "已复制原始 Markdown 候选；任务书和人审状态未改变。",
      );
    } catch {
      setError("无法写入剪贴板，请从下方选择并复制原始 Markdown。");
    }
  }
  return (
    <section aria-label="专业技能规划候选" className="space-y-3 text-xs">
      <h3 className="font-semibold">
        {disposition === "QUARANTINED"
          ? "隔离保留的专业技能产物"
          : "专业技能规划候选"}
      </h3>
      <p className="leading-5 text-[var(--muted)]">
        保留原专业 Skill 的完整 Markdown
        输出，供本人核对下一步研究决策；不会自动覆盖任务书或确认科学结论。
      </p>
      {disposition === "QUARANTINED" && (
        <p className="text-[var(--danger)]">
          此结果隔离保留，仅供核对回执和审计，不作为已完成规划或科学证据。
        </p>
      )}
      {markdown ? (
        <>
          <p className="break-all font-mono">
            产物 SHA-256：{sha256 || "未记录"}
          </p>
          <Button size="sm" variant="secondary" onClick={() => void copy()}>
            {disposition === "QUARANTINED"
              ? "复制隔离保留的 Markdown"
              : "复制原始 Markdown 候选"}
          </Button>
          {message && <p role="status">{message}</p>}
          {error && <ErrorState message={error} />}
          <MarkdownViewer
            content={markdown}
            label="规划候选 Markdown"
            showCopy={false}
          />
        </>
      ) : (
        <EmptyState
          title="尚无规划候选产物"
          detail="只有实际返回的专业 Skill 输出会出现在这里。"
        />
      )}
    </section>
  );
}
