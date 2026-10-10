import Link from "next/link";

import { Card, CardContent, CardHeader } from "@/components/ui/card";
import type { PaperReproductionPreview } from "@/lib/api";

export const reproductionStageLabels = {
  PLAN: "复现方案",
  IMPLEMENT_CODE: "代码与测试准备",
} as const;
export const reproductionScopeLabels = {
  METADATA_ONLY: "论文元数据",
  ABSTRACT_ONLY: "元数据与摘要",
  FULL_TEXT: "选定的全文解析文本",
  DERIVED_NOTE: "已有精读Markdown（AI派生资料）",
} as const;

export function ReproductionContextPanel({
  context,
  title = "已冻结的论文来源",
}: {
  context: PaperReproductionPreview;
  title?: string;
}) {
  return (
    <Card>
      <CardHeader>
        <h2 className="font-semibold">{title}</h2>
        <span className="text-xs text-[var(--muted)]">
          {reproductionStageLabels[context.stage]}
        </span>
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        <Link
          href={"/papers/" + context.paper_id}
          className="font-medium text-[var(--accent)] hover:underline"
        >
          {context.paper_title}
        </Link>
        <dl className="grid gap-3 text-xs sm:grid-cols-2">
          {context.source_scope === "DERIVED_NOTE" && (
            <div className="sm:col-span-2 space-y-2 rounded border border-[var(--border)] p-3">
              <p>
                本次资料为 AI_DERIVED
                精读笔记，原PDF绑定但未发送（BOUND_NOT_SENT）。科学审核状态：
                {context.note_review_status ?? "未知，未提供此状态"}。
              </p>
              <p>
                原PDF字节核查：
                {context.pdf_bytes_verified
                  ? "本次明确预览已核对"
                  : "历史或列表未记录核验"}
                ；核验字节不表示代码模型收到了原PDF。
              </p>
              {context.skill_provenance === "LEGACY_INSTRUCTIONS" && (
                <p className="text-amber-700 dark:text-amber-300">
                  旧任务仅保存阅读指令，完整Skill文件快照未记录；没有补造历史来源。
                </p>
              )}
              <details>
                <summary className="cursor-pointer">
                  查看笔记与原PDF溯源
                </summary>
                <div className="mt-2 space-y-1 break-all font-mono">
                  <p>
                    笔记 SHA-256：{context.canonical_note_sha256 ?? "未记录"}
                  </p>
                  <p>阅读任务：{context.reading_job_id ?? "未记录"}</p>
                  <p>批准计划：{context.reading_plan_id ?? "未记录"}</p>
                  <p>原PDF SHA-256：{context.pdf_sha256 ?? "未记录"}</p>
                  <p>
                    Skill：{context.skill_key ?? "未记录"} v
                    {context.skill_version ?? "未记录"}
                  </p>
                  <p>来源层级：{context.skill_provenance ?? "未记录"}</p>
                  <p>
                    来源文件快照：
                    {context.source_manifest_sha256 ?? "历史未记录"}
                  </p>
                  {context.provenance_gaps?.map((gap, index) => (
                    <p key={gap + index}>{gap}</p>
                  ))}
                </div>
              </details>
            </div>
          )}
          <div>
            <dt className="text-[var(--muted)]">资料范围</dt>
            <dd className="mt-1">
              {reproductionScopeLabels[context.source_scope]}
            </dd>
          </div>
          <div>
            <dt className="text-[var(--muted)]">论文元数据版本</dt>
            <dd className="mt-1">v{context.paper_metadata_version}</dd>
          </div>
          <div>
            <dt className="text-[var(--muted)]">来源文本大小</dt>
            <dd className="mt-1">
              {context.context_characters.toLocaleString()} 字符 / 上限{" "}
              {context.max_context_characters?.toLocaleString() ??
                "见服务端配置"}
            </dd>
          </div>
          <div>
            <dt className="text-[var(--muted)]">
              {context.source_scope === "DERIVED_NOTE"
                ? "笔记选择范围"
                : "选定解析章节"}
            </dt>
            <dd className="mt-1">
              {context.source_scope === "DERIVED_NOTE"
                ? context.selection_mode === "EXCERPTS"
                  ? "明确精确选段 · " + (context.excerpts?.length ?? 0) + " 个"
                  : "完整已有Markdown笔记，未默认截断"
                : context.section_ids.length + " 个"}
            </dd>
          </div>
          {context.note_id && (
            <div className="sm:col-span-2">
              <dt className="text-[var(--muted)]">引用的精读笔记</dt>
              <dd className="mt-1 flex flex-wrap gap-2">
                <Link
                  href={"/research-notes/" + context.note_id}
                  className="text-[var(--accent)] hover:underline"
                >
                  修订 v{context.note_revision ?? "未记录"}
                </Link>
                <span>
                  人工审核状态：{context.note_review_status ?? "未记录"}
                </span>
              </dd>
              <p className="mt-1 text-[var(--muted)]">
                笔记内容作为来源材料；AI 候选与尚未确认的判断仍需核对原文。
              </p>
            </div>
          )}
          {context.parsed_document_id && (
            <div className="sm:col-span-2 space-y-1">
              <dt className="text-[var(--muted)]">PDF 与解析版本</dt>
              <dd>
                {context.parser_name ?? "未记录"} v
                {context.parser_version ?? "未记录"} ·{" "}
                {context.parser_status ?? "状态未记录"}
              </dd>
              <dd className="break-all font-mono text-[11px]">
                PDF SHA-256：{context.pdf_sha256 ?? "未记录"}
              </dd>
              <dd className="break-all text-[var(--muted)]">
                解析文档：{context.parsed_document_id}
              </dd>
            </div>
          )}
          <div className="sm:col-span-2">
            <dt className="text-[var(--muted)]">来源快照 SHA-256</dt>
            <dd className="mt-1 break-all font-mono text-[11px]">
              {context.context_sha256}
            </dd>
          </div>
        </dl>
        {context.source_scope === "DERIVED_NOTE" && (
          <div className="space-y-2 text-xs">
            <p>
              上下文：{context.context_characters} Unicode 字符 /{" "}
              {context.context_bytes ?? "历史未记录"} 字节；字节上限{" "}
              {context.max_context_bytes ?? "历史未记录"}。
            </p>
            {context.excerpts?.map((excerpt, index) => (
              <details key={excerpt.start + ":" + excerpt.end}>
                <summary className="cursor-pointer">
                  冻结精确选段 {index + 1} · {excerpt.start}–{excerpt.end}
                </summary>
                <pre
                  aria-label={"冻结精确选段 " + (index + 1)}
                  className="mt-2 max-h-56 overflow-auto whitespace-pre-wrap break-words"
                >
                  {excerpt.text}
                </pre>
                <p className="break-all font-mono">{excerpt.sha256}</p>
              </details>
            ))}
            {(context.omitted_ranges?.length ?? 0) > 0 && (
              <details>
                <summary className="cursor-pointer">实际省略范围</summary>
                <pre className="overflow-auto">
                  {JSON.stringify(context.omitted_ranges, null, 2)}
                </pre>
              </details>
            )}
          </div>
        )}
        <div className="rounded border border-[var(--border)] bg-[var(--background)] p-3 text-xs leading-5 text-[var(--muted)]">
          此任务仅准备科研方案、代码改进及服务器交接说明。实验、模型试运行、训练、评价与仿真只在课题组服务器执行；此页面不提交服务器任务，也不授权本机科研运行。
        </div>
        {(context.warnings ?? []).length > 0 && (
          <div className="space-y-1 rounded border border-amber-500/25 bg-amber-500/5 p-3 text-xs leading-5 text-amber-700 dark:text-amber-300">
            {(context.warnings ?? []).map((warning, index) => (
              <p key={index}>{warning}</p>
            ))}
          </div>
        )}
        <details className="rounded border border-[var(--border)] p-3">
          <summary className="cursor-pointer text-xs font-medium">
            查看选定来源全文
          </summary>
          <pre className="mt-3 max-h-96 overflow-y-auto whitespace-pre-wrap break-words font-sans text-xs leading-6">
            {context.context_text}
          </pre>
        </details>
      </CardContent>
    </Card>
  );
}
