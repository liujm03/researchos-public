"use client";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { PlanningMarkdownCandidate } from "./planning-markdown-candidate";
import { PlanningBriefCandidateReview } from "./planning-brief-candidate-review";
import type { components } from "@/lib/generated";
type Job = components["schemas"]["PlanningJobOut"];
const labels: Record<Job["status"], string> = {
  QUEUED: "排队中",
  RUNNING: "正在规划",
  CANCEL_REQUESTED: "已请求取消，等待确认",
  COMPLETED: "技术任务完成",
  FAILED: "任务失败",
  NEEDS_ATTENTION: "调用结果待核查",
  CANCELLED: "已取消",
};

export function PlanningJobCard({
  job,
  busy,
  onCancel,
}: {
  job: Job;
  busy: boolean;
  onCancel: () => Promise<void>;
}) {
  return (
    <Card data-testid="planning-job">
      <CardHeader>
        <h3 className="break-all text-sm font-semibold">规划任务 · {job.id}</h3>
        <span className="shrink-0 text-xs text-[var(--muted)]">
          {labels[job.status]}
        </span>
      </CardHeader>
      <CardContent className="space-y-3 text-xs">
        <p className="whitespace-pre-wrap break-words">
          本次关注点：{job.focus}
        </p>
        <details>
          <summary className="cursor-pointer text-[var(--muted)]">
            执行校验详情
          </summary>{" "}
          <p className="break-all font-mono">
            执行 Manifest SHA-256：{job.manifest_sha256}
          </p>
        </details>
        {job.error_message && (
          <p className="break-words text-[var(--danger)]">
            {job.error_code ? `${job.error_code}：` : ""}
            {job.error_message}
          </p>
        )}
        {job.status === "NEEDS_ATTENTION" && (
          <p className="leading-5">
            已开始调用的结果未知，回执与用量保留。不能把它当作未调用或自动重放。
          </p>
        )}
        {job.status === "CANCEL_REQUESTED" && (
          <p className="leading-5">
            平台已经请求停止；外部调用尚未确认结束，不显示为已停止。
          </p>
        )}
        <details className="rounded border border-[var(--border)]">
          <summary className="cursor-pointer p-2">
            查看冻结输入快照与许可
          </summary>
          <div className="space-y-2 border-t border-[var(--border)] p-2">
            {job.permit ? (
              <>
                <p className="break-all font-mono">
                  Permit ID：{job.permit.id} ·{" "}
                  {
                    {
                      RESERVED: "排队预约，尚未签发执行许可",
                      ISSUED: "已签发短期执行许可",
                      STARTED: "实际调用已开始",
                      REVOKED: "许可已撤销",
                    }[job.permit.state]
                  }
                </p>
                <p>
                  {job.permit.state === "RESERVED"
                    ? "预约有效期："
                    : "许可有效期："}
                  {new Date(job.permit.expires_at).toLocaleString("zh-CN")}
                </p>
                <p className="break-all font-mono">
                  许可 Manifest SHA-256：{job.permit.manifest_sha256}
                </p>
              </>
            ) : (
              <p>未记录执行许可。</p>
            )}
            <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words bg-[var(--surface)] p-2 font-mono">
              {JSON.stringify(job.input_snapshot, null, 2)}
            </pre>
          </div>
        </details>
        <section aria-label="规划实际调用尝试" className="space-y-2">
          <h4 className="font-semibold">
            实际调用尝试 · {job.attempts.length}
          </h4>
          {job.attempts.length ? (
            job.attempts.map((attempt) => (
              <div
                key={attempt.id}
                className="space-y-1 rounded border border-[var(--border)] p-2"
              >
                <p className="break-all font-mono">
                  Attempt ID：{attempt.id} · {attempt.status}
                </p>
                <p className="break-all font-mono">
                  Permit ID：{attempt.permit_id}
                </p>
                <p>
                  开始 {new Date(attempt.started_at).toLocaleString("zh-CN")} ·
                  结束{" "}
                  {attempt.ended_at
                    ? new Date(attempt.ended_at).toLocaleString("zh-CN")
                    : "尚未确认"}
                </p>
                <p className="break-all">
                  Provider 响应 ID：{attempt.provider_response_id || "未记录"}
                </p>
                <p>
                  已报告输入 / 输出 Token：{attempt.input_tokens ?? "未知"} /{" "}
                  {attempt.output_tokens ?? "未知"}
                </p>
                {attempt.error_message && (
                  <p className="break-words text-[var(--danger)]">
                    {attempt.error_code ? `${attempt.error_code}：` : ""}
                    {attempt.error_message}
                  </p>
                )}
              </div>
            ))
          ) : (
            <p className="text-[var(--muted)]">
              尚无实际提交尝试，不生成假的 Attempt 或 Provider 回执。
            </p>
          )}
          <p className="text-[var(--muted)]">
            已报告 Token 是本次记录的消耗，账号余额未知时保持未知。
          </p>
        </section>
        {["QUEUED", "RUNNING"].includes(job.status) && (
          <Button
            size="sm"
            variant="secondary"
            disabled={busy}
            onClick={() => void onCancel()}
          >
            {job.status === "QUEUED" ? "取消排队规划任务" : "请求取消运行任务"}
          </Button>
        )}
        {job.result && (
          <p className="break-all font-mono">
            产物关联真实 Attempt ID：{job.result.attempt_id}
          </p>
        )}
        <PlanningMarkdownCandidate
          markdown={job.result?.markdown}
          sha256={job.result?.sha256}
          disposition={job.result?.disposition}
        />
        <PlanningBriefCandidateReview
          key={`${job.id}:${job.result?.sha256 ?? "none"}`}
          job={job}
          disabled={busy}
        />
      </CardContent>
    </Card>
  );
}
