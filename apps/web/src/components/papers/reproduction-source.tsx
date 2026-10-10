"use client";
import Link from "next/link";
import { MarkdownViewer } from "@/components/markdown/markdown-viewer";
import type { ReproductionSourceContent } from "@/lib/api";
export function ReproductionSourceView({
  source,
}: {
  source: ReproductionSourceContent;
}) {
  return (
    <section
      className="space-y-3 rounded border border-[var(--border)] p-3"
      aria-label="实际精读Markdown来源"
    >
      <p className="text-sm font-medium">
        {source.skill_key} ·{" "}
        {new Date(source.created_at).toLocaleString("zh-CN")}
      </p>
      <p className="text-xs">
        AI 派生精读笔记 · 科学审核状态未知。原 PDF 共 {source.page_count}{" "}
        页，本次只发送选定的 Markdown 资料；原 PDF 绑定但不会发送给代码模型。
      </p>
      {source.skill_provenance === "LEGACY_INSTRUCTIONS" && (
        <p className="text-xs text-amber-700 dark:text-amber-300">
          旧任务仅保存阅读指令，完整 Skill
          文件快照未记录。此历史缺口不要求重新付费精读。
        </p>
      )}
      {source.gaps.length > 0 && (
        <div
          aria-label="精读来源硬缺口"
          className="space-y-1 text-xs text-[var(--danger)]"
        >
          {source.gaps.map((gap, index) => (
            <p key={gap + index}>{gap}</p>
          ))}
        </div>
      )}
      <p className="text-xs text-[var(--muted)]">
        {source.note_characters} Unicode 字符 / {source.note_bytes}{" "}
        字节。列表未核验 PDF 当前字节，明确预览时才核对。
      </p>
      <details className="text-xs">
        <summary className="cursor-pointer">
          精读笔记、原PDF与阅读指令身份
        </summary>
        <div className="mt-2 space-y-1 break-all font-mono">
          <p>笔记 SHA-256：{source.note_sha256}</p>
          <p>原 PDF SHA-256：{source.pdf_sha256}</p>
          <p>阅读任务：{source.reading_job_id}</p>
          <p>批准计划：{source.reading_plan_id}</p>
          <p>
            Skill：{source.skill_key} v{source.skill_version}
          </p>
          <p>Skill SHA-256：{source.skill_sha256}</p>
          <p>来源文件快照：{source.source_manifest_sha256 ?? "历史未记录"}</p>
          <p>来源层级：{source.skill_provenance}</p>
          {source.provenance_gaps?.map((gap, index) => (
            <p key={gap + index}>{gap}</p>
          ))}
        </div>
      </details>
      <Link
        className="text-xs text-[var(--accent)] underline"
        href={"/papers/" + source.paper_id + "/analysis"}
      >
        查阅原 PDF 与精读任务
      </Link>
      <MarkdownViewer
        content={source.markdown}
        label="复现准备精读笔记原文"
        className="max-h-[38rem] overflow-auto"
      />
    </section>
  );
}
