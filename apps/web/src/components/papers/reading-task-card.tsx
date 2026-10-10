"use client";
import { PDFReadingSourcePanel } from "./direct-pdf-reading";
import { ReadingResultEnvelopePanel } from "./reading-result-envelope";
import { AnalysisResultIssues } from "@/components/literature/analysis-result-issues";
import { Button } from "@/components/ui/button";
import type { AnalysisJob, AutomationSettings, ResearchNote } from "@/lib/api";
export const analysisStatusLabels: Record<string, string> = {
  QUEUED: "等待执行",
  ANALYZING: "正在分析",
  RETRY_WAIT: "等待重试",
  WAITING_CONFIG: "等待配置",
  WAITING_BUDGET: "等待预算",
  WAITING_PROVIDER_QUOTA: "等待 Codex 账号额度",
  WAITING_INPUT_REDUCTION: "等待调整输入",
  COMPLETED: "分析完成",
  FAILED: "分析失败",
  CANCELLED: "已取消",
  NEEDS_ATTENTION: "需要核查调用结果",
};
export function requiresUncertainAcknowledgement(job: AnalysisJob) {
  return (
    job.status === "NEEDS_ATTENTION" ||
    (job.status === "CANCELLED" &&
      [
        "ANALYSIS_OUTCOME_UNCERTAIN",
        "PART_RESULT_UNCERTAIN",
        "PART_OUTCOME_UNCERTAIN",
      ].includes(job.error_code ?? ""))
  );
}
export function usesCurrentReadingSkill(job: AnalysisJob) {
  return (
    job.source_type === "PDF" &&
    Boolean(job.approval_plan_id) &&
    job.uses_current_reading_skill === true
  );
}

export function ReadingTaskCard({
  job,
  settings,
  busy,
  note,
  acknowledgedJobId,
  setAcknowledgedJobId,
  retryJob,
  cancelJob,
  retryUncertainJob,
  load,
}: {
  job: AnalysisJob;
  settings: AutomationSettings | null;
  busy: boolean;
  note?: ResearchNote;
  acknowledgedJobId: string | null;
  setAcknowledgedJobId: (id: string | null) => void;
  retryJob: (id: string) => Promise<void>;
  cancelJob: (id: string) => Promise<void>;
  retryUncertainJob: (id: string) => Promise<void>;
  load: () => Promise<void>;
}) {
  if (!usesCurrentReadingSkill(job)) return null;
  return (
    <div
      data-testid={`reading-task-${job.id}`}
      className="space-y-2 rounded border border-[var(--border)] p-2 text-xs"
    >
      <div className="flex justify-between gap-2">
        <span>Skill 精读 · {job.analysis_mode} · 原始 PDF 完整页面</span>
        <span
          className={
            job.status === "COMPLETED"
              ? "text-emerald-500"
              : "text-[var(--muted)]"
          }
        >
          {analysisStatusLabels[job.status] ?? job.status}
        </span>
      </div>
      {job.source_type === "PDF" && (
        <PDFReadingSourcePanel
          compact
          jobId={job.id}
          researchNoteId={note?.id}
          completed={job.status === "COMPLETED"}
        />
      )}
      {job.part_count > 0 && (
        <div>
          <p className="text-[var(--muted)]">
            分段进度：已完成 {job.parts_completed}/{job.part_count}
          </p>
          <progress
            aria-label={`分析任务 ${job.id} 的分段进度`}
            value={job.parts_completed}
            max={job.part_count}
            className="mt-1 h-1.5 w-full accent-[var(--accent)]"
          />
        </div>
      )}
      {job.source_type === "PDF" &&
      job.approval_plan_id &&
      job.status === "WAITING_PROVIDER_QUOTA" ? (
        <p className="text-amber-700 dark:text-amber-300">
          Codex
          返回额度不足。已完成的分段与记录保留；账号额度恢复后可手动重试，系统不会猜测恢复时间。
        </p>
      ) : (
        job.source_type === "PDF" &&
        job.approval_plan_id &&
        job.status.startsWith("WAITING_") && (
          <p className="text-amber-700 dark:text-amber-300">
            {job.attempt_count === 0
              ? "任务已保存，尚未调用 AI。请按原因调整设置后重试。"
              : "后续分析正在等待，已完成的分段与记录保留。请按原因调整设置后重试。"}
          </p>
        )
      )}
      {(job.error_message || job.error_code) && (
        <p
          className={
            job.status.startsWith("WAITING_")
              ? "text-amber-700 dark:text-amber-300"
              : "text-[var(--danger)]"
          }
        >
          {job.error_message || job.error_code}
        </p>
      )}
      {job.status === "FAILED" &&
        [
          "AI_INVALID_EVIDENCE",
          "ANALYTICAL_NOTE_INVALID",
          "ANALYTICAL_NOTE_ASSET_UNVERIFIED",
          "AI_INVALID_OUTPUT",
        ].includes(job.error_code ?? "") && (
          <AnalysisResultIssues
            key={job.id + "-" + job.attempt_count}
            jobId={job.id}
            allowRestore={job.source_type === "PDF" && !!job.approval_plan_id}
            onRestored={load}
          />
        )}
      {requiresUncertainAcknowledgement(job) && (
        <AnalysisResultIssues
          key={job.id + "-interruption-" + job.attempt_count}
          jobId={job.id}
          view="interruption"
          allowRestore={
            job.status === "NEEDS_ATTENTION" &&
            job.source_type === "PDF" &&
            !!job.approval_plan_id
          }
          onRestored={load}
        />
      )}
      {job.status === "COMPLETED" &&
        job.source_type === "PDF" &&
        job.approval_plan_id && (
          <AnalysisResultIssues jobId={job.id} view="interruption" />
        )}
      <div className="flex flex-wrap gap-2">
        {[
          "FAILED",
          "RETRY_WAIT",
          "WAITING_CONFIG",
          "WAITING_BUDGET",
          "WAITING_PROVIDER_QUOTA",
          "WAITING_INPUT_REDUCTION",
          "CANCELLED",
        ].includes(job.status) &&
          job.source_type === "PDF" &&
          job.approval_plan_id &&
          !requiresUncertainAcknowledgement(job) &&
          job.model_key !== "unconfigured" && (
            <Button
              size="sm"
              variant="secondary"
              disabled={busy}
              onClick={() => retryJob(job.id)}
            >
              重试
            </Button>
          )}
        {[
          "QUEUED",
          "WAITING_CONFIG",
          "WAITING_BUDGET",
          "WAITING_PROVIDER_QUOTA",
          "RETRY_WAIT",
          "NEEDS_ATTENTION",
        ].includes(job.status) &&
          job.source_type === "PDF" && (
            <Button
              size="sm"
              variant="ghost"
              disabled={busy}
              onClick={() => cancelJob(job.id)}
            >
              取消
            </Button>
          )}
      </div>
      {job.source_type === "PDF" &&
        job.approval_plan_id &&
        requiresUncertainAcknowledgement(job) && (
          <div className="space-y-2 rounded border border-amber-500/30 p-2">
            <p className="text-amber-700 dark:text-amber-300">
              {job.provider_key === "codex"
                ? "上次 Codex 调用的完整结果未确认，可能已经消耗账号额度。已完成分段保留；确认后仅继续未确认的调用及后续分段。"
                : "上次模型调用的结果不明，可能已经产生费用。检查外部账单后，可明确同意重新执行这次调用。"}
            </p>
            <label className="flex items-start gap-2">
              <input
                type="checkbox"
                checked={acknowledgedJobId === job.id}
                onChange={(event) =>
                  setAcknowledgedJobId(event.target.checked ? job.id : null)
                }
              />
              <span>
                {job.provider_key === "codex"
                  ? "我理解重新执行可能再次消耗账号额度"
                  : "我理解重新执行可能重复计费"}
              </span>
            </label>
            <Button
              size="sm"
              variant="secondary"
              disabled={busy || acknowledgedJobId !== job.id}
              onClick={() => retryUncertainJob(job.id)}
            >
              {job.provider_key === "codex"
                ? "确认并继续未完成分段"
                : "确认并重试"}
            </Button>
          </div>
        )}
      <details className="rounded border border-[var(--border)] p-2">
        <summary className="cursor-pointer text-[var(--accent)]">
          执行记录与用量
        </summary>
        <div className="mt-2 space-y-2">
          <ReadingResultEnvelopePanel jobId={job.id} status={job.status} />
          <p className="text-[var(--muted)]">
            模型：{job.model_key}
            {job.reasoning_effort
              ? ` · 推理强度 ${job.reasoning_effort}`
              : " · 推理强度未记录"}
          </p>
          <p className="text-[var(--muted)]">
            已报告{" "}
            {job.input_tokens === null || job.output_tokens === null
              ? "用量未知"
              : `${job.input_tokens + job.output_tokens} Token`}{" "}
            {job.provider_key === "codex" &&
            settings?.budget_mode === "PROVIDER_QUOTA"
              ? "（非剩余额度）"
              : " · 预留 " +
                job.reserved_tokens +
                " Token · 费用 " +
                (job.cost_estimate === null
                  ? "未知"
                  : job.cost_estimate + " " + (job.cost_currency ?? ""))}
          </p>
        </div>
      </details>
    </div>
  );
}
