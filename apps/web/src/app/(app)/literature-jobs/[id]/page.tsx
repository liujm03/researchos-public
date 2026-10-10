"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import {
  ArrowLeft,
  BookOpen,
  FileText,
  Inbox,
  LoaderCircle,
  RefreshCw,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import {
  api,
  type AnalysisJob,
  type LiteratureJob,
  type Paper,
  type ParseJob,
} from "@/lib/api";

const activeStatuses = new Set([
  "QUEUED",
  "RUNNING",
  "WAITING_PARSE",
  "WAITING_ANALYSIS",
]);
const retryableStatuses = new Set([
  "FAILED",
  "WAITING_CONFIG",
  "WAITING_BUDGET",
  "WAITING_PROVIDER_QUOTA",
  "WAITING_INPUT_REDUCTION",
  "CANCELLED",
]);
const cancelableAnalysisStatuses = new Set([
  "QUEUED",
  "WAITING_CONFIG",
  "WAITING_BUDGET",
  "WAITING_PROVIDER_QUOTA",
  "RETRY_WAIT",
]);

const stageLabels: Record<string, string> = {
  SYNC: "读取 Zotero 条目",
  COPY: "复制 PDF",
  PARSE: "解析 PDF",
  ANALYZE: "分析论文",
  INBOX: "生成待审核笔记",
  DONE: "处理完成",
};

const statusLabels: Record<string, string> = {
  QUEUED: "排队中",
  RUNNING: "处理中",
  WAITING_PARSE: "等待 PDF 解析",
  WAITING_ANALYSIS: "等待 AI 分析",
  WAITING_CONFIG: "等待 AI 配置",
  WAITING_BUDGET: "等待可用预算",
  WAITING_PROVIDER_QUOTA: "等待 Codex 账号额度",
  WAITING_INPUT_REDUCTION: "待缩减输入",
  WAITING_REVIEW: "等待人工选择已有论文",
  COMPLETED: "已完成",
  FAILED: "失败",
  CANCELLED: "已取消",
};

function Status({ value }: { value: string }) {
  const color =
    value === "COMPLETED"
      ? "text-emerald-600 dark:text-emerald-400"
      : value === "FAILED"
        ? "text-[var(--danger)]"
        : value.startsWith("WAITING")
          ? "text-amber-700 dark:text-amber-300"
          : "text-[var(--muted)]";
  return <span className={color}>{statusLabels[value] ?? value}</span>;
}

export default function LiteratureJobPage() {
  const { id } = useParams<{ id: string }>();
  const [job, setJob] = useState<LiteratureJob | null>(null);
  const [paper, setPaper] = useState<Paper | null>(null);
  const [candidates, setCandidates] = useState<Record<string, Paper>>({});
  const [parseJob, setParseJob] = useState<ParseJob | null>(null);
  const [analysisJob, setAnalysisJob] = useState<AnalysisJob | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [detailError, setDetailError] = useState("");

  const load = useCallback(
    async (initial = false) => {
      if (!initial) setRefreshing(true);
      try {
        const current = await api.get<LiteratureJob>(`/literature-jobs/${id}`);
        setJob(current);
        setError("");
        const details = await Promise.allSettled([
          current.paper_id
            ? api.get<Paper>(`/papers/${current.paper_id}`)
            : Promise.resolve(null),
          current.parse_job_id
            ? api.get<ParseJob>(`/parse-jobs/${current.parse_job_id}`)
            : Promise.resolve(null),
          current.analysis_job_id
            ? api.get<AnalysisJob>(`/analysis-jobs/${current.analysis_job_id}`)
            : Promise.resolve(null),
        ]);
        const [paperResult, parseResult, analysisResult] = details;
        if (paperResult.status === "fulfilled") setPaper(paperResult.value);
        if (parseResult.status === "fulfilled") setParseJob(parseResult.value);
        if (analysisResult.status === "fulfilled")
          setAnalysisJob(analysisResult.value);
        const candidateDetails = await Promise.allSettled(
          current.candidate_paper_ids.map((paperId) =>
            api.get<Paper>(`/papers/${paperId}`),
          ),
        );
        setCandidates(
          Object.fromEntries(
            candidateDetails.flatMap((result, index) =>
              result.status === "fulfilled"
                ? [[current.candidate_paper_ids[index], result.value]]
                : [],
            ),
          ),
        );
        setDetailError(
          details.some((result) => result.status === "rejected") ||
            candidateDetails.some((result) => result.status === "rejected")
            ? "部分关联详情暂时无法读取；流水线状态仍可查看，稍后可刷新。"
            : "",
        );
      } catch (cause) {
        setError(
          cause instanceof Error ? cause.message : "无法读取文献处理任务",
        );
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [id],
  );

  useEffect(() => {
    queueMicrotask(() => void load(true));
  }, [load]);
  useEffect(() => {
    if (!job || !activeStatuses.has(job.status)) return;
    const timer = window.setInterval(() => {
      void load();
    }, 3000);
    return () => window.clearInterval(timer);
  }, [job, load]);

  async function runAction(action: "retry" | "cancel") {
    setBusy(true);
    setError("");
    try {
      const updated = await api.post<LiteratureJob>(
        `/literature-jobs/${id}/${action}`,
      );
      setJob(updated);
      await load();
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : `${action === "retry" ? "重试" : "取消"}任务失败`,
      );
    } finally {
      setBusy(false);
    }
  }

  async function resolveCandidate(paperId: string) {
    setBusy(true);
    setError("");
    try {
      const updated = await api.post<LiteratureJob>(
        `/literature-jobs/${id}/resolve-paper`,
        {
          existing_paper_id: paperId,
        },
      );
      setJob(updated);
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "关联候选论文失败");
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <LoadingState label="正在读取文献处理任务…" />;
  if (!job && error)
    return <ErrorState message={error} onRetry={() => void load()} />;
  if (!job)
    return (
      <EmptyState
        title="任务不存在"
        detail="返回 Zotero 文献库重新选择文献。"
      />
    );

  const canCancel =
    !job.cleared_at &&
    (job.status === "QUEUED" ||
      (job.status === "WAITING_PARSE" && parseJob?.status === "QUEUED") ||
      (job.status === "WAITING_ANALYSIS" &&
        analysisJob &&
        cancelableAnalysisStatuses.has(analysisJob.status)) ||
      [
        "WAITING_CONFIG",
        "WAITING_BUDGET",
        "WAITING_PROVIDER_QUOTA",
        "WAITING_INPUT_REDUCTION",
        "WAITING_REVIEW",
      ].includes(job.status));
  const showSpinner = !job.cleared_at && activeStatuses.has(job.status);

  return (
    <div className="space-y-5">
      <Link
        href="/integrations/zotero"
        className="inline-flex items-center gap-2 text-xs text-[var(--muted)] hover:text-[var(--accent)]"
      >
        <ArrowLeft className="h-4 w-4" />
        返回 Zotero 文献库
      </Link>
      <div>
        <p className="mb-1 text-xs uppercase tracking-[0.18em] text-[var(--accent)]">
          Literature pipeline
        </p>
        <h1 className="text-2xl font-semibold">文献处理任务</h1>
        <p className="mt-1 text-sm text-[var(--muted)]">
          {paper?.title ?? job.item_title} · {job.id}
        </p>
      </div>
      {job.cleared_at && (
        <p className="rounded-md border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-xs text-[var(--muted)]">
          此任务已从任务列表清空，历史记录保留。关联论文、PDF 和笔记仍可查阅。
        </p>
      )}
      {error && <ErrorState message={error} onRetry={() => void load()} />}
      {detailError && (
        <p className="rounded border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-xs text-amber-700 dark:text-amber-300">
          {detailError}
        </p>
      )}

      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <BookOpen className="h-4 w-4 text-[var(--accent)]" />
            <h2 className="font-semibold">流水线状态</h2>
          </div>
          <Status value={job.status} />
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            {showSpinner && (
              <LoaderCircle className="h-4 w-4 animate-spin text-[var(--accent)]" />
            )}
            <span className="font-medium">
              {stageLabels[job.stage] ?? job.stage}
            </span>
            <span className="text-[var(--muted)]">
              · 第 {job.attempt_count} 次尝试
            </span>
          </div>
          <div className="grid gap-2 text-xs text-[var(--muted)] sm:grid-cols-3">
            <div className="rounded-md border border-[var(--border)] p-3">
              Zotero：
              <Link
                href={`/integrations/zotero?item=${encodeURIComponent(job.item_key)}`}
                className="text-[var(--accent)] hover:underline"
              >
                {job.item_key}
              </Link>{" "}
              <span>· v{job.source_version}</span>
            </div>
            <div className="rounded-md border border-[var(--border)] p-3">
              PDF：{job.copy_pdf ? "请求复制" : "未请求复制"}
            </div>
            <div className="rounded-md border border-[var(--border)] p-3">
              AI：
              {job.request_analysis
                ? `${job.analysis_mode} 分析`
                : "未请求分析"}
            </div>
          </div>
          {job.warning_message && (
            <p className="rounded border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-xs text-amber-700 dark:text-amber-300">
              {job.warning_code && `${job.warning_code}：`}
              {job.warning_message}
            </p>
          )}
          {job.error_message && (
            <p className="rounded border border-[var(--danger)]/20 bg-[var(--danger)]/5 px-3 py-2 text-xs text-[var(--danger)]">
              {job.error_code && `${job.error_code}：`}
              {job.error_message}
            </p>
          )}
          {job.candidate_paper_ids.length > 0 && (
            <div className="space-y-2 rounded border border-[var(--accent)]/25 bg-[var(--accent)]/5 p-3 text-xs">
              <p className="font-medium">
                发现可能重复的论文。请核对标题、作者和
                DOI，确认后才关联来源并继续处理。
              </p>
              {job.candidate_paper_ids.map((paperId) => (
                <div
                  key={paperId}
                  className="flex flex-wrap items-center justify-between gap-2 rounded border border-[var(--border)] bg-[var(--surface)] p-2"
                >
                  <div className="min-w-0">
                    <Link
                      href={`/papers/${paperId}`}
                      className="font-medium text-[var(--accent)] hover:underline"
                    >
                      {candidates[paperId]?.title ?? paperId}
                    </Link>
                    <p className="mt-1 text-[var(--muted)]">
                      {candidates[paperId]?.authors
                        .map((author) => author.display_name)
                        .join(", ") || "作者信息暂不可用"}{" "}
                      · DOI {candidates[paperId]?.doi ?? "未知"}
                    </p>
                  </div>
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => void resolveCandidate(paperId)}
                    disabled={busy || !!job.cleared_at || !candidates[paperId]}
                  >
                    关联并继续处理
                  </Button>
                </div>
              ))}
            </div>
          )}
          {job.status === "WAITING_CONFIG" &&
            (job.stage === "ANALYZE" ? (
              <p className="text-xs text-[var(--muted)]">
                需要配置 AI Provider 或资料外发权限后重试。
                <Link
                  href="/settings/literature"
                  className="ml-1 text-[var(--accent)] hover:underline"
                >
                  打开文献设置
                </Link>
              </p>
            ) : (
              <p className="text-xs text-[var(--muted)]">
                当前 Zotero 连接或来源库与任务记录不一致。核对连接后再重试。
                <Link
                  href="/integrations/zotero"
                  className="ml-1 text-[var(--accent)] hover:underline"
                >
                  查看 Zotero 连接
                </Link>
              </p>
            ))}
          {job.status === "WAITING_BUDGET" && (
            <p className="text-xs text-[var(--muted)]">
              当前 AI 额度不足。调整预算后可重试。
              <Link
                href="/settings/literature"
                className="ml-1 text-[var(--accent)] hover:underline"
              >
                查看预算设置
              </Link>
            </p>
          )}
          {job.status === "WAITING_PROVIDER_QUOTA" && (
            <p className="text-xs text-[var(--muted)]">
              Codex
              账号额度不足，已完成的分段与记录保留。账号额度恢复后可手动重试；系统不会猜测恢复时间。
            </p>
          )}
          {job.status === "WAITING_INPUT_REDUCTION" && (
            <p className="text-xs text-[var(--muted)]">
              输入超过当前可处理范围，可前往论文分析工作区选择较浅深度或调整内容。
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            <Button
              variant="secondary"
              onClick={() => void load()}
              disabled={refreshing || busy}
            >
              <RefreshCw
                className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`}
              />
              刷新
            </Button>
            {!job.cleared_at &&
              retryableStatuses.has(job.status) &&
              !(
                job.status === "FAILED" && job.candidate_paper_ids.length > 0
              ) && (
                <Button onClick={() => void runAction("retry")} disabled={busy}>
                  {busy ? "处理中…" : "重试流水线"}
                </Button>
              )}
            {canCancel && (
              <Button
                variant="ghost"
                onClick={() => void runAction("cancel")}
                disabled={busy}
              >
                取消任务
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <FileText className="h-4 w-4 text-[var(--accent)]" />
              <h2 className="font-semibold">PDF 与解析</h2>
            </div>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            {job.attachment_id ? (
              <p>PDF 已保存到 ResearchOS。</p>
            ) : (
              <p className="text-[var(--muted)]">
                {job.copy_pdf
                  ? "尚无可用的已保存 PDF。"
                  : "本任务未请求复制 PDF。"}
              </p>
            )}
            {parseJob ? (
              <div className="rounded border border-[var(--border)] p-3 text-xs">
                <p>
                  解析任务：
                  <Status value={parseJob.status} />
                </p>
                {parseJob.error_message && (
                  <p className="mt-2 text-[var(--danger)]">
                    {parseJob.error_code && `${parseJob.error_code}：`}
                    {parseJob.error_message}
                  </p>
                )}
              </div>
            ) : (
              job.copy_pdf && (
                <p className="text-xs text-[var(--muted)]">
                  复制成功后会自动创建解析任务。
                </p>
              )
            )}
            {job.paper_id && (
              <Link
                href={`/papers/${job.paper_id}/analysis`}
                className="inline-flex text-xs text-[var(--accent)] hover:underline"
              >
                打开 PDF 与解析工作区 →
              </Link>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Inbox className="h-4 w-4 text-[var(--accent)]" />
              <h2 className="font-semibold">AI 分析与人工审核</h2>
            </div>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            {analysisJob ? (
              <div className="rounded border border-[var(--border)] p-3 text-xs">
                <p>
                  {analysisJob.analysis_mode} · {analysisJob.analysis_scope} ·{" "}
                  <Status value={analysisJob.status} />
                </p>
                {analysisJob.error_message && (
                  <p className="mt-2 text-[var(--danger)]">
                    {analysisJob.error_code && `${analysisJob.error_code}：`}
                    {analysisJob.error_message}
                  </p>
                )}
              </div>
            ) : (
              <p className="text-[var(--muted)]">
                {job.request_analysis
                  ? "尚未创建 AI 分析任务。"
                  : "本任务未请求 AI 分析。"}
              </p>
            )}
            {job.inbox_item_id ? (
              <Link
                href="/inbox"
                className="inline-flex text-xs text-[var(--accent)] hover:underline"
              >
                打开 Research Inbox 审核笔记 →
              </Link>
            ) : (
              job.request_analysis && (
                <p className="text-xs text-[var(--muted)]">
                  分析成功后，笔记会进入 Research Inbox 等待审核。
                </p>
              )
            )}
          </CardContent>
        </Card>
      </div>
      {job.paper_id && (
        <Link
          href={`/papers/${job.paper_id}`}
          className="inline-flex items-center gap-2 text-sm text-[var(--accent)] hover:underline"
        >
          <BookOpen className="h-4 w-4" />
          查看已导入论文
        </Link>
      )}
    </div>
  );
}
