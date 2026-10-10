"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { api } from "@/lib/api";
import type { components } from "@/lib/generated";
type Job = components["schemas"]["BaselineRunJobOut"];
type Attempt = components["schemas"]["BaselineRunAttemptOut"];
type Artifact = components["schemas"]["BaselineRunArtifactOut"];
type Event = components["schemas"]["BaselineRunEventOut"];
const labels: Record<Job["status"], string> = {
  QUEUED: "已入队，尚未运行",
  STARTING: "准备容器中",
  RUNNING: "容器运行中",
  CANCEL_REQUESTED: "已请求取消，等待真实停止确认",
  COMPLETED_CANDIDATE: "运行回执已取得，内容为候选",
  FAILED: "执行或回执保存失败",
  CANCELLED: "任务已取消",
  NEEDS_ATTENTION: "运行结果待核查",
};
const permits: Record<Job["permit"]["state"], string> = {
  RESERVED: "排队预约，尚未签发执行许可",
  ISSUED: "短期执行许可已签发",
  STARTED: "许可已用于实际调用",
  REVOKED: "执行许可已撤销",
};

export function BaselineRunJobCard({
  initial,
  projectId,
  versionId,
  onChanged,
}: {
  initial: Job;
  projectId: string;
  versionId: string;
  onChanged: () => Promise<void>;
}) {
  const [job, setJob] = useState(initial),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [expanded, setExpanded] = useState(false),
    [loading, setLoading] = useState(false),
    [recordError, setRecordError] = useState("");
  const [attempts, setAttempts] = useState<Attempt[] | null>(null),
    [artifacts, setArtifacts] = useState<Artifact[] | null>(null),
    [events, setEvents] = useState<Event[] | null>(null);
  const busyRef = useRef(false),
    seq = useRef(0),
    recordSeq = useRef(0),
    polling = useRef(false);
  const endpoint = `/baseline-run-jobs/${encodeURIComponent(initial.id)}`;
  const loadJob = useCallback(async () => {
    const token = ++seq.current;
    try {
      const result = await api.get<Job>(endpoint);
      if (result.project_id !== projectId || result.version_id !== versionId)
        throw new Error("任务不属于当前项目与基线版本。");
      if (token === seq.current) {
        setJob(result);
        setError("");
      }
    } catch (cause) {
      if (token === seq.current)
        setError(cause instanceof Error ? cause.message : "运行任务暂不可读");
    }
  }, [endpoint, projectId, versionId]);
  const loadRecords = useCallback(async () => {
    const token = ++recordSeq.current;
    setLoading(true);
    const results = await Promise.allSettled([
      api.get<Attempt[]>(`${endpoint}/attempts`),
      api.get<Artifact[]>(`${endpoint}/artifacts`),
      api.get<Event[]>(`${endpoint}/events`),
    ]);
    if (token !== recordSeq.current) return;
    const [a, b, c] = results;
    if (a.status === "fulfilled") setAttempts(a.value);
    if (b.status === "fulfilled") setArtifacts(b.value);
    if (c.status === "fulfilled") setEvents(c.value);
    setRecordError(
      results
        .filter(
          (item): item is PromiseRejectedResult => item.status === "rejected",
        )
        .map((item) =>
          item.reason instanceof Error
            ? item.reason.message
            : "部分实际运行记录暂不可读",
        )
        .join("；"),
    );
    setLoading(false);
  }, [endpoint]);
  useEffect(() => {
    queueMicrotask(() => setJob(initial));
  }, [initial]);
  useEffect(() => {
    if (
      !["QUEUED", "STARTING", "RUNNING", "CANCEL_REQUESTED"].includes(
        job.status,
      )
    )
      return;
    const timer = setInterval(() => {
      if (
        document.visibilityState !== "visible" ||
        busyRef.current ||
        polling.current
      )
        return;
      polling.current = true;
      void loadJob().finally(() => {
        polling.current = false;
      });
    }, 4000);
    return () => clearInterval(timer);
  }, [job.status, loadJob]);
  useEffect(
    () => () => {
      seq.current += 1;
      recordSeq.current += 1;
    },
    [],
  );
  async function action(kind: "cancel" | "reconcile") {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError("");
    try {
      const result = await api.post<Job>(`${endpoint}/${kind}`, {});
      if (result.project_id !== projectId || result.version_id !== versionId)
        throw new Error("任务返回的项目版本不匹配。");
      setJob(result);
      await onChanged();
      if (expanded) await loadRecords();
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "任务操作未确认，原回执保留。",
      );
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }
  const shownArtifacts = artifacts ?? job.artifacts;
  return (
    <section
      className="space-y-3 rounded border border-[var(--border)] p-3"
      aria-label={`运行任务 ${job.id}`}
    >
      <h3 className="text-sm font-medium">{labels[job.status]}</h3>
      <p className="text-xs">{permits[job.permit.state]}</p>
      <p className="text-xs text-[var(--muted)]">
        科学资格：NOT_GRANTED。Python 退出 0 不会自动成为 SMOKE、PROTOCOL
        或论文复现成功。
      </p>
      {job.error_message && (
        <p
          role="alert"
          aria-label="运行任务原因"
          className="break-words text-xs text-[var(--danger)]"
        >
          {job.error_code ? `${job.error_code}：` : ""}
          {job.error_message}
        </p>
      )}
      {job.status === "CANCEL_REQUESTED" && (
        <p className="text-xs text-amber-700 dark:text-amber-300">
          停止尚待容器事实确认；不会提前显示为已停止。
        </p>
      )}
      {error && <ErrorState message={error} onRetry={() => void loadJob()} />}
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          size="sm"
          variant="ghost"
          disabled={busy}
          onClick={() => void loadJob()}
        >
          刷新真实任务状态
        </Button>
        {job.can_cancel && (
          <Button
            type="button"
            size="sm"
            variant="secondary"
            disabled={busy}
            onClick={() => void action("cancel")}
          >
            请求取消此任务
          </Button>
        )}
        {job.can_reconcile && (
          <Button
            type="button"
            size="sm"
            variant="secondary"
            disabled={busy}
            onClick={() => void action("reconcile")}
          >
            核查已有运行结果与回执
          </Button>
        )}
      </div>
      {job.can_reconcile && (
        <p className="text-xs text-[var(--muted)]">
          只核对既有容器与已产生结果，不重新执行代码；保存失败时可恢复已取得的产物回执。
        </p>
      )}
      {shownArtifacts.length > 0 && (
        <section className="space-y-2" aria-label={`运行产物 ${job.id}`}>
          <h4 className="text-xs font-medium">实际产物记录</h4>
          {shownArtifacts.map((artifact) => (
            <div
              key={artifact.id}
              className="space-y-1 rounded border border-[var(--border)] p-2 text-xs"
            >
              <p className="break-all">
                {artifact.path} · {artifact.disposition}
              </p>
              <p className="break-all font-mono">{artifact.sha256}</p>
              <p>{artifact.size_bytes} 字节</p>
              {artifact.disposition === "QUARANTINED" && (
                <p className="text-amber-700 dark:text-amber-300">
                  隔离保留，仅供审计，不能用作科学接受。
                </p>
              )}
              {artifact.attachment_id &&
              artifact.disposition !== "UNAVAILABLE" ? (
                <a
                  href={`/api/v1/attachments/${artifact.attachment_id}/download`}
                  className="inline-block text-[var(--accent)] underline"
                >
                  {artifact.disposition === "QUARANTINED"
                    ? "读取隔离产物（仅审计）"
                    : "下载已保存产物"}
                </a>
              ) : (
                <p className="text-[var(--muted)]">尚无可读取的持久文件。</p>
              )}
            </div>
          ))}
        </section>
      )}
      <Button
        type="button"
        size="sm"
        variant="secondary"
        disabled={busy || loading}
        onClick={() => {
          if (expanded) {
            setExpanded(false);
          } else {
            setExpanded(true);
            void loadRecords();
          }
        }}
      >
        {expanded ? "收起实际运行记录" : "查看实际运行记录"}
      </Button>
      {expanded && (
        <div className="space-y-3 border-t border-[var(--border)] pt-3">
          {recordError && (
            <ErrorState
              message={recordError}
              onRetry={() => void loadRecords()}
            />
          )}{" "}
          {loading && (
            <LoadingState label="正在读取真实 attempts、产物和事件…" />
          )}
          {attempts?.length
            ? attempts.map((attempt) => (
                <section
                  key={attempt.id}
                  className="space-y-2 rounded border border-[var(--border)] p-2 text-xs"
                  aria-label={`实际调用 ${attempt.id}`}
                >
                  <p className="font-medium">
                    Attempt {attempt.id} · {attempt.status}
                  </p>
                  <p>
                    进程退出码：{attempt.exit_code ?? "未取得"} · 容器停止：
                    {attempt.container_stopped === null
                      ? "未确认"
                      : attempt.container_stopped
                        ? "已确认"
                        : "未停止"}
                  </p>
                  <p>
                    输入封存：
                    {attempt.input_sealed
                      ? "回执记录为已封存"
                      : "未证实封存，不能视为不可变输入"}
                  </p>
                  {attempt.issues.map((issue, index) => (
                    <p
                      key={`${issue}:${index}`}
                      className="break-words text-amber-700 dark:text-amber-300"
                    >
                      {issue}
                    </p>
                  ))}
                  <details>
                    <summary className="cursor-pointer">
                      实际容器、镜像与输入身份
                    </summary>
                    <div className="mt-2 space-y-1 break-all font-mono">
                      <p>Container：{attempt.container_id ?? "未取得"}</p>
                      <p>Name：{attempt.container_name ?? "未取得"}</p>
                      <p>Image：{attempt.image_id}</p>
                      <p>Daemon：{attempt.daemon_id}</p>
                      <p>
                        Command SHA-256：{attempt.command_sha256 ?? "未记录"}
                      </p>
                      <p>
                        Input manifest SHA-256：
                        {attempt.input_manifest_sha256 ?? "未记录"}
                      </p>
                      {attempt.input_seal && (
                        <pre className="overflow-auto whitespace-pre-wrap">
                          {JSON.stringify(attempt.input_seal, null, 2)}
                        </pre>
                      )}
                    </div>
                  </details>
                  <h4 className="font-medium">原始运行日志</h4>
                  <pre
                    aria-label={`运行原始日志 ${attempt.id}`}
                    className="max-h-80 overflow-auto whitespace-pre-wrap break-words rounded bg-[var(--background)] p-2 font-mono"
                  >
                    {attempt.logs ?? "未取得原始日志"}
                  </pre>
                </section>
              ))
            : attempts && <EmptyState title="尚无实际调用回执" />}
          {artifacts && !artifacts.length && (
            <EmptyState title="尚无持久产物" />
          )}
          <h4 className="text-xs font-medium">原始任务事件</h4>
          {events?.length ? (
            <ul className="space-y-1 text-xs">
              {events.map((event) => (
                <li key={event.id} className="break-all">
                  {new Date(event.occurred_at).toLocaleString("zh-CN")} ·{" "}
                  {event.event_type} · {event.status ?? "未记录状态"} ·{" "}
                  {event.code ?? "无错误码"}
                </li>
              ))}
            </ul>
          ) : (
            events && <EmptyState title="尚无任务事件" />
          )}
        </div>
      )}
    </section>
  );
}
