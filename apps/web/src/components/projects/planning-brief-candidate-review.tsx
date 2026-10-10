"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { api } from "@/lib/api";
import { briefSections } from "./research-brief-editor";
import type { components } from "@/lib/generated";

type Job = components["schemas"]["PlanningJobOut"];
type Proposal = components["schemas"]["PlanningBriefProposalOut"];
type Preview = components["schemas"]["PlanningBriefAdoptionPreviewOut"];
type PreviewCreate =
  components["schemas"]["PlanningBriefAdoptionPreviewCreate"];
type Adoption = components["schemas"]["PlanningBriefAdoptionOut"];
type Brief = components["schemas"]["ResearchBriefDetailOut"];
type BriefPage = components["schemas"]["ResearchBriefPage"];
type SectionKey = (typeof briefSections)[number][0];

export function PlanningBriefCandidateReview({
  job,
  disabled,
}: {
  job: Job;
  disabled: boolean;
}) {
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [base, setBase] = useState<Brief | null>(null);
  const [selected, setSelected] = useState<SectionKey[]>([]);
  const [includeStop, setIncludeStop] = useState(false);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [acknowledgeStale, setAcknowledgeStale] = useState(false);
  const [saved, setSaved] = useState<Adoption | null>(null);
  const [visible, setVisible] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const busyRef = useRef(false);
  const nonce = useRef<{ signature: string; key: string } | null>(null);
  const endpoint = `/projects/${job.project_id}/planning-jobs/${job.id}`;
  const canRead =
    job.status === "COMPLETED" && job.result?.disposition === "AVAILABLE";

  function begin() {
    if (busyRef.current || disabled) return false;
    busyRef.current = true;
    setBusy(true);
    setError("");
    return true;
  }
  function end() {
    busyRef.current = false;
    setBusy(false);
  }
  function changed() {
    setPreview(null);
    setAcknowledgeStale(false);
    setSaved(null);
    nonce.current = null;
  }
  async function read() {
    if (!canRead || !begin()) return;
    setVisible(true);
    setPreview(null);
    setAcknowledgeStale(false);
    try {
      const result = await api.get<Proposal>(`${endpoint}/brief-proposal`);
      setProposal(result);
      if (result.adoptable) {
        const current = await api.get<BriefPage>(
          `/projects/${job.project_id}/research-briefs?limit=1`,
        );
        if (!current.items.length) {
          setBase(null);
          return;
        }
        setBase(
          await api.get<Brief>(
            `/projects/${job.project_id}/research-briefs/${current.items[0].id}`,
          ),
        );
      }
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "候选或最新任务书暂不可读",
      );
    } finally {
      end();
    }
  }
  function requestBody(): PreviewCreate | null {
    if (
      !proposal?.adoptable ||
      !base ||
      !proposal.result_sha256 ||
      !proposal.proposal_sha256 ||
      (!selected.length && !includeStop)
    )
      return null;
    return {
      base_brief_id: base.id,
      expected_base_sha256: base.sha256,
      selected_section_keys: selected,
      include_stop_rules: includeStop,
      expected_result_sha256: proposal.result_sha256,
      expected_proposal_sha256: proposal.proposal_sha256,
    };
  }
  async function previewChanges() {
    const body = requestBody();
    if (!canRead || !body || !begin()) return;
    setPreview(null);
    setAcknowledgeStale(false);
    setSaved(null);
    try {
      setPreview(
        await api.post<Preview>(`${endpoint}/brief-adoption-preview`, body),
      );
    } catch (cause) {
      setError(
        (cause instanceof Error ? cause.message : "差异预览失败") +
          "。选择保留，请核对最新基础版本。",
      );
    } finally {
      end();
    }
  }
  async function adopt() {
    const body = requestBody();
    if (
      !canRead ||
      !body ||
      !preview?.effective_changes ||
      (preview.source_stale && !acknowledgeStale) ||
      !begin()
    )
      return;
    const signature = JSON.stringify({
      ...body,
      acknowledge_stale_context: acknowledgeStale,
    });
    if (nonce.current?.signature !== signature)
      nonce.current = { signature, key: crypto.randomUUID() };
    try {
      const result = await api.post<Adoption>(`${endpoint}/adopt-brief`, {
        ...body,
        acknowledge_stale_context: acknowledgeStale,
        idempotency_key: nonce.current.key,
      } satisfies components["schemas"]["PlanningBriefAdoptionCreate"]);
      setSaved(result);
    } catch (cause) {
      setError(
        (cause instanceof Error ? cause.message : "候选保存失败") +
          "。选择及说明保留；同一请求重试复用原请求编号。",
      );
    } finally {
      end();
    }
  }

  if (!job.result) return null;
  if (!canRead)
    return (
      <p className="text-xs text-[var(--muted)]">
        当前结果仅供原文与回执核对；隔离、未完成或未知结果不能采用为任务书。
      </p>
    );
  return (
    <section
      aria-label="规划摘录择项审阅"
      className="space-y-3 rounded border border-[var(--border)] p-3 text-xs"
    >
      <h4 className="font-semibold">规划原文摘录 → 新任务书草稿</h4>
      <p className="leading-5 text-[var(--muted)]">
        摘录来自上述原专业 Skill Markdown，属于 AI
        建议，不是论文作者事实或实测结果。本人明确选择的内容仅保存到新
        DRAFT，旧版本、未选段、Idea、文献快照及旧审阅保留。
      </p>
      <Button
        size="sm"
        variant="secondary"
        disabled={disabled || busy}
        onClick={() => void read()}
      >
        {busy
          ? "正在读取或保存…"
          : visible
            ? "重新读取候选与最新任务书"
            : "查看规范摘录候选"}
      </Button>
      {busy && <LoadingState label="正在处理冻结候选与版本…" />}
      {error && (
        <div role="alert" aria-label="候选采用失败">
          <ErrorState message={error} />
        </div>
      )}
      {visible && proposal && (
        <>
          <dl className="space-y-2">
            <div>
              <dt className="text-[var(--muted)]">规范候选状态</dt>
              <dd>{proposal.normalization_status}</dd>
            </div>
            <div>
              <dt className="text-[var(--muted)]">实际来源任务 / Attempt</dt>
              <dd className="break-all font-mono">
                {proposal.job_id} / {proposal.attempt_id || "未记录"}
              </dd>
            </div>
            <div>
              <dt className="text-[var(--muted)]">原产物 / 规范候选 SHA-256</dt>
              <dd className="break-all font-mono">
                {proposal.result_sha256 || "未记录"}
                <br />
                {proposal.proposal_sha256 || "未记录"}
              </dd>
            </div>
          </dl>
          {proposal.normalization_issue && (
            <p className="break-words text-[var(--danger)]">
              {proposal.normalization_issue}
            </p>
          )}
          {proposal.warnings.map((warning, index) => (
            <p key={`w:${index}`} className="text-[var(--muted)]">
              {warning}
            </p>
          ))}
          {proposal.gaps.map((gap, index) => (
            <p key={`g:${index}`} className="text-[var(--muted)]">
              {gap}
            </p>
          ))}
          {!proposal.adoptable ? (
            <p className="leading-5 text-[var(--muted)]">
              未记录可采用的规范摘录，或候选未通过核验。保留原
              Markdown；不会补造格式、重新解析固定标题或重跑模型。
            </p>
          ) : !base ? (
            <EmptyState
              title="没有当前基础任务书"
              detail="先创建任务书草稿，再读取可采用摘录。"
            />
          ) : (
            <>
              <p className="break-all">
                最新基础版本 {base.revision} · {base.id} · SHA-256 {base.sha256}
              </p>
              <fieldset className="space-y-2">
                <legend className="font-semibold">明确选择要替换的段落</legend>
                {proposal.sections.map((section) => {
                  const title =
                    briefSections.find(([key]) => key === section.key)?.[1] ||
                    section.key;
                  const current = base.sections.find(
                    (item) => item.key === section.key,
                  );
                  return (
                    <div
                      key={section.key}
                      className="space-y-2 rounded border border-[var(--border)] p-3"
                    >
                      <label className="flex items-center gap-2">
                        <input
                          aria-label={`采用摘录：${title}`}
                          type="checkbox"
                          checked={selected.includes(section.key)}
                          disabled={
                            disabled || busy || !section.content || !!saved
                          }
                          onChange={(event) => {
                            setSelected((old) =>
                              event.target.checked
                                ? [...old, section.key]
                                : old.filter((key) => key !== section.key),
                            );
                            changed();
                          }}
                        />
                        {title}
                      </label>
                      {current?.origin_type === "OWNER_INPUT" && (
                        <p className="text-amber-700 dark:text-amber-300">
                          此段已有本人输入，默认不选；选择将仅替换新版本中的该段，原版本保留。
                        </p>
                      )}
                      <p className="whitespace-pre-wrap break-words leading-5">
                        {section.content || "原文未提供这部分摘录。"}
                      </p>
                      {section.content && (
                        <p className="text-[var(--muted)]">
                          原 Markdown 字符区间 [{section.source_start},{" "}
                          {section.source_end}) ·{" "}
                          {section.uncertainty || "AI 建议，仍需本人判断"}
                        </p>
                      )}
                    </div>
                  );
                })}
              </fieldset>
              {proposal.stop_rules_quote && (
                <div className="space-y-2 rounded border border-[var(--border)] p-3">
                  <label className="flex items-center gap-2">
                    <input
                      aria-label="采用停止规则摘录"
                      type="checkbox"
                      checked={includeStop}
                      disabled={disabled || busy || !!saved}
                      onChange={(event) => {
                        setIncludeStop(event.target.checked);
                        changed();
                      }}
                    />
                    停止规则摘录
                  </label>
                  <p className="whitespace-pre-wrap break-words">
                    {proposal.stop_rules_quote}
                  </p>
                  <p className="text-[var(--muted)]">
                    原 Markdown 字符区间 [{proposal.stop_source_start},{" "}
                    {proposal.stop_source_end})
                  </p>
                </div>
              )}
              <Button
                size="sm"
                variant="secondary"
                disabled={
                  disabled ||
                  busy ||
                  (!selected.length && !includeStop) ||
                  !!saved
                }
                onClick={() => void previewChanges()}
              >
                预览所选摘录与当前版本差异
              </Button>
              {preview && (
                <section
                  aria-label="候选采用差异"
                  className="space-y-3 rounded border border-[var(--border)] p-3"
                >
                  <h5 className="font-semibold">新版本差异预览</h5>
                  <p className="break-all font-mono">
                    基础 SHA-256：{preview.base_sha256}
                    <br />
                    原产物 SHA-256：{preview.result_sha256}
                    <br />
                    规范候选 SHA-256：{preview.proposal_sha256}
                  </p>
                  {preview.diffs.map((diff) => (
                    <div
                      key={diff.key}
                      className="space-y-2 rounded bg-[var(--surface)] p-3"
                    >
                      <h6 className="font-medium">
                        {briefSections.find(([key]) => key === diff.key)?.[1] ||
                          diff.key}
                      </h6>
                      {diff.overwrites_owner_input && (
                        <p className="text-amber-700 dark:text-amber-300">
                          将替换新版本中的已有本人输入；旧版内容与审阅继续保留。
                        </p>
                      )}
                      <p className="whitespace-pre-wrap break-words">
                        当前：{diff.current_content || "未填写"}
                      </p>
                      <p className="whitespace-pre-wrap break-words">
                        拟采用：{diff.proposed_content}
                      </p>
                    </div>
                  ))}
                  {preview.warnings.map((warning, index) => (
                    <p key={`pw:${index}`} className="text-[var(--muted)]">
                      {warning}
                    </p>
                  ))}
                  {preview.gaps.map((gap, index) => (
                    <p key={`pg:${index}`} className="text-[var(--muted)]">
                      {gap}
                    </p>
                  ))}
                  {preview.source_stale && (
                    <label className="flex items-start gap-2 leading-5 text-amber-700 dark:text-amber-300">
                      <input
                        aria-label="知悉原规划上下文已经变化"
                        type="checkbox"
                        checked={acknowledgeStale}
                        disabled={disabled || busy || !!saved}
                        onChange={(event) => {
                          setAcknowledgeStale(event.target.checked);
                          nonce.current = null;
                        }}
                      />
                      我已知悉原规划基于旧上下文，仍选择上述摘录作为新版本的 AI
                      建议。
                    </label>
                  )}
                  {!preview.effective_changes && (
                    <p className="text-[var(--muted)]">
                      没有有效文字变化；不会创建空版本。
                    </p>
                  )}
                  <Button
                    disabled={
                      disabled ||
                      busy ||
                      !preview.effective_changes ||
                      (preview.source_stale && !acknowledgeStale) ||
                      !!saved
                    }
                    onClick={() => void adopt()}
                  >
                    保存所选摘录为新任务书草稿
                  </Button>
                </section>
              )}
              {saved && (
                <div
                  className="space-y-2 rounded border border-[var(--accent)] p-3"
                  role="status"
                >
                  <p>
                    已保存新任务书版本 {saved.brief.revision} ·
                    DRAFT；未自动接受、授予执行权限或启动模型。
                  </p>
                  <p className="break-all font-mono">
                    采用回执：{saved.receipt.id} · 新版本 SHA-256：
                    {saved.brief.sha256}
                  </p>
                  <Link
                    className="text-[var(--accent)] underline"
                    href={`/projects/${job.project_id}/brief?version=${saved.brief.id}`}
                  >
                    查看新任务书草稿及 AI 来源
                  </Link>
                </div>
              )}
            </>
          )}
        </>
      )}
    </section>
  );
}
