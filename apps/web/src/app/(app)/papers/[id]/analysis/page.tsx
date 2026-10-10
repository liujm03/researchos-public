"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { ArrowLeft, FileText, LoaderCircle, Sparkles } from "lucide-react";

import { PdfUploadForm } from "@/components/papers/pdf-upload";
import { PdfAnnotationReader } from "@/components/pdf-annotations/reader";
import { DirectPDFReading } from "@/components/papers/direct-pdf-reading";
import {
  ReadingTaskCard,
  analysisStatusLabels,
  requiresUncertainAcknowledgement,
  usesCurrentReadingSkill,
} from "@/components/papers/reading-task-card";
import { CanonicalNotePanel } from "@/components/papers/canonical-note";
import { VenueBadges } from "@/components/papers/venue-ratings";
import {
  ClassificationEditor,
  ProjectLabels,
  ZoteroSourceLabels,
} from "@/components/literature/classification";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import {
  api,
  type AICapabilities,
  type AnalysisJob,
  type AutomationSettings,
  type CopiedPdf,
  type Paper,
  type PaperAttachment,
  type ParseJob,
  type ParsedDocument,
  type PdfUpload,
  type ResearchNote,
  type ZoteroAttachment,
} from "@/lib/api";

function isSkillReading(job: AnalysisJob) {
  return usesCurrentReadingSkill(job);
}
const parseStatusLabels: Record<string, string> = {
  QUEUED: "等待本机解析",
  PARSING: "正在解析",
  COMPLETED: "解析完成",
  FAILED: "解析失败",
};

function submittedAnalysisMessage(job: AnalysisJob) {
  if (job.status === "QUEUED")
    return "分析任务已入队，等待 worker 执行；尚未产生分析结果。";
  if (job.status.startsWith("WAITING_"))
    return `任务已保存，尚未开始分析：${analysisStatusLabels[job.status] ?? job.status}。${job.error_message ?? "请检查下方任务原因和 AI 设置。"}`;
  if (job.status === "COMPLETED")
    return "这份输入与分析深度已有完成任务，已复用结果；可打开下方结构化笔记。";
  return `任务状态：${analysisStatusLabels[job.status] ?? job.status}。${job.error_message ?? ""}`;
}

export default function PaperAnalysisPage() {
  const { id } = useParams<{ id: string }>();
  const [analysisVisible, setAnalysisVisible] = useState(true);
  const [paper, setPaper] = useState<Paper | null>(null);
  const [attachments, setAttachments] = useState<PaperAttachment[]>([]);
  const [zoteroAttachments, setZoteroAttachments] = useState<
    ZoteroAttachment[]
  >([]);
  const [zoteroError, setZoteroError] = useState("");
  const [zoteroKey, setZoteroKey] = useState<string | null>(null);
  const [documents, setDocuments] = useState<ParsedDocument[]>([]);
  const [jobs, setJobs] = useState<AnalysisJob[]>([]);
  const [notes, setNotes] = useState<ResearchNote[]>([]);
  const [notesError, setNotesError] = useState("");
  const [parseJobs, setParseJobs] = useState<ParseJob[]>([]);
  const [selectedAttachmentId, setSelectedAttachmentId] = useState<
    string | null
  >(null);
  const [parseError, setParseError] = useState("");
  const [capabilities, setCapabilities] = useState<AICapabilities | null>(null);
  const [settings, setSettings] = useState<AutomationSettings | null>(null);
  const [preflightError, setPreflightError] = useState("");
  const [analysisPollError, setAnalysisPollError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [pdfUnsaved, setPdfUnsaved] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [acknowledgedJobId, setAcknowledgedJobId] = useState<string | null>(
    null,
  );

  const storedPdfs = attachments.filter(
    (attachment) => attachment.attachment_id,
  );
  const storedPdf =
    storedPdfs.find(
      (attachment) => attachment.attachment_id === selectedAttachmentId,
    ) ?? storedPdfs[0];
  const parseJob = parseJobs.find(
    (job) => job.attachment_id === storedPdf?.attachment_id,
  );

  const load = useCallback(async () => {
    try {
      const [
        paperResult,
        attachmentResult,
        documentResult,
        jobResult,
        noteResult,
        parseJobResult,
      ] = await Promise.allSettled([
        api.get<Paper>(`/papers/${id}`),
        api.get<PaperAttachment[]>(`/papers/${id}/attachments`),
        api.get<ParsedDocument[]>(`/papers/${id}/parsed-documents`),
        api.get<AnalysisJob[]>(`/papers/${id}/analysis-jobs`),
        api.get<ResearchNote[]>(`/papers/${id}/research-notes`),
        api.get<ParseJob[]>(`/papers/${id}/parse-jobs?limit=100`),
      ]);
      if (paperResult.status !== "fulfilled") throw paperResult.reason;
      if (attachmentResult.status !== "fulfilled")
        throw attachmentResult.reason;
      const paperData = paperResult.value;
      const attachmentData = attachmentResult.value;
      setPaper(paperData);
      setAttachments(attachmentData);
      setDocuments(
        documentResult.status === "fulfilled" ? documentResult.value : [],
      );
      setJobs(
        jobResult.status === "fulfilled"
          ? jobResult.value.filter(isSkillReading)
          : [],
      );
      setNotes(noteResult.status === "fulfilled" ? noteResult.value : []);
      setNotesError(
        noteResult.status === "fulfilled"
          ? ""
          : "暂时无法读取已有科研笔记，可刷新重试。",
      );
      setParseJobs(
        parseJobResult.status === "fulfilled" ? parseJobResult.value : [],
      );
      setParseError(
        documentResult.status === "rejected" ||
          parseJobResult.status === "rejected"
          ? "整理文本或解析任务暂不可读取，原始 PDF 精读仍可提交。"
          : "",
      );
      setAnalysisPollError(
        jobResult.status === "fulfilled"
          ? ""
          : "暂时无法读取分析任务历史，可刷新重试。",
      );
      setSelectedAttachmentId((current) =>
        attachmentData.some(
          (attachment) => attachment.attachment_id === current,
        )
          ? current
          : (attachmentData.find((attachment) => attachment.attachment_id)
              ?.attachment_id ?? null),
      );
      setError("");
      setLoading(false);
      const checks = await Promise.allSettled([
        api.get<AICapabilities>("/ai/capabilities"),
        api.get<AutomationSettings>("/settings/literature-automation"),
      ]);
      const [aiCheck, settingsCheck] = checks;
      setCapabilities(aiCheck.status === "fulfilled" ? aiCheck.value : null);
      setSettings(
        settingsCheck.status === "fulfilled" ? settingsCheck.value : null,
      );
      setPreflightError(
        checks.some((check) => check.status === "rejected")
          ? "无法读取精读配置，请刷新后再提交；原始 PDF 仍可查阅。"
          : "",
      );
      const zoteroSource = paperData.sources.find((source) =>
        source.provider_key.startsWith("zotero_"),
      );
      const key = zoteroSource?.provider_id.split(":").at(-1) ?? null;
      setZoteroKey(key);
      if (key) {
        try {
          setZoteroAttachments(
            await api.get<ZoteroAttachment[]>(
              `/reference-managers/zotero/items/${encodeURIComponent(key)}/attachments`,
            ),
          );
          setZoteroError("");
        } catch (cause) {
          setZoteroAttachments([]);
          setZoteroError(
            cause instanceof Error ? cause.message : "Zotero 来源暂不可访问",
          );
        }
      } else {
        setZoteroAttachments([]);
        setZoteroError("");
      }
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "无法加载论文分析工作区",
      );
    } finally {
      setLoading(false);
    }
  }, [id]);
  useEffect(() => {
    queueMicrotask(() => void load());
  }, [load]);

  useEffect(() => {
    if (!parseJob || !["QUEUED", "PARSING"].includes(parseJob.status)) return;
    let active = true;
    const timer = window.setInterval(async () => {
      try {
        const current = await api.get<ParseJob>(`/parse-jobs/${parseJob.id}`);
        if (!active) return;
        setParseJobs((previous) =>
          previous.map((job) => (job.id === current.id ? current : job)),
        );
        setParseError("");
        if (current.status === "COMPLETED") void load();
      } catch (cause) {
        if (active)
          setParseError(
            cause instanceof Error
              ? `无法更新解析状态：${cause.message}`
              : "无法更新解析状态，稍后自动重试。",
          );
      }
    }, 2500);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [parseJob, load]);

  useEffect(() => {
    if (
      !jobs.some((job) =>
        ["QUEUED", "ANALYZING", "RETRY_WAIT"].includes(job.status),
      )
    )
      return;
    const timer = window.setInterval(async () => {
      try {
        const current = await api.get<AnalysisJob[]>(
          `/papers/${id}/analysis-jobs`,
        );
        setJobs(current.filter(isSkillReading));
        setAnalysisPollError("");
        if (current.some((job) => job.status === "COMPLETED")) {
          setNotes(
            await api.get<ResearchNote[]>(`/papers/${id}/research-notes`),
          );
        }
      } catch (cause) {
        setAnalysisPollError(
          cause instanceof Error
            ? `无法更新分析状态：${cause.message}`
            : "无法更新分析状态，稍后自动重试。",
        );
      }
    }, 3000);
    return () => window.clearInterval(timer);
  }, [jobs, id]);

  async function copyPdf(attachmentKey: string) {
    if (!zoteroKey) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const result = await api.post<CopiedPdf>(
        `/reference-managers/zotero/items/${zoteroKey}/attachments/${attachmentKey}/copy`,
        { paper_id: id },
      );
      setSelectedAttachmentId(result.attachment_id);
      setMessage(
        `PDF 已保存到 ResearchOS（SHA-256: ${result.sha256.slice(0, 12)}…）。`,
      );
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "PDF 复制失败");
    } finally {
      setBusy(false);
    }
  }

  async function parsePdf(attachmentId: string) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const result = await api.post<ParseJob>(
        `/papers/${id}/attachments/${attachmentId}/parse-jobs`,
      );
      setSelectedAttachmentId(attachmentId);
      setParseJobs((current) => [
        result,
        ...current.filter((job) => job.id !== result.id),
      ]);
      setParseError("");
      setMessage(
        result.status === "COMPLETED"
          ? "这份 PDF 已有当前解析器版本的结果，已复用；无需重新上传。"
          : result.status === "PARSING"
            ? "这份 PDF 正在本机解析，完成后章节会更新。"
            : "PDF 解析任务已入队；页面会更新状态。",
      );
      if (result.status === "COMPLETED") await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "解析入队失败");
    } finally {
      setBusy(false);
    }
  }

  async function uploadedPdf(result: PdfUpload) {
    setSelectedAttachmentId(result.attachment.attachment_id);
    setParseJobs((current) => [
      result.parse_job,
      ...current.filter((job) => job.id !== result.parse_job.id),
    ]);
    setParseError("");
    await load();
  }

  async function retryParseJob(jobId: string) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const result = await api.post<ParseJob>(`/parse-jobs/${jobId}/retry`);
      setParseJobs((current) => [
        result,
        ...current.filter((job) => job.id !== result.id),
      ]);
      setParseError("");
      setMessage("本机 PDF 解析已重新排队。");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "无法重试 PDF 解析");
    } finally {
      setBusy(false);
    }
  }

  async function retryJob(jobId: string) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const updated = await api.post<AnalysisJob>(
        `/analysis-jobs/${jobId}/retry`,
      );
      setJobs((current) =>
        current.map((job) => (job.id === jobId ? updated : job)),
      );
      setMessage(submittedAnalysisMessage(updated));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "重试失败");
    } finally {
      setBusy(false);
    }
  }

  async function retryUncertainJob(jobId: string) {
    if (acknowledgedJobId !== jobId) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const updated = await api.post<AnalysisJob>(
        `/analysis-jobs/${jobId}/acknowledge-uncertain`,
        { acknowledge_possible_duplicate_charge: true },
      );
      setJobs((current) =>
        current.map((job) => (job.id === jobId ? updated : job)),
      );
      setAcknowledgedJobId(null);
      setMessage("已记录确认，任务重新入队；结果不明的片段可能重复计费。");
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "无法重试结果不明的任务",
      );
    } finally {
      setBusy(false);
    }
  }

  async function cancelJob(jobId: string) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const updated = await api.post<AnalysisJob>(
        `/analysis-jobs/${jobId}/cancel`,
      );
      setJobs((current) =>
        current.map((job) => (job.id === jobId ? updated : job)),
      );
      setMessage("任务已取消。");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "取消失败");
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <LoadingState label="正在加载文献、附件与分析状态…" />;
  if (error && !paper)
    return <ErrorState message={error} onRetry={() => void load()} />;
  if (!paper) return null;

  const latestDocument = documents.find(
    (document) => document.attachment_id === storedPdf?.attachment_id,
  );
  const orderedJobs = jobs
    .filter(isSkillReading)
    .sort((a, b) => b.queued_at.localeCompare(a.queued_at));
  const latestJob = orderedJobs[0];
  const needsAction = (job: AnalysisJob) =>
    requiresUncertainAcknowledgement(job) ||
    !!job.error_code ||
    !!job.error_message ||
    job.status === "FAILED" ||
    job.status.startsWith("WAITING_") ||
    ["QUEUED", "ANALYZING", "RETRY_WAIT"].includes(job.status);
  const visibleJobs = orderedJobs.filter(
    (job) => job.id === latestJob?.id || needsAction(job),
  );
  const historicalJobs = orderedJobs.filter(
    (job) => !visibleJobs.includes(job),
  );
  const renderTask = (job: AnalysisJob) => (
    <ReadingTaskCard
      key={job.id}
      job={job}
      settings={settings}
      busy={busy}
      note={notes.find((note) => note.analysis_job_id === job.id)}
      acknowledgedJobId={acknowledgedJobId}
      setAcknowledgedJobId={setAcknowledgedJobId}
      retryJob={retryJob}
      cancelJob={cancelJob}
      retryUncertainJob={retryUncertainJob}
      load={load}
    />
  );
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Link
          href={`/papers/${id}`}
          className="inline-flex items-center gap-2 text-xs text-[var(--muted)] hover:text-[var(--accent)]"
        >
          <ArrowLeft className="h-4 w-4" />
          返回论文
        </Link>
        <div className="flex flex-wrap items-center gap-3">
          <Link
            href={`/papers/${id}/reproduction`}
            className="text-xs text-[var(--accent)] hover:underline"
          >
            创建复现准备草稿 →
          </Link>
          <Button
            size="sm"
            variant="secondary"
            aria-controls="paper-analysis-panel"
            aria-expanded={analysisVisible}
            onClick={() => setAnalysisVisible((visible) => !visible)}
          >
            {analysisVisible ? "专注阅读（隐藏分析）" : "显示分析与审核"}
          </Button>
        </div>
      </div>
      <div>
        <h1 className="text-base font-semibold leading-snug lg:text-lg">
          {paper.title}
        </h1>
        <VenueBadges records={paper.venue_assessments} />
        <div className="mt-2 space-y-2">
          <ProjectLabels projects={paper.literature_context?.projects} />
          <details className="text-xs text-[var(--muted)]">
            <summary className="cursor-pointer">
              Zotero 来源文件夹 / 课题分类
            </summary>
            <div className="mt-2 space-y-2">
              <ZoteroSourceLabels context={paper.literature_context} />
              <ClassificationEditor
                key={id}
                paperId={id}
                onSaved={() => void load()}
              />
            </div>
          </details>
        </div>
        <p
          className="mt-1 truncate text-xs text-[var(--muted)]"
          title={storedPdf?.filename ?? undefined}
        >
          当前精读来源：{storedPdf?.filename ?? "请选择或上传原始 PDF"}
          。默认直接阅读所选 PDF 原始页面。
        </p>
      </div>
      {error && <ErrorState message={error} onRetry={() => void load()} />}
      {message && (
        <p
          role="status"
          className="rounded-md border border-[var(--accent)]/30 bg-[var(--accent)]/8 px-3 py-2 text-sm text-[var(--accent)]"
        >
          {message}
        </p>
      )}
      <div
        data-testid="paper-reading-layout"
        className={`grid items-start gap-3 ${analysisVisible ? "lg:grid-cols-[minmax(0,1fr)_320px]" : "grid-cols-1"}`}
      >
        <Card className="min-w-0" data-testid="original-pdf-panel">
          <CardHeader className="px-3 py-2">
            <div className="flex items-center gap-2">
              <FileText className="h-4 w-4 text-[var(--accent)]" />
              <h2 className="font-semibold">原文 PDF</h2>
            </div>
            {storedPdf?.attachment_id && (
              <a
                href={`/api/v1/attachments/${storedPdf.attachment_id}/download`}
                target="_blank"
                rel="noreferrer"
                className="text-xs text-[var(--accent)] hover:underline"
              >
                独立打开原文 ↗
              </a>
            )}
          </CardHeader>
          <CardContent className="space-y-2 p-2">
            {storedPdf?.attachment_id && (
              <PdfAnnotationReader
                paperId={id}
                attachmentId={storedPdf.attachment_id}
                sourceSha256={storedPdf.sha256}
                filename={storedPdf.filename ?? undefined}
                onUnsavedChange={setPdfUnsaved}
              />
            )}
            <details
              open={!storedPdf?.attachment_id}
              className="rounded-md border border-[var(--border)] p-2"
              data-testid="paper-source-tools"
            >
              <summary className="cursor-pointer text-xs font-medium">
                PDF 来源、上传与解析
              </summary>
              <div className="mt-3 space-y-3">
                {preflightError && (
                  <ErrorState
                    message={preflightError}
                    onRetry={() => void load()}
                  />
                )}
                <PdfUploadForm
                  paperId={id}
                  disabled={busy || pdfUnsaved}
                  onUploadingChange={setBusy}
                  onUploaded={uploadedPdf}
                />
                {storedPdfs.length > 1 && (
                  <label className="block space-y-1.5 text-xs font-medium">
                    选择已保存的 PDF
                    <select
                      aria-label="选择已保存的 PDF"
                      disabled={busy || pdfUnsaved}
                      value={storedPdf?.attachment_id ?? ""}
                      onChange={(event) => {
                        setSelectedAttachmentId(event.target.value);
                        setParseError("");
                      }}
                      className="h-9 w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-2 text-xs"
                    >
                      {storedPdfs.map((attachment) => (
                        <option
                          key={attachment.id}
                          value={attachment.attachment_id!}
                        >
                          {attachment.filename ?? "PDF"} ·{" "}
                          {attachment.sha256?.slice(0, 12) ?? "未知校验和"}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
                {storedPdf?.attachment_id ? (
                  <>
                    <p className="text-xs text-[var(--muted)]">
                      {storedPdf.filename} ·{" "}
                      {storedPdf.size_bytes
                        ? `${(storedPdf.size_bytes / 1024 / 1024).toFixed(1)} MB`
                        : "大小未知"}
                    </p>
                    <Button
                      variant="secondary"
                      disabled={
                        busy ||
                        ["QUEUED", "PARSING"].includes(parseJob?.status ?? "")
                      }
                      onClick={() => parsePdf(storedPdf.attachment_id!)}
                    >
                      {latestDocument
                        ? "检查并重新解析这份 PDF"
                        : "解析这份 PDF"}
                    </Button>
                    {latestDocument && (
                      <p className="text-xs leading-5 text-[var(--muted)]">
                        解析器升级后可直接检查并重新解析已保存文件，旧原文与笔记仍可核对。
                      </p>
                    )}
                  </>
                ) : (
                  <EmptyState
                    title="尚未将 PDF 保存到 ResearchOS"
                    detail={
                      zoteroKey
                        ? "可上传本地 PDF 或从下方 Zotero 附件复制。"
                        : "上传你持有的原始 PDF 后，可按精读技能阅读并生成笔记。"
                    }
                  />
                )}
                {zoteroError && (
                  <div className="space-y-1 rounded border border-amber-500/20 bg-amber-500/5 px-2 py-2 text-xs leading-5 text-amber-700 dark:text-amber-300">
                    <p>
                      Zotero 来源暂不可访问，仅影响来源刷新和附件复制。已保存的
                      PDF 仍可查阅、解析，并在 AI 条件满足后分析。
                    </p>
                    <p className="break-words">连接原因：{zoteroError}</p>
                    <Link
                      href="/integrations/zotero"
                      className="inline-block underline"
                    >
                      检查 Zotero 连接
                    </Link>
                  </div>
                )}
                {parseJob && (
                  <div className="space-y-2 rounded-md border border-[var(--border)] p-3">
                    <p
                      role="status"
                      className="flex items-center gap-2 text-xs text-[var(--muted)]"
                    >
                      {["QUEUED", "PARSING"].includes(parseJob.status) && (
                        <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
                      )}
                      解析任务：
                      {parseStatusLabels[parseJob.status] ?? parseJob.status}
                    </p>
                    <p className="break-all text-xs text-[var(--muted)]">
                      任务 ID：{parseJob.id}
                    </p>
                    {parseJob.error_message && (
                      <p role="alert" className="text-xs text-[var(--danger)]">
                        {parseJob.error_message}
                      </p>
                    )}
                    <div className="flex flex-wrap gap-2">
                      {parseJob.status === "FAILED" && (
                        <Button
                          size="sm"
                          variant="secondary"
                          disabled={busy}
                          onClick={() => retryParseJob(parseJob.id)}
                        >
                          重试解析
                        </Button>
                      )}
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={busy}
                        onClick={() => void load()}
                      >
                        刷新状态
                      </Button>
                    </div>
                  </div>
                )}
                {parseError && (
                  <p role="alert" className="text-xs text-[var(--danger)]">
                    {parseError}
                  </p>
                )}
                {zoteroKey &&
                  zoteroAttachments.filter(
                    (item) => item.content_type === "application/pdf",
                  ).length > 0 && (
                    <div className="space-y-2 border-t border-[var(--border)] pt-3">
                      <h3 className="text-xs font-semibold">Zotero 可用附件</h3>
                      {zoteroAttachments
                        .filter(
                          (item) => item.content_type === "application/pdf",
                        )
                        .map((item) => (
                          <div
                            key={item.key}
                            className="flex flex-wrap items-center justify-between gap-2 rounded border border-[var(--border)] px-2 py-2 text-xs"
                          >
                            <span className="truncate">{item.title}</span>
                            <Button
                              size="sm"
                              variant="secondary"
                              onClick={() => copyPdf(item.key)}
                              disabled={busy}
                            >
                              复制到系统
                            </Button>
                          </div>
                        ))}
                    </div>
                  )}
              </div>
            </details>
          </CardContent>
        </Card>

        <Card
          id="paper-analysis-panel"
          hidden={!analysisVisible}
          className="min-w-0 h-fit lg:sticky lg:top-20 lg:max-h-[calc(100dvh-100px)] lg:overflow-y-auto"
          role="region"
          aria-label="分析与审核侧栏"
        >
          <CardHeader className="px-3 py-2">
            <div className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-[var(--accent)]" />
              <h2 className="font-semibold">分析与审核</h2>
            </div>
          </CardHeader>
          <CardContent className="space-y-4 p-3">
            <DirectPDFReading
              key={storedPdf?.attachment_id ?? "no-pdf"}
              paperId={id}
              attachment={storedPdf}
              capabilities={capabilities}
              settings={settings}
              disabled={busy}
              onBusyChange={setBusy}
              onSubmitted={async (job) => {
                setMessage(
                  job.status === "QUEUED"
                    ? "原始 PDF 精读已入队，将按原始页码调用阅读技能。"
                    : "原始 PDF 精读任务已保存：" +
                        (analysisStatusLabels[job.status] ?? job.status) +
                        "。" +
                        (job.error_message ?? ""),
                );
                setJobs((previous) => [
                  job,
                  ...previous.filter((item) => item.id !== job.id),
                ]);
                await load();
              }}
            />

            <Link
              href="/settings/literature"
              className="block text-center text-xs text-[var(--accent)] hover:underline"
            >
              精读设置
            </Link>
            <div className="border-t border-[var(--border)] pt-4">
              <h3 className="text-xs font-semibold">当前精读</h3>
              {analysisPollError && (
                <p role="alert" className="mt-2 text-xs text-[var(--danger)]">
                  {analysisPollError}
                  <button
                    className="ml-2 underline"
                    onClick={() => void load()}
                  >
                    刷新
                  </button>
                </p>
              )}
              {visibleJobs.length ? (
                <div className="mt-2 space-y-2">
                  <p className="text-xs text-[var(--muted)]">
                    本篇最新精读及仍需处理的任务；每条记录保留其已批准来源。
                  </p>
                  {visibleJobs.map(renderTask)}
                </div>
              ) : (
                <p className="mt-2 text-xs text-[var(--muted)]">
                  尚无当前精读任务
                </p>
              )}
              {historicalJobs
                .filter(
                  (job) =>
                    job.source_type === "PDF" &&
                    !!job.approval_plan_id &&
                    job.status === "COMPLETED",
                )
                .map((job) => (
                  <CanonicalNotePanel
                    key={job.id}
                    jobId={job.id}
                    researchNoteId={
                      notes.find((note) => note.analysis_job_id === job.id)?.id
                    }
                    attentionOnly
                  />
                ))}
              {notesError && visibleJobs.length > 0 && (
                <ErrorState message={notesError} onRetry={() => void load()} />
              )}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
