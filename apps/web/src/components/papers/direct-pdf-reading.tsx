"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { LoaderCircle, BookOpen } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ErrorState } from "@/components/ui/state";
import { CanonicalNotePanel } from "./canonical-note";
import { ReadingPlanSources } from "./reading-plan-sources";
import {
  api,
  ApiError,
  type AICapabilities,
  type AnalysisJob,
  type AutomationSettings,
  type PaperAttachment,
  type PDFReadingJobCreate,
  type PDFReadingSource,
  type ReadingPlan,
  type ReadingPlanCreate,
} from "@/lib/api";

export function DirectPDFReading({
  paperId,
  attachment,
  capabilities,
  settings,
  disabled,
  onBusyChange,
  onSubmitted,
}: {
  paperId: string;
  attachment?: PaperAttachment;
  capabilities: AICapabilities | null;
  settings: AutomationSettings | null;
  disabled: boolean;
  onBusyChange: (busy: boolean) => void;
  onSubmitted: (job: AnalysisJob) => Promise<void>;
}) {
  const [collection, setCollection] = useState("未分类");
  const [plan, setPlan] = useState<ReadingPlan | null>(null);
  const [approved, setApproved] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const key = useRef<{ plan: string; nonce: string } | null>(null);
  const missingPermission = settings?.cloud_scope !== "FULL_TEXT";
  async function preview() {
    if (!attachment?.attachment_id || disabled || previewing || submitting)
      return;
    setPreviewing(true);
    onBusyChange(true);
    setError("");
    setPlan(null);
    setApproved(false);
    try {
      const body: ReadingPlanCreate = {
        attachment_id: attachment.attachment_id,
        collection: collection.trim(),
      };
      setPlan(
        await api.post<ReadingPlan>(
          `/papers/${encodeURIComponent(paperId)}/reading-plans`,
          body,
        ),
      );
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "无法预览论文精读计划");
    } finally {
      setPreviewing(false);
      onBusyChange(false);
    }
  }
  async function submit() {
    if (
      !attachment?.attachment_id ||
      !plan ||
      !approved ||
      submitting ||
      disabled
    )
      return;
    setSubmitting(true);
    onBusyChange(true);
    setError("");
    const storageKey = "researchos.approved-pdf-reading." + plan.id;
    try {
      if (key.current?.plan !== plan.id) {
        let saved: string | null = null;
        try {
          saved = sessionStorage.getItem(storageKey);
        } catch {
          /* Request key remains in current page. */
        }
        key.current = {
          plan: plan.id,
          nonce:
            saved && /^[0-9a-f-]{36}$/.test(saved)
              ? saved
              : crypto.randomUUID(),
        };
      }
      try {
        sessionStorage.setItem(storageKey, key.current.nonce);
      } catch {
        /* Storage may be disabled. */
      }
      const body: PDFReadingJobCreate = {
        attachment_id: attachment.attachment_id,
        approval_plan_id: plan.id,
        expected_plan_sha256: plan.plan_sha256,
        approved: true,
        idempotency_key: key.current.nonce,
      };
      const job = await api.post<AnalysisJob>(
        `/papers/${encodeURIComponent(paperId)}/pdf-reading-jobs`,
        body,
      );
      key.current = null;
      try {
        sessionStorage.removeItem(storageKey);
      } catch {
        /* Durable receipt exists. */
      }
      setApproved(false);
      setPlan(null);
      await onSubmitted(job);
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 409) {
        setPlan(null);
        setApproved(false);
        key.current = null;
        setError(
          cause.message + "。请重新预览并批准当前来源、模板与保存目标。",
        );
      } else
        setError(
          (cause instanceof Error ? cause.message : "精读提交失败") +
            "。再次批准同一计划会复用本次请求编号。",
        );
    } finally {
      setSubmitting(false);
      onBusyChange(false);
    }
  }
  return (
    <section
      className="space-y-3 rounded-md border border-[var(--accent)]/30 bg-[var(--accent)]/5 p-3"
      aria-label="原始 PDF 技能精读"
    >
      <h3 className="flex items-center gap-2 text-sm font-semibold">
        <BookOpen className="h-4 w-4 text-[var(--accent)]" />
        原始 PDF 技能精读
      </h3>
      <p className="text-xs leading-5 text-[var(--muted)]">
        使用 zotero-analytical-writer，直接阅读原始 PDF
        正文、图、表与公式，按你的论文精读模板生成完整
        Markdown。篇幅不限，全篇按需分段；阅读完成后统一写成最终笔记。
      </p>
      <p className="text-xs leading-5 text-[var(--muted)]">
        先核对本篇 PDF、技能、模板和保存位置，再批准精读。全局 FULL_TEXT
        权限不能代替每篇批准；不要求先整理 PDF 文本。
      </p>
      {attachment?.attachment_id ? (
        <p className="break-words text-xs">
          当前来源：{attachment.filename ?? "所选原始 PDF"} · SHA-256{" "}
          {attachment.sha256 ?? "服务端核对"}
        </p>
      ) : (
        <p className="text-xs text-[var(--muted)]">
          先上传或复制你持有的原始 PDF，再预览精读计划。
        </p>
      )}
      <label className="block space-y-1 text-xs font-medium">
        笔记分类目录
        <Input
          aria-label="笔记分类目录"
          value={collection}
          maxLength={160}
          disabled={disabled || submitting || previewing}
          placeholder="例如：多模态山火感知"
          onChange={(event) => {
            setCollection(event.target.value);
            setPlan(null);
            setApproved(false);
          }}
        />
      </label>
      <Button
        variant="secondary"
        className="w-full"
        disabled={
          disabled ||
          previewing ||
          submitting ||
          !attachment?.attachment_id ||
          !collection.trim()
        }
        onClick={() => void preview()}
      >
        {previewing ? (
          <>
            <LoaderCircle className="h-4 w-4 animate-spin" />
            预览计划中…
          </>
        ) : (
          "预览本篇精读与保存计划"
        )}
      </Button>
      {plan && (
        <div
          className="space-y-3 rounded border border-[var(--border)] bg-[var(--background)] p-3"
          aria-label="本篇精读批准计划"
        >
          <p className="text-sm font-medium">
            {plan.title} · 全文 {plan.page_count} 页
          </p>
          <p className="text-xs leading-5">
            {plan.writing_stage === "READ_ALL_PAGES_THEN_WRITE_NOTE"
              ? `覆盖 ${plan.page_batches.length} 个原始页批次，全部阅读后独立生成最终笔记。`
              : "整篇原始 PDF 一次阅读并生成最终笔记。"}{" "}
            每批页数是传输安排，不限制论文总页数。
          </p>
          <dl className="space-y-2 text-xs">
            <div>
              <dt className="text-[var(--muted)]">批准的原始 PDF SHA-256</dt>
              <dd className="break-all font-mono text-[10px]">{plan.sha256}</dd>
            </div>
            <div>
              <dt className="text-[var(--muted)]">阅读技能</dt>
              <dd>
                {plan.skill_key} v{plan.skill_version}
              </dd>
            </div>
            <div>
              <dt className="text-[var(--muted)]">本篇批准的模型与推理强度</dt>
              <dd>
                {plan.model_key} · {plan.reasoning_effort}
              </dd>
            </div>
            <div>
              <dt className="text-[var(--muted)]">模板 SHA-256</dt>
              <dd className="break-all font-mono text-[10px]">
                {plan.template_sha256}
              </dd>
            </div>
            <div>
              <dt className="text-[var(--muted)]">最终 Markdown 保存路径</dt>
              <dd className="break-all font-mono">{plan.output_path}</dd>
            </div>
          </dl>
          <p className="text-xs leading-5 text-[var(--muted)]">
            模板保留基本信息、一句话摘要、研究对象、研究方法、数据来源、研究结论、关联精读笔记、我的判断，以及方法表格和原文证据。未核实内容明确标记，最终笔记仍需人工审阅。
          </p>
          {plan.existing_file_sha256 && (
            <p
              role="status"
              className="text-xs leading-5 text-amber-700 dark:text-amber-300"
            >
              此位置已有文件（SHA-256：{plan.existing_file_sha256}
              ）。保存时校验已批准状态，人工修改或未受管理的文件会进入冲突核对。
            </p>
          )}
          <details className="text-xs">
            <summary className="cursor-pointer text-[var(--accent)]">
              核对全部页码与计划哈希
            </summary>
            <div className="mt-2 space-y-2">
              <p className="break-all font-mono text-[10px]">
                组装技能指令 SHA-256：{plan.skill_sha256}
              </p>
              <p className="break-all font-mono text-[10px]">
                批准计划 SHA-256：{plan.plan_sha256}
              </p>
              {plan.page_batches.map((batch) => (
                <p key={batch.part_index}>
                  阅读批次 {batch.part_index}：原始页码 {batch.pages.join("、")}
                </p>
              ))}
            </div>
          </details>
          <ReadingPlanSources
            key={`${plan.id}:${plan.source_manifest_sha256 ?? "legacy"}`}
            paperId={paperId}
            plan={plan}
          />
          <label className="flex items-start gap-2 text-xs leading-5">
            <input
              aria-label="批准本篇 PDF 精读及保存计划"
              type="checkbox"
              checked={approved}
              disabled={disabled || submitting}
              onChange={(event) => setApproved(event.target.checked)}
            />
            <span>
              我批准将这篇原始 PDF 交给
              Codex，按上述技能与模板精读，并保存到已核对的 Markdown 路径。
            </span>
          </label>
          <Button
            className="w-full"
            disabled={
              disabled || submitting || !approved || !settings || !capabilities
            }
            onClick={() => void submit()}
          >
            {submitting ? (
              <>
                <LoaderCircle className="h-4 w-4 animate-spin" />
                批准提交中…
              </>
            ) : (
              "批准并开始本篇精读"
            )}
          </Button>
        </div>
      )}
      {settings?.budget_mode === "PROVIDER_QUOTA" && (
        <p className="text-xs text-[var(--muted)]">
          跟随 Codex 账号额度；已报告 Token 不代表剩余额度。
        </p>
      )}
      {missingPermission && (
        <p className="text-xs text-amber-700 dark:text-amber-300">
          当前未允许 FULL_TEXT 外发。批准后的任务仍需满足外发权限才可运行。
        </p>
      )}
      {capabilities && !capabilities.available && (
        <p className="text-xs text-amber-700 dark:text-amber-300">
          {capabilities.reason_message ??
            "AI 接入当前不可调用，任务会显示明确等待原因。"}
        </p>
      )}
      {error && <ErrorState message={error} />}
    </section>
  );
}

export function PDFReadingSourcePanel({
  jobId,
  researchNoteId,
  completed = false,
  compact = false,
}: {
  jobId: string;
  researchNoteId?: string;
  completed?: boolean;
  compact?: boolean;
}) {
  const [source, setSource] = useState<PDFReadingSource | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    setLoading(true);
    try {
      setSource(
        await api.get<PDFReadingSource>(
          "/analysis-jobs/" + encodeURIComponent(jobId) + "/pdf-source",
        ),
      );
      setError("");
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "无法读取原始 PDF 来源",
      );
    } finally {
      setLoading(false);
    }
  }, [jobId]);
  useEffect(() => {
    queueMicrotask(() => void load());
  }, [load]);
  return (
    <div className="space-y-2 rounded border border-[var(--border)] p-2 text-xs">
      <details open={!compact}>
        <summary className="cursor-pointer text-[var(--accent)]">
          核对已批准的原始 PDF 来源
        </summary>
        {loading && !source ? (
          <p role="status" className="text-[var(--muted)]">
            正在读取原始 PDF 来源…
          </p>
        ) : (
          source && (
            <>
              <p className="font-medium">原始 PDF · {source.page_count} 页</p>
              <p className="text-[var(--muted)]">
                阅读技能：{source.skill_key} v{source.skill_version}
              </p>
              <details>
                <summary className="cursor-pointer text-[var(--accent)]">
                  查看原始页码与技能版本
                </summary>
                <div className="mt-2 space-y-2">
                  <p className="break-all font-mono text-[10px]">
                    PDF SHA-256：{source.sha256}
                  </p>
                  <p className="break-all font-mono text-[10px]">
                    技能 SHA-256：{source.skill_sha256}
                  </p>
                  <p className="text-[var(--muted)]">
                    页面渲染：{source.render_version}
                  </p>
                  {source.page_batches.map((batch) => (
                    <p key={batch.part_index}>
                      分段 {batch.part_index}：原始页码 {batch.pages.join("、")}{" "}
                      ·{" "}
                      <a
                        href={
                          "/api/v1/attachments/" +
                          source.attachment_id +
                          "/download#page=" +
                          batch.pages[0]
                        }
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-[var(--accent)] hover:underline"
                      >
                        核对原始页面 →
                      </a>
                    </p>
                  ))}
                </div>
              </details>
              {compact && (
                <p className="text-[var(--muted)]">
                  以上来源属于此任务；切换当前 PDF 不会改变已批准来源。
                </p>
              )}
            </>
          )
        )}
      </details>
      {error && <ErrorState message={error} onRetry={() => void load()} />}
      {completed && source?.skill_key === "zotero-analytical-writer" && (
        <CanonicalNotePanel jobId={jobId} researchNoteId={researchNoteId} />
      )}
    </div>
  );
}
