"use client";

import { useCallback, useEffect, useState } from "react";
import {
  api,
  type AnalysisJob,
  type PDFReadingSource,
  type PaperAttachment,
  type ResearchNote,
} from "@/lib/api";
import { LoadingState, ErrorState, EmptyState } from "@/components/ui/state";
import { feedbackLabel } from "./feedback";

export function NoteSourcePanel({ note }: { note: ResearchNote }) {
  const [source, setSource] = useState<PDFReadingSource | null>(null);
  const [attachment, setAttachment] = useState<PaperAttachment | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      if (note.analysis_job_id) {
        const job = await api.get<AnalysisJob>(
          `/analysis-jobs/${note.analysis_job_id}`,
        );
        if (job.source_type === "PDF")
          setSource(
            await api.get<PDFReadingSource>(
              `/analysis-jobs/${note.analysis_job_id}/pdf-source`,
            ),
          );
        // A legacy text job does not establish which PDF supplied its evidence.
      } else {
        const attachments = await api.get<PaperAttachment[]>(
          `/papers/${note.paper_id}/attachments`,
        );
        if (attachments.length === 1) setAttachment(attachments[0]);
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "无法读取本版原文来源");
    } finally {
      setBusy(false);
    }
  }, [note.analysis_job_id, note.paper_id]);
  useEffect(() => {
    queueMicrotask(() => void load());
  }, [load]);
  const attachmentId = source?.attachment_id ?? attachment?.attachment_id;
  return (
    <section
      aria-label="原文与来源"
      className="space-y-3 rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4"
    >
      <div className="flex flex-wrap justify-between gap-2">
        <h2 className="font-semibold">原文与来源</h2>
        {attachmentId && (
          <a
            className="text-xs text-[var(--accent)] hover:underline"
            href={`/api/v1/attachments/${attachmentId}/download`}
            target="_blank"
            rel="noopener noreferrer"
          >
            独立打开原文 ↗
          </a>
        )}
      </div>
      {busy ? (
        <LoadingState label="正在读取原文来源…" />
      ) : error ? (
        <ErrorState message={error} onRetry={() => void load()} />
      ) : attachmentId ? (
        <iframe
          title="论文原文 PDF"
          src={`/api/v1/attachments/${attachmentId}/download`}
          className="h-[75vh] min-h-96 w-full rounded border border-[var(--border)]"
        />
      ) : (
        <EmptyState
          title="本版没有明确绑定的原始 PDF"
          detail="没有可确认的来源时，不自动选择其他附件代替。"
        />
      )}
      <details className="rounded border border-[var(--border)] p-3 text-xs">
        <summary className="cursor-pointer">来源、Skill 与证据定位</summary>
        <div className="mt-3 space-y-2 break-words text-[var(--muted)]">
          <p>
            来源范围：{note.analysis_scope} · {note.analysis_mode} ·{" "}
            {note.created_by}
          </p>
          {source && (
            <>
              <p>
                技能：{source.skill_key} · {source.skill_version}
              </p>
              <p>
                PDF：{source.page_count} 页 · SHA-256 {source.sha256}
              </p>
              <p>Skill SHA-256：{source.skill_sha256}</p>
            </>
          )}
          {note.sections.map((section) => (
            <div key={section.id}>
              {section.evidence.length > 0 && (
                <h3 className="font-medium">
                  {feedbackLabel(section.section_key)}
                </h3>
              )}
              {section.evidence.map((evidence, index) => (
                <p key={index} className="mt-1">
                  {evidence.source_section || "未定位章节"}
                  {evidence.source_page ? ` · p.${evidence.source_page}` : ""}
                  {evidence.locator ? ` · ${evidence.locator}` : ""}
                  {evidence.evidence_text ? ` — ${evidence.evidence_text}` : ""}
                  {source &&
                    evidence.source_page &&
                    evidence.source_page > 0 &&
                    evidence.source_page <= source.page_count && (
                      <a
                        href={`/api/v1/attachments/${source.attachment_id}/download#page=${evidence.source_page}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="ml-2 text-[var(--accent)]"
                      >
                        查看此页 ↗
                      </a>
                    )}
                </p>
              ))}
            </div>
          ))}
        </div>
      </details>
    </section>
  );
}
