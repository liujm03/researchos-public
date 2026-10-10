"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { api } from "@/lib/api";
import type { components } from "@/lib/generated";

type Envelope = components["schemas"]["ReadingResultEnvelopeOut"];
const proposalLabels: Record<Envelope["completion_proposal"], string> = {
  NEEDS_HUMAN_REVIEW: "科研内容等待人工审阅",
  BLOCKED: "交接证据存在阻断",
  NO_RESULT: "尚无可交接的分析产物",
};
const fileLabels: Record<string, string> = {
  RECORDED_FILE_NOT_RECHECKED: "已记录保存状态，未现场复核文件",
  VERIFIED: "文件复核通过",
  MISSING: "文件未找到",
  CHANGED: "文件内容已变化",
  UNAVAILABLE: "文件暂不可读",
  UNSAFE_PATH: "路径未通过安全核验",
};

export function ReadingResultEnvelopePanel({
  jobId,
  status,
}: {
  jobId: string;
  status?: string;
}) {
  const [envelope, setEnvelope] = useState<Envelope | null>(null);
  const [visible, setVisible] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const opened = useRef(false);
  const busy = useRef(false);
  const sequence = useRef(0);
  const lastOperation = useRef(false);
  const observedStatus = useRef(`${jobId}:${status ?? ""}`);

  const load = useCallback(
    async (checkFile = false) => {
      if (busy.current) return;
      busy.current = true;
      lastOperation.current = checkFile;
      const current = ++sequence.current;
      setLoading(true);
      setError("");
      try {
        const endpoint = `/analysis-jobs/${encodeURIComponent(jobId)}/result-envelope`;
        const result = checkFile
          ? await api.post<Envelope>(`${endpoint}/check-file`, {})
          : await api.get<Envelope>(endpoint);
        if (current === sequence.current) setEnvelope(result);
      } catch (cause) {
        if (current === sequence.current)
          setError(
            cause instanceof Error ? cause.message : "无法读取执行交接记录",
          );
      } finally {
        if (current === sequence.current) setLoading(false);
        busy.current = false;
      }
    },
    [jobId],
  );

  useEffect(() => {
    const next = `${jobId}:${status ?? ""}`;
    if (observedStatus.current === next) return;
    if (loading || busy.current) return;
    observedStatus.current = next;
    let active = true;
    void Promise.resolve().then(() => {
      if (active && opened.current) void load();
    });
    return () => {
      active = false;
    };
  }, [jobId, status, load, loading]);
  useEffect(
    () => () => {
      sequence.current += 1;
    },
    [jobId],
  );

  return (
    <section aria-label="执行交接记录" className="space-y-2 text-xs">
      <Button
        size="sm"
        variant="secondary"
        disabled={loading}
        aria-expanded={visible}
        onClick={() => {
          const next = !visible;
          opened.current = next;
          setVisible(next);
          if (next && !envelope) void load();
        }}
      >
        {loading
          ? "正在读取交接记录…"
          : visible
            ? "收起执行交接记录"
            : "查看执行交接记录"}
      </Button>
      {visible && (
        <div className="space-y-3 rounded border border-[var(--border)] bg-[var(--background)] p-3">
          {loading && <LoadingState label="正在核对执行交接记录…" />}
          {error && (
            <ErrorState
              message={error}
              onRetry={() => void load(lastOperation.current)}
            />
          )}
          {envelope && (
            <>
              <header className="space-y-1">
                <h4 className="font-medium">
                  {proposalLabels[envelope.completion_proposal]}
                </h4>
                <p className="text-[var(--muted)]">
                  技术任务状态：{envelope.job_status} · 查询时间{" "}
                  {new Date(envelope.checked_at).toLocaleString("zh-CN")}
                </p>
                {envelope.job_status === "COMPLETED" && (
                  <p>技术任务已完成，科研结论与精读内容仍需人工核对。</p>
                )}
              </header>
              <dl className="space-y-2">
                <div>
                  <dt className="text-[var(--muted)]">交接协议</dt>
                  <dd>{envelope.schema_version}</dd>
                </div>
                <div>
                  <dt className="text-[var(--muted)]">任务 ID</dt>
                  <dd className="break-all font-mono">{envelope.task_id}</dd>
                </div>
                <div>
                  <dt className="text-[var(--muted)]">统一执行尝试 ID</dt>
                  <dd className="break-all font-mono">
                    {envelope.attempt_id || "未记录统一执行尝试 ID"}
                  </dd>
                </div>
                <div>
                  <dt className="text-[var(--muted)]">论文 ID</dt>
                  <dd className="break-all font-mono">{envelope.paper_id}</dd>
                </div>
                <div>
                  <dt className="text-[var(--muted)]">主课题</dt>
                  <dd className="break-all">
                    {envelope.project_id ||
                      ((envelope.project_ids ?? []).length
                        ? "关联课题已记录，未指定主课题"
                        : "尚未关联课题")}
                  </dd>
                </div>
              </dl>
              {!!envelope.project_ids?.length && (
                <div className="space-y-1">
                  <ul className="space-y-1" aria-label="关联课题">
                    {envelope.project_ids.map((id) => (
                      <li key={id}>
                        <Link
                          className="break-all text-[var(--accent)] underline"
                          href={`/projects/${encodeURIComponent(id)}`}
                        >
                          {id}
                        </Link>
                      </li>
                    ))}
                  </ul>
                  <p className="text-[var(--muted)]">
                    课题列表为当前论文关联；执行时的主课题未由此推断。
                  </p>
                </div>
              )}
              <section aria-label="交接技能来源" className="space-y-2">
                <h5 className="font-medium">技能来源</h5>
                {envelope.skill_binding ? (
                  <>
                    <p>
                      {envelope.skill_binding.key} ·{" "}
                      {envelope.skill_binding.version}
                    </p>
                    <p className="break-all font-mono">
                      组装指令 SHA-256：
                      {envelope.skill_binding.assembled_sha256 || "未记录"}
                    </p>
                    <p className="break-all font-mono">
                      来源清单 SHA-256：
                      {envelope.skill_binding.source_manifest_sha256 ||
                        "未记录文件级清单"}
                    </p>
                    <p>
                      文件绑定版本：
                      {envelope.skill_binding.source_binding_version ||
                        "未记录"}
                    </p>
                    <p>
                      来源核验：
                      {envelope.skill_binding.source_verified
                        ? "冻结来源已核验"
                        : "尚未核验"}{" "}
                      · 通用技能 READY 未授予
                    </p>
                  </>
                ) : (
                  <p className="text-[var(--muted)]">
                    历史任务未记录技能绑定；原有回执和缺口保留，不补造执行身份。
                  </p>
                )}
              </section>
              <section aria-label="交接输入来源" className="space-y-2">
                <h5 className="font-medium">输入来源</h5>
                {envelope.input_refs?.length ? (
                  <ul className="space-y-2">
                    {envelope.input_refs.map((input) => (
                      <li
                        key={`${input.kind}:${input.id}`}
                        className="space-y-1 rounded border border-[var(--border)] p-2"
                      >
                        <p>
                          {input.kind} ·{" "}
                          <span className="break-all font-mono">
                            {input.id}
                          </span>
                        </p>
                        <p className="break-all font-mono">
                          SHA-256：{input.sha256 || "未记录"}
                        </p>
                        <p>
                          版本：{input.version ?? "未记录"}
                          {input.page_count !== null &&
                          input.page_count !== undefined
                            ? ` · 原始页数 ${input.page_count}`
                            : ""}
                        </p>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <EmptyState title="尚无输入来源记录" />
                )}
              </section>
              <section aria-label="交接输出产物" className="space-y-2">
                <h5 className="font-medium">输出产物</h5>
                {envelope.output_artifacts?.length ? (
                  <ul className="space-y-2">
                    {envelope.output_artifacts.map((artifact) => (
                      <li
                        key={`${artifact.kind}:${artifact.id}`}
                        className="space-y-1 rounded border border-[var(--border)] p-2"
                      >
                        <p>
                          {artifact.kind} ·{" "}
                          <span className="break-all font-mono">
                            {artifact.id}
                          </span>
                        </p>
                        <p className="break-all font-mono">
                          SHA-256：{artifact.sha256}
                        </p>
                        <p>
                          {artifact.size_bytes.toLocaleString("zh-CN")} 字节 ·
                          版本 {artifact.version ?? "未记录"}
                        </p>
                        {artifact.path && (
                          <p className="break-all font-mono">
                            记录路径：{artifact.path}
                          </p>
                        )}
                        <p>
                          核验记录：
                          {fileLabels[artifact.verification] ||
                            artifact.verification}
                        </p>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <EmptyState title="尚无输出产物" />
                )}
              </section>
              <p className="leading-5 text-[var(--muted)]">
                路径和哈希来自持久记录。普通查询不现场核验当前笔记文件；需要时使用下方文件复核。
              </p>
              <section aria-label="交接执行回执" className="space-y-2">
                <h5 className="font-medium">调用 / 执行回执</h5>
                {envelope.tool_receipt_refs?.length ? (
                  <ul className="space-y-2">
                    {envelope.tool_receipt_refs.map((receipt) => (
                      <li
                        key={receipt.id}
                        className="space-y-1 rounded border border-[var(--border)] p-2"
                      >
                        <p>
                          {receipt.kind} · {receipt.status}
                        </p>
                        <p className="break-all font-mono">
                          回执 ID：{receipt.id}
                        </p>
                        <p className="break-all">
                          Provider 响应 ID：
                          {receipt.provider_response_id || "未记录"}
                        </p>
                        <p>
                          已报告输入 / 输出 Token：
                          {receipt.input_tokens ?? "未记录"} /{" "}
                          {receipt.output_tokens ?? "未记录"}
                        </p>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <EmptyState title="尚无调用回执" />
                )}
              </section>
              <section aria-label="交接证据缺口" className="space-y-2">
                <h5 className="font-medium">证据缺口</h5>
                {envelope.gaps?.length ? (
                  <ul className="space-y-2">
                    {envelope.gaps.map((gap, index) => (
                      <li
                        key={`${gap.code}:${index}`}
                        className="rounded border border-[var(--border)] p-2"
                      >
                        <p className="font-mono">{gap.code}</p>
                        <p className="mt-1 break-words">{gap.detail}</p>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-[var(--muted)]">
                    本次交接记录未报告缺口；科研内容仍按人工审阅状态处理。
                  </p>
                )}
              </section>
              <p className="rounded bg-[var(--surface)] p-2 leading-5">
                下一步：{envelope.next_action}
              </p>
              <div className="flex flex-wrap gap-2">
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={loading}
                  onClick={() => void load()}
                >
                  刷新交接记录
                </Button>
                {envelope.file_recheck_available && (
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={loading}
                    onClick={() => void load(true)}
                  >
                    复核已记录笔记文件
                  </Button>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </section>
  );
}
