"use client";

import { useState } from "react";
import { LoaderCircle, ShieldAlert } from "lucide-react";

import { Button } from "@/components/ui/button";
import { api, type AnalysisJob, type AnalysisResultIssue } from "@/lib/api";

const pageSize = 20;
const sectionLabels: Record<string, string> = {
  analytical_note: "完整模板精读笔记",
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
  reproduction: "复现线索",
  research_inspiration: "科研启发",
};
const diagnosticLabels: Record<string, string> = {
  validation_reason: "校验原因",
  note_section: "候选笔记章节",
  evidence_index: "证据索引",
  source_section: "模型给出的来源章节",
  source_page: "模型给出的页码",
  source_block_index: "模型给出的区块编号",
  quote_match_count: "原文匹配数量",
};
const interruptionLabels: Record<string, string> = {
  failure_reason: "中断原因",
  call_stage: "调用阶段",
  elapsed_seconds: "已等待时间",
  timeout_seconds: "此调用的等待上限",
  exception_type: "中断类型",
};
const reasonLabels: Record<string, string> = {
  CLIENT_DEADLINE: "等待模型返回超时",
  ADAPTER_GUARD_DEADLINE: "执行器等待超时",
  STREAM_INTERRUPTED: "模型响应连接中断",
  TOOL_ACTIVITY: "模型尝试使用禁用工具，调用已中断",
  OUTPUT_SOFT_LIMIT: "触及该次调用的输出软上限",
  OUTPUT_SIZE_LIMIT: "返回内容超过保存大小限制",
  INCOMPLETE_TURN: "模型未返回可确认的完整结果",
  PROVIDER_QUOTA: "Codex 账号额度不足",
  PROVIDER_RATE_LIMIT: "Codex 返回速率限制",
};
const stageLabels: Record<string, string> = {
  PREPARING: "准备分析运行环境",
  PREFLIGHT: "检查账号、模型与运行权限",
  THREAD_START: "创建分析会话",
  TURN_SUBMISSION: "提交模型请求",
  STREAMING: "等待模型分析结果",
  RESULT_CHECK: "检查模型返回结果",
};

function diagnosticValue(key: string, value: string): string {
  if (key === "note_section") return sectionLabels[value] ?? value;
  if (key === "failure_reason") return reasonLabels[value] ?? value;
  if (key === "call_stage") return stageLabels[value] ?? value;
  if (key === "elapsed_seconds" || key === "timeout_seconds") {
    const seconds = Number(value);
    if (Number.isFinite(seconds) && seconds >= 0)
      return seconds.toFixed(1) + " 秒";
  }
  return value;
}

function reportedTokens(value: unknown): string {
  return typeof value === "number" && Number.isInteger(value) && value >= 0
    ? value.toLocaleString()
    : "未报告";
}

function scalarText(value: unknown): string | null {
  if (
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  )
    return String(value);
  return null;
}

function omittedText(reason: string | null) {
  if (reason === "NOT_RECORDED")
    return "此历史调用未记录原始候选内容，无法恢复；失败与用量记录仍保留。";
  if (reason === "SIZE_LIMIT") return "候选内容超过保存大小限制，未保留正文。";
  if (reason === "INVALID_SCHEMA_OR_SERIALIZATION")
    return "候选内容未满足保存结构，无法显示正文。";
  return "这次失败没有可显示的原始候选内容。";
}

function IssueReceipt({
  issue,
  allowRestore,
  restoring,
  onRestore,
}: {
  issue: AnalysisResultIssue;
  allowRestore: boolean;
  restoring: boolean;
  onRestore: (issue: AnalysisResultIssue) => void;
}) {
  const uncertain = issue.event_type === "paper.analysis_outcome_uncertain";
  const hasFinalCandidate =
    issue.event_type === "paper.analysis_result_unusable" &&
    !issue.candidate_result_truncated &&
    issue.candidate_result?.sections.length === 1 &&
    issue.candidate_result.sections[0].section_key === "analytical_note" &&
    !!issue.candidate_result.sections[0].body_markdown &&
    /^[0-9a-f]{64}$/i.test(issue.candidate_result_sha256 ?? "");
  const diagnostics = Object.entries(
    uncertain ? interruptionLabels : diagnosticLabels,
  ).flatMap(([key, label]) => {
    const value = scalarText(issue.diagnostics?.[key]);
    if (value === null) return [];
    return [
      {
        key,
        label,
        value: diagnosticValue(key, value),
      },
    ];
  });

  return (
    <article className="space-y-3 rounded border border-[var(--border)] p-3">
      <p className="font-medium">
        {uncertain
          ? "调用结果未确认"
          : issue.revalidated_at
            ? "原失败回执（候选已重新校验）"
            : "未通过模板/证据校验"}
      </p>
      <div className="space-y-1 text-[var(--muted)]">
        <p>
          {issue.part_index === null
            ? "整篇调用"
            : "分段编号 " + issue.part_index}
          {" · 第 " + issue.attempt + " 次调用"}
        </p>
        <p>{new Date(issue.occurred_at).toLocaleString("zh-CN")}</p>
      </div>
      {issue.error_code && <p className="font-medium">{issue.error_code}</p>}
      {issue.error_message && (
        <p className="break-words">{issue.error_message}</p>
      )}
      {diagnostics.length > 0 ? (
        <div className="space-y-2">
          <h4 className="font-medium">
            {uncertain ? "已保存的中断详情" : "失败定位（供核对）"}
          </h4>
          <dl className="space-y-1">
            {diagnostics.map((diagnostic) => (
              <div key={diagnostic.key} className="break-words">
                <dt className="inline text-[var(--muted)]">
                  {diagnostic.label}：
                </dt>
                <dd className="inline">{diagnostic.value}</dd>
              </div>
            ))}
          </dl>
          <p className="text-[var(--muted)]">
            {uncertain
              ? "该记录描述这次调用发生的中断，不能确认模型是否在服务端完成。"
              : "以上为失败时的定位信息，不能作为有效原文引用。请对照左侧 PDF 和解析章节核查。"}
          </p>
        </div>
      ) : (
        <p className="text-[var(--muted)]">
          {uncertain
            ? "此历史记录未保存具体中断原因或阶段，不能推断为超时。"
            : "此记录未保留具体证据定位。"}
        </p>
      )}
      {uncertain && (
        <div className="space-y-1 text-[var(--muted)]">
          <p>
            本次调用已报告输入 Token：
            {reportedTokens(issue.reported_input_tokens)}
          </p>
          <p>
            本次调用已报告输出 Token：
            {reportedTokens(issue.reported_output_tokens)}
          </p>
          <p>只显示已保存的用量报告；完整结果与最终用量仍未确认。</p>
        </div>
      )}
      {issue.diagnostics_truncated && (
        <p className="text-amber-700 dark:text-amber-300">
          定位诊断受保存大小限制，可能不完整。
        </p>
      )}
      {issue.candidate_result ? (
        <details className="rounded border border-[var(--border)] p-2">
          <summary className="cursor-pointer font-medium">
            查看原始候选内容
          </summary>
          <div className="mt-3 space-y-3">
            <p className="font-medium text-amber-700 dark:text-amber-300">
              {uncertain
                ? "这是未确认调用保留的候选，仅供核对，尚未发布为科研笔记。"
                : issue.revalidated_at
                  ? "此候选已重新校验发布，科学内容仍需人工审阅；原失败记录保留。"
                  : "未通过模板/证据校验，仅供核对；该次失败结果未生成科研笔记。"}
            </p>
            {issue.candidate_result_truncated && (
              <p className="text-[var(--muted)]">候选内容受保存大小限制。</p>
            )}
            <div>
              <h4 className="font-medium">候选概述</h4>
              <p className="mt-1 max-h-48 overflow-y-auto whitespace-pre-wrap break-words leading-5">
                {issue.candidate_result.summary}
              </p>
            </div>
            {issue.candidate_result.sections.map((section, sectionIndex) => (
              <details
                key={section.section_key + "-" + sectionIndex}
                className="rounded border border-[var(--border)] p-2"
              >
                <summary className="cursor-pointer font-medium">
                  {sectionLabels[section.section_key] ?? section.section_key}
                </summary>
                <div className="mt-2 space-y-2">
                  <p className="text-[var(--muted)]">
                    模型标注：
                    {section.origin_type === "PAPER_REPORTED"
                      ? "论文报告"
                      : "模型解读"}
                    （未验证）
                  </p>
                  <p className="max-h-64 overflow-y-auto whitespace-pre-wrap break-words leading-5">
                    {section.body_markdown ?? "未提供候选正文。"}
                  </p>
                  {section.uncertainty && (
                    <p className="text-[var(--muted)]">
                      模型提示：{section.uncertainty}
                    </p>
                  )}
                  {(section.evidence ?? []).map((evidence, evidenceIndex) => (
                    <div
                      key={evidenceIndex}
                      className="space-y-1 border-t border-[var(--border)] pt-2"
                    >
                      <p className="font-medium">
                        候选证据 {evidenceIndex + 1}（未验证）
                      </p>
                      <p className="break-words text-[var(--muted)]">
                        {evidence.source_section ?? "未给出来源章节"}
                        {evidence.source_page === null
                          ? ""
                          : " · 页码 " + evidence.source_page}
                        {evidence.source_block_index === null
                          ? ""
                          : " · 区块 " + evidence.source_block_index}
                      </p>
                      <p className="whitespace-pre-wrap break-words leading-5">
                        {evidence.evidence_text ?? "未提供候选引用文本。"}
                      </p>
                    </div>
                  ))}
                </div>
              </details>
            ))}
            {issue.candidate_result.warnings.length > 0 && (
              <div className="space-y-1 text-[var(--muted)]">
                <h4 className="font-medium">模型返回的提示</h4>
                {issue.candidate_result.warnings.map((warning, index) => (
                  <p key={index}>{warning}</p>
                ))}
              </div>
            )}
          </div>
        </details>
      ) : (
        <p className="text-[var(--muted)]">
          {uncertain
            ? "本次调用未取得可确认的完整分析结果，无法显示完整候选正文。"
            : omittedText(issue.candidate_result_omitted_reason)}
        </p>
      )}
      {issue.candidate_result_sha256 && (
        <p className="break-all font-mono text-[10px] text-[var(--muted)]">
          已保存候选 SHA-256：{issue.candidate_result_sha256}
        </p>
      )}
      {issue.revalidated_at && (
        <p className="text-[var(--muted)]">
          已重新校验此候选：
          {new Date(issue.revalidated_at).toLocaleString("zh-CN")}。
          科学内容仍待人工审核，原失败与后续未确认调用回执保留。
          {issue.revalidation_event_id &&
            ` 重新校验回执：${issue.revalidation_event_id}`}
        </p>
      )}
      {allowRestore && hasFinalCandidate && !issue.revalidation_event_id && (
        <div className="space-y-2">
          <p className="text-[var(--muted)]">
            使用已保存的完整候选重新检查模板、来源和批准记录。通过后保存笔记；
            不调用模型，仍需人工审核科学内容。后续未确认调用与用量记录保留。
          </p>
          <Button
            size="sm"
            variant="secondary"
            disabled={restoring}
            onClick={() => onRestore(issue)}
          >
            {restoring
              ? "正在重新校验已有结果…"
              : "重新校验并保存已有结果（不调用 AI）"}
          </Button>
        </div>
      )}
    </article>
  );
}

export function AnalysisResultIssues({
  jobId,
  view = "evidence",
  allowRestore = false,
  onRestored,
}: {
  jobId: string;
  view?: "evidence" | "interruption";
  allowRestore?: boolean;
  onRestored?: () => Promise<void>;
}) {
  const interruption = view === "interruption";
  const [expanded, setExpanded] = useState(false);
  const [receipts, setReceipts] = useState<AnalysisResultIssue[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [nextOffset, setNextOffset] = useState<number | null>(0);
  const [restoring, setRestoring] = useState(false);
  const [restoreError, setRestoreError] = useState("");
  const [restoreMessage, setRestoreMessage] = useState("");

  async function restore(issue: AnalysisResultIssue) {
    if (!allowRestore || restoring || !issue.candidate_result_sha256) return;
    setRestoring(true);
    setRestoreError("");
    setRestoreMessage("");
    try {
      await api.post<AnalysisJob>(
        `/analysis-jobs/${encodeURIComponent(jobId)}/result-issues/${encodeURIComponent(issue.event_id)}/revalidate`,
        { expected_result_sha256: issue.candidate_result_sha256 },
      );
      setRestoreMessage(
        "已有结果重新校验通过，正在刷新笔记与保存回执；未调用模型。",
      );
      await onRestored?.();
    } catch (cause) {
      setRestoreError(
        cause instanceof Error ? cause.message : "已有结果重新校验失败",
      );
    } finally {
      setRestoring(false);
    }
  }

  async function fetchReceipts(offset: number) {
    if (loading) return;
    setExpanded(true);
    setLoading(true);
    setError("");
    try {
      const page = await api.get<AnalysisResultIssue[]>(
        "/analysis-jobs/" +
          encodeURIComponent(jobId) +
          "/result-issues?limit=" +
          pageSize +
          "&offset=" +
          offset,
      );
      setReceipts((current) => {
        const merged = new Map(
          (offset === 0 ? [] : current).map((receipt) => [
            receipt.event_id,
            receipt,
          ]),
        );
        for (const receipt of page) merged.set(receipt.event_id, receipt);
        return [...merged.values()];
      });
      setLoaded(true);
      setNextOffset(page.length === pageSize ? offset + pageSize : null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "无法读取调用详情");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-2">
      <Button
        size="sm"
        variant="secondary"
        disabled={loading}
        aria-expanded={expanded}
        onClick={() => {
          if (expanded) setExpanded(false);
          else if (loaded) setExpanded(true);
          else void fetchReceipts(0);
        }}
      >
        {loading ? (
          <>
            <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
            {interruption ? "读取中断详情中…" : "读取诊断中…"}
          </>
        ) : expanded ? (
          interruption ? (
            "收起中断详情"
          ) : (
            "收起失败诊断"
          )
        ) : interruption ? (
          "查看中断详情"
        ) : (
          "查看失败诊断"
        )}
      </Button>
      {expanded && (
        <section
          aria-label={interruption ? "中断详情" : "失败诊断"}
          className="space-y-3 rounded border border-amber-500/25 bg-amber-500/5 p-3"
        >
          <p className="flex items-start gap-2 font-medium text-amber-700 dark:text-amber-300">
            <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            {interruption
              ? "调用结果未确认；已完成分段已保存。"
              : "未通过模板/证据校验，仅供核对；未生成科研笔记。"}
          </p>
          {loading && (
            <p role="status" className="text-[var(--muted)]">
              正在读取已保存的诊断记录…
            </p>
          )}
          {error && (
            <div role="alert" className="space-y-2 text-[var(--danger)]">
              <p className="break-words">{error}</p>
              <Button
                size="sm"
                variant="secondary"
                disabled={loading}
                onClick={() =>
                  void fetchReceipts(loaded ? (nextOffset ?? 0) : 0)
                }
              >
                {interruption ? "重新加载中断详情" : "重新加载诊断"}
              </Button>
            </div>
          )}
          {restoreError && (
            <p role="alert" className="break-words text-[var(--danger)]">
              {restoreError}
            </p>
          )}
          {restoreMessage && <p role="status">{restoreMessage}</p>}
          {receipts.map((issue) => (
            <IssueReceipt
              key={issue.event_id}
              issue={issue}
              allowRestore={allowRestore}
              restoring={restoring}
              onRestore={(receipt) => void restore(receipt)}
            />
          ))}
          {loaded && !loading && !error && receipts.length === 0 && (
            <p className="text-[var(--muted)]">
              {interruption
                ? "此任务没有已保存的中断详情，不能从当前等待状态推断具体原因。"
                : "此任务没有已保存的失败诊断记录，无法恢复未记录的候选内容。"}
            </p>
          )}
          {loaded && nextOffset !== null && (
            <Button
              size="sm"
              variant="secondary"
              disabled={loading}
              onClick={() => void fetchReceipts(nextOffset)}
            >
              加载较早的诊断
            </Button>
          )}
        </section>
      )}
    </div>
  );
}
