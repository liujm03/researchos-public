"use client";

import { useState } from "react";
import Link from "next/link";
import { MarkdownContent } from "@/components/markdown/markdown-content";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Textarea } from "@/components/ui/input";
import { briefSections } from "./research-brief-editor";
import type { components } from "@/lib/generated";

type Detail = components["schemas"]["ResearchBriefDetailOut"];
type Review = components["schemas"]["ResearchBriefReviewCreate"];
export function ResearchBriefDetail({
  detail,
  busy,
  onEdit,
  onReview,
  onRefresh,
}: {
  detail: Detail;
  busy: boolean;
  onEdit: (detail: Detail) => void;
  onReview: (body: Review) => Promise<void>;
  onRefresh: () => void;
}) {
  const [comment, setComment] = useState("");
  const labels: Record<string, string> = {
    DRAFT: "草稿",
    ACCEPTED: "已接受",
    REJECTED: "已拒绝",
  };
  return (
    <Card>
      <CardHeader>
        <h2 className="font-semibold">
          任务书版本 {detail.revision} ·{" "}
          {labels[detail.status] || detail.status}
        </h2>
        <Button
          size="sm"
          variant="secondary"
          disabled={busy}
          onClick={onRefresh}
        >
          刷新版本上下文
        </Button>
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        <MarkdownContent content={detail.idea} />
        <dl className="grid gap-2 text-xs sm:grid-cols-2">
          <div>
            <dt className="text-[var(--muted)]">版本 ID</dt>
            <dd className="break-all font-mono">{detail.id}</dd>
          </div>
          <div>
            <dt className="text-[var(--muted)]">冻结项目版本</dt>
            <dd>{detail.project_version}</dd>
          </div>
          <div className="sm:col-span-2">
            <dt className="text-[var(--muted)]">任务书 SHA-256</dt>
            <dd className="break-all font-mono">{detail.sha256}</dd>
          </div>
          <div>
            <dt className="text-[var(--muted)]">继承版本 ID</dt>
            <dd className="break-all font-mono">
              {detail.base_brief_id || "首版草稿"}
            </dd>
          </div>
          <div>
            <dt className="text-[var(--muted)]">创建时间</dt>
            <dd>{new Date(detail.created_at).toLocaleString("zh-CN")}</dd>
          </div>
        </dl>
        <p
          className={`rounded border border-[var(--border)] p-3 text-xs ${detail.context_current ? "text-[var(--muted)]" : "text-[var(--danger)]"}`}
        >
          {detail.context_current
            ? "冻结上下文仍与当前项目及所选文献一致。"
            : "项目或文献上下文已变化；历史内容与审阅保留，请生成修订并核对当前来源。"}
        </p>
        <p className="rounded bg-[var(--surface)] p-3 text-xs leading-5">
          执行授权：未授予。接受任务书只记录本版本的研究决策，不批准模型调用、代码执行或训练。
        </p>
        <section aria-label="任务书八部分" className="space-y-2">
          {briefSections.map(([key, title]) => {
            const section = detail.sections.find((item) => item.key === key);
            return (
              <details
                key={key}
                className="rounded border border-[var(--border)]"
              >
                <summary className="cursor-pointer px-3 py-2 text-sm">
                  {title} · {section?.content ? "有内容" : "尚未填写"}
                </summary>
                <div className="space-y-2 border-t border-[var(--border)] p-3 text-xs">
                  <p className="text-[var(--muted)]">
                    来源：{section?.origin_type || "MISSING"}
                  </p>
                  {section?.origin_type === "AI_INFERRED" && (
                    <p className="text-[var(--muted)]">
                      此段为规划原文中的 AI
                      建议，不是论文作者事实、实测结果或已经验证的科研结论。
                    </p>
                  )}
                  {section?.source_planning_job_id && (
                    <div className="space-y-1">
                      <Link
                        className="break-all text-[var(--accent)] underline"
                        href={`/projects/${detail.project_id}/planning?job=${section.source_planning_job_id}`}
                      >
                        核对来源规划任务 {section.source_planning_job_id}
                      </Link>
                      <p className="break-all font-mono">
                        来源原产物 SHA-256：
                        {section.source_result_sha256 || "未记录"}
                      </p>
                    </div>
                  )}
                  {section?.uncertainty && (
                    <p className="text-[var(--muted)]">
                      未确定内容标记：{String(section.uncertainty)}
                    </p>
                  )}
                  <MarkdownContent
                    content={section?.content || "当前版本没有这部分内容。"}
                  />
                  {section?.origin_type === "PROJECT_CONTEXT" && (
                    <p className="text-[var(--muted)]">
                      项目字段候选，需要核对；未由精读或实验验证。
                    </p>
                  )}
                </div>
              </details>
            );
          })}
        </section>
        {detail.stop_rules && (
          <details className="rounded border border-[var(--border)]">
            <summary className="cursor-pointer p-3">停止规则</summary>
            <MarkdownContent content={detail.stop_rules} className="p-3" />
            {detail.stop_rules_origin && (
              <p className="p-3 pt-0 text-xs text-[var(--muted)]">
                停止规则来源：{detail.stop_rules_origin}
              </p>
            )}
            {detail.stop_source_planning_job_id && (
              <div className="space-y-1 p-3 pt-0 text-xs">
                <Link
                  className="break-all text-[var(--accent)] underline"
                  href={`/projects/${detail.project_id}/planning?job=${detail.stop_source_planning_job_id}`}
                >
                  核对停止规则来源任务 {detail.stop_source_planning_job_id}
                </Link>
                <p className="break-all font-mono">
                  原产物 SHA-256：{detail.stop_source_result_sha256 || "未记录"}
                </p>
              </div>
            )}
          </details>
        )}
        <section aria-label="冻结文献元数据" className="space-y-2">
          <h3 className="text-sm font-medium">
            冻结文献元数据 · {detail.evidence.length}
          </h3>
          <p className="text-xs text-[var(--muted)]">
            以下仅为本版本保存的来源元数据；不代替原始 PDF 精读事实或科学验证。
          </p>
          {detail.evidence.length ? (
            detail.evidence.map((source) => (
              <details
                key={source.id}
                className="rounded border border-[var(--border)]"
              >
                <summary className="cursor-pointer p-3 text-xs">
                  {source.title} · {source.year ?? "年份未知"}
                </summary>
                <div className="space-y-2 border-t border-[var(--border)] p-3 text-xs">
                  <p className="break-all font-mono">
                    Paper ID：{source.paper_id} · Paper 版本{" "}
                    {source.paper_version}
                  </p>
                  <p>DOI：{source.doi || "未记录"}</p>
                  <p className="break-all font-mono">
                    来源 SHA-256：{source.sha256}
                  </p>
                  <p className="whitespace-pre-wrap break-words">
                    {source.abstract || "未记录摘要"}
                  </p>
                </div>
              </details>
            ))
          ) : (
            <p className="text-xs text-[var(--muted)]">没有冻结文献来源。</p>
          )}
        </section>
        <section aria-label="冻结精读笔记" className="space-y-2">
          <h3 className="text-sm font-medium">
            冻结精读笔记 · {detail.canonical_note_sources?.length ?? 0}
          </h3>
          <p className="text-xs text-[var(--muted)]">
            Canonical Markdown 原文候选及其批准来源随版本冻结。派生笔记不是原
            PDF，也不表示科学结论已验证。
          </p>
          {detail.canonical_note_sources?.length ? (
            detail.canonical_note_sources.map((source) => (
              <details
                key={source.canonical_note_id}
                className="rounded border border-[var(--border)]"
              >
                <summary className="cursor-pointer p-3 text-xs">
                  {source.paper_title} ·{" "}
                  {source.context_current
                    ? "来源仍一致"
                    : "来源已变化或存在缺口"}
                </summary>
                <div className="space-y-3 border-t border-[var(--border)] p-3 text-xs">
                  <Link
                    className="text-[var(--accent)] underline"
                    href={`/papers/${source.paper_id}`}
                  >
                    核对论文与 Skill 精读
                  </Link>
                  <p className="break-all font-mono">
                    笔记 ID：{source.canonical_note_id}
                  </p>
                  <p className="break-all font-mono">
                    原笔记 SHA-256：{source.note_sha256}
                  </p>
                  <p>
                    {source.note_characters} 字 · {source.note_bytes} bytes ·{" "}
                    {source.source_scope} / {source.note_origin}
                  </p>
                  <p className="break-all">
                    批准计划：{source.reading_plan_id} · 精读任务：
                    {source.reading_job_id}
                  </p>
                  {!!source.gaps.length && (
                    <p className="break-words text-[var(--danger)]">
                      来源缺口：{source.gaps.join("、")}
                    </p>
                  )}
                  <details>
                    <summary className="cursor-pointer py-1">
                      查看冻结来源事实（PDF 仅绑定，不随笔记发送）
                    </summary>
                    <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-all rounded bg-[var(--surface)] p-2">
                      {JSON.stringify(source.source_facts, null, 2)}
                    </pre>
                  </details>
                  <details open>
                    <summary className="cursor-pointer py-1">
                      浏览完整精读 Markdown
                    </summary>
                    <MarkdownContent content={source.markdown} />
                  </details>
                  <details>
                    <summary className="cursor-pointer py-1">
                      查看原 Markdown（只读）
                    </summary>
                    <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-words rounded bg-[var(--surface)] p-2">
                      {source.markdown}
                    </pre>
                  </details>
                </div>
              </details>
            ))
          ) : (
            <p className="text-xs text-[var(--muted)]">
              没有冻结精读笔记。修订时可主动选择课题论文的可用笔记。
            </p>
          )}
        </section>
        <section aria-label="任务书缺口" className="space-y-2">
          <h3 className="font-medium">当前缺口</h3>
          {detail.gaps.length ? (
            <ul className="space-y-1 text-xs text-[var(--muted)]">
              {detail.gaps.map((gap, index) => (
                <li key={`${gap}:${index}`} className="break-words">
                  {gap}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-[var(--muted)]">
              未报告任务书字段缺口；执行仍需独立授权。
            </p>
          )}
        </section>
        {detail.review ? (
          <div className="space-y-2 rounded border border-[var(--border)] p-3 text-xs">
            <p>
              本人审阅：{detail.review.decision === "ACCEPT" ? "接受" : "拒绝"}{" "}
              · {new Date(detail.review.reviewed_at).toLocaleString("zh-CN")}
            </p>
            {detail.review.comment && (
              <p className="whitespace-pre-wrap break-words">
                {detail.review.comment}
              </p>
            )}
            <p className="text-[var(--muted)]">
              旧审阅保持与原版本绑定；修订需要审阅新版本。
            </p>
          </div>
        ) : (
          <div className="space-y-3 rounded border border-[var(--border)] p-3">
            <label className="block space-y-1.5 text-xs font-medium">
              本版本审阅意见（可选）
              <Textarea
                maxLength={4000}
                disabled={busy}
                value={comment}
                onChange={(event) => setComment(event.target.value)}
              />
            </label>
            <div className="flex flex-wrap gap-2">
              <Button
                disabled={busy || !detail.context_current}
                onClick={() =>
                  void onReview({
                    expected_sha256: detail.sha256,
                    decision: "ACCEPT",
                    comment: comment.trim() || null,
                  })
                }
              >
                接受本版本
              </Button>
              <Button
                variant="secondary"
                disabled={busy || !detail.context_current}
                onClick={() =>
                  void onReview({
                    expected_sha256: detail.sha256,
                    decision: "REJECT",
                    comment: comment.trim() || null,
                  })
                }
              >
                拒绝本版本
              </Button>
            </div>
          </div>
        )}
        <Button
          variant="secondary"
          disabled={busy}
          onClick={() => onEdit(detail)}
        >
          以此版本创建修订
        </Button>
      </CardContent>
    </Card>
  );
}
