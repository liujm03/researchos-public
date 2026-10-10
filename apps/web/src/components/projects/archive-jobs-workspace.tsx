"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { api } from "@/lib/api";
import type { components } from "@/lib/generated";

type Binding = components["schemas"]["ArchiveBindingOut"];
type Capability = components["schemas"]["ArchiveStatusOut"];
type Job = components["schemas"]["ArchiveJobOut"];
type JobList = components["schemas"]["ArchiveJobListOut"];
type JobEvent = components["schemas"]["ArchiveJobEventOut"];
type Policy = components["schemas"]["ArchivePolicyOut"];

const activeStatuses = new Set<Job["status"]>([
  "QUEUED",
  "PREPARING",
  "COMMITTING",
  "PUBLISHING",
]);
const statusLabels: Record<Job["status"], string> = {
  QUEUED: "排队中",
  PREPARING: "核验文件",
  COMMITTING: "保存本地版本",
  PUBLISHING: "推送并核验",
  COMPLETED: "已完成",
  UNCHANGED: "无文件变化",
  FAILED: "失败",
  NEEDS_ATTENTION: "需要核验结果",
  CANCELLED: "已取消",
};
function time(value: string | null | undefined) {
  return value ? new Date(value).toLocaleString("zh-CN") : "尚无记录";
}

function JobCard({
  projectId,
  job,
  writeEnabled,
  busy,
  onAction,
}: {
  projectId: string;
  job: Job;
  writeEnabled: boolean;
  busy: boolean;
  onAction: (job: Job, action: "cancel" | "reconcile") => Promise<void>;
}) {
  const [events, setEvents] = useState<JobEvent[] | null>(null);
  const [visible, setVisible] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function loadEvents() {
    setLoading(true);
    setVisible(true);
    setError("");
    try {
      setEvents(
        await api.get<JobEvent[]>(
          `/projects/${projectId}/archive/jobs/${job.id}/events`,
        ),
      );
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "无法读取任务事件");
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card data-testid="archive-job">
      <CardHeader>
        <div className="min-w-0">
          <h3 className="break-all text-sm font-semibold">{job.tag}</h3>
          <p className="mt-1 text-xs text-[var(--muted)]">
            {job.trigger_kind === "SCHEDULED"
              ? "自动归档"
              : job.trigger_kind === "MANUAL"
                ? "手动归档"
                : job.trigger_kind}{" "}
            · {time(job.created_at)}
          </p>
        </div>
        <span className="shrink-0 rounded border border-[var(--border)] px-2 py-1 text-xs">
          {statusLabels[job.status]}
        </span>
      </CardHeader>
      <CardContent className="space-y-3 text-xs">
        <p className="break-all text-[var(--muted)]">任务 ID：{job.id}</p>
        {job.error_message && (
          <p className="break-all text-[var(--danger)]">
            {job.error_code ? `${job.error_code}：` : ""}
            {job.error_message}
          </p>
        )}
        {job.status === "NEEDS_ATTENTION" && (
          <p className="rounded border border-[var(--border)] p-3 leading-5">
            上次本地或远端动作的结果尚未确认。核验只检查原版本和远端回执，不重新创建版本或盲目推送。
          </p>
        )}
        {job.status === "UNCHANGED" && (
          <p className="text-[var(--muted)]">
            代码文件未变化，此次没有创建或推送新版本。
          </p>
        )}
        <dl className="grid gap-2 sm:grid-cols-2">
          <div>
            <dt className="text-[var(--muted)]">开始时间</dt>
            <dd>{time(job.started_at)}</dd>
          </div>
          <div>
            <dt className="text-[var(--muted)]">结束时间</dt>
            <dd>{time(job.finished_at)}</dd>
          </div>
          <div className="sm:col-span-2">
            <dt className="text-[var(--muted)]">工作区范围 Fingerprint</dt>
            <dd className="break-all font-mono">{job.workspace_fingerprint}</dd>
          </div>
          {job.commit_sha && (
            <div className="sm:col-span-2">
              <dt className="text-[var(--muted)]">Commit SHA</dt>
              <dd className="break-all font-mono">{job.commit_sha}</dd>
            </div>
          )}
          {job.manifest_sha256 && (
            <div className="sm:col-span-2">
              <dt className="text-[var(--muted)]">Manifest SHA-256</dt>
              <dd className="break-all font-mono">{job.manifest_sha256}</dd>
            </div>
          )}
        </dl>
        <div className="flex flex-wrap gap-2">
          {writeEnabled && job.status === "QUEUED" && (
            <Button
              size="sm"
              variant="secondary"
              disabled={busy}
              onClick={() => void onAction(job, "cancel")}
            >
              取消排队任务
            </Button>
          )}
          {writeEnabled && job.status === "NEEDS_ATTENTION" && (
            <Button
              size="sm"
              variant="secondary"
              disabled={busy}
              onClick={() => void onAction(job, "reconcile")}
            >
              核验未确认结果
            </Button>
          )}
          <Button
            size="sm"
            variant="secondary"
            disabled={loading}
            aria-expanded={visible}
            onClick={() => {
              if (visible) setVisible(false);
              else if (events) setVisible(true);
              else void loadEvents();
            }}
          >
            {loading
              ? "正在读取事件…"
              : visible
                ? "收起任务事件"
                : "查看任务事件"}
          </Button>
        </div>
        {visible && (
          <section aria-label={`${job.tag} 任务事件`} className="space-y-2">
            {loading && <LoadingState label="正在读取归档任务事件…" />}
            {error && (
              <ErrorState message={error} onRetry={() => void loadEvents()} />
            )}
            {!loading &&
              !error &&
              events &&
              (events.length ? (
                <ol className="space-y-2">
                  {events.map((event) => (
                    <li
                      key={event.id}
                      className="rounded border border-[var(--border)] p-2"
                    >
                      <p className="text-[var(--muted)]">
                        {time(event.created_at)} · {event.event_kind}
                      </p>
                      <p className="mt-1 break-all">{event.message}</p>
                    </li>
                  ))}
                </ol>
              ) : (
                <EmptyState title="尚无任务事件" />
              ))}
            {!loading && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => void loadEvents()}
              >
                刷新任务事件
              </Button>
            )}
          </section>
        )}
      </CardContent>
    </Card>
  );
}

export function ArchiveJobsWorkspace({
  projectId,
  binding,
  capability,
  onVersionsChanged,
}: {
  projectId: string;
  binding: Binding;
  capability: Capability;
  onVersionsChanged: () => Promise<void>;
}) {
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [draft, setDraft] = useState({ auto: false, interval: "60" });
  const [tag, setTag] = useState("");
  const [busy, setBusy] = useState(false);
  const [jobError, setJobError] = useState("");
  const [policyError, setPolicyError] = useState("");
  const [actionError, setActionError] = useState("");
  const [notice, setNotice] = useState("");
  const jobSequence = useRef(0);
  const policySequence = useRef(0);
  const jobsRef = useRef<Job[]>([]);
  const busyRef = useRef(false);
  const pollRef = useRef(false);

  const applyJobs = useCallback(
    async (next: Job[]) => {
      const finished = next.some(
        (job) =>
          job.status === "COMPLETED" &&
          jobsRef.current.some(
            (old) => old.id === job.id && old.status !== "COMPLETED",
          ),
      );
      jobsRef.current = next;
      setJobs(next);
      setJobError("");
      if (finished) {
        try {
          await onVersionsChanged();
        } catch (cause) {
          setJobError(
            cause instanceof Error ? cause.message : "版本记录刷新失败，请重试",
          );
        }
      }
    },
    [onVersionsChanged],
  );

  const loadJobs = useCallback(async () => {
    const sequence = ++jobSequence.current;
    try {
      const result = await api.get<JobList>(
        `/projects/${projectId}/archive/jobs`,
      );
      if (sequence === jobSequence.current) await applyJobs(result.items);
    } catch (cause) {
      if (sequence === jobSequence.current)
        setJobError(
          cause instanceof Error ? cause.message : "归档任务加载失败",
        );
    }
  }, [projectId, applyJobs]);

  const loadPolicy = useCallback(async () => {
    const sequence = ++policySequence.current;
    try {
      const result = await api.get<Policy>(
        `/projects/${projectId}/archive/policy`,
      );
      if (sequence !== policySequence.current) return;
      setPolicy(result);
      setDraft({
        auto: result.auto_enabled,
        interval: String(result.interval_minutes),
      });
      setPolicyError("");
    } catch (cause) {
      if (sequence === policySequence.current)
        setPolicyError(
          cause instanceof Error ? cause.message : "自动归档规则加载失败",
        );
    }
  }, [projectId]);

  useEffect(() => {
    let active = true;
    void Promise.resolve().then(() => {
      if (active) {
        void loadJobs();
        void loadPolicy();
      }
    });
    return () => {
      active = false;
      jobSequence.current += 1;
      policySequence.current += 1;
    };
  }, [loadJobs, loadPolicy]);

  const activeJobs = !!jobs?.some((job) => activeStatuses.has(job.status));
  useEffect(() => {
    if (!activeJobs) return;
    let active = true;
    const poll = async () => {
      if (!active || document.hidden || busyRef.current || pollRef.current)
        return;
      pollRef.current = true;
      try {
        await loadJobs();
      } finally {
        pollRef.current = false;
      }
    };
    const interval = window.setInterval(() => void poll(), 4000);
    const visible = () => {
      if (!document.hidden) void poll();
    };
    document.addEventListener("visibilitychange", visible);
    return () => {
      active = false;
      window.clearInterval(interval);
      document.removeEventListener("visibilitychange", visible);
    };
  }, [activeJobs, loadJobs]);

  function beginAction() {
    if (busyRef.current) return false;
    busyRef.current = true;
    setBusy(true);
    setActionError("");
    setNotice("");
    jobSequence.current += 1;
    return true;
  }
  function endAction() {
    busyRef.current = false;
    setBusy(false);
  }

  async function createJob(event: FormEvent) {
    event.preventDefault();
    if (!capability.write_enabled || !beginAction()) return;
    try {
      const result = await api.post<Job>(
        `/projects/${projectId}/archive/jobs`,
        tag.trim()
          ? ({
              tag: tag.trim(),
            } satisfies components["schemas"]["ArchiveJobCreate"])
          : {},
      );
      setTag("");
      await applyJobs([
        result,
        ...jobsRef.current.filter((job) => job.id !== result.id),
      ]);
      setNotice("归档任务已排队；版本保存和远端推送尚未完成。");
    } catch (cause) {
      setActionError(
        cause instanceof Error ? cause.message : "创建归档任务失败",
      );
    } finally {
      endAction();
    }
  }
  async function jobAction(job: Job, action: "cancel" | "reconcile") {
    if (!capability.write_enabled || !beginAction()) return;
    try {
      const result = await api.post<Job>(
        `/projects/${projectId}/archive/jobs/${job.id}/${action}`,
      );
      await applyJobs(
        jobsRef.current.map((value) =>
          value.id === result.id ? result : value,
        ),
      );
      setNotice(
        action === "cancel"
          ? "已取消排队任务。"
          : "已检查未确认结果；请查阅任务状态与事件。",
      );
    } catch (cause) {
      setActionError(cause instanceof Error ? cause.message : "任务操作失败");
    } finally {
      endAction();
    }
  }
  async function savePolicy(event: FormEvent) {
    event.preventDefault();
    if (!capability.write_enabled || !policy || !beginAction()) return;
    policySequence.current += 1;
    const minutes = Number(draft.interval);
    if (!Number.isInteger(minutes) || minutes < 10 || minutes > 10080) {
      setActionError("归档间隔须为 10–10080 分钟的整数。");
      endAction();
      return;
    }
    try {
      const result = await api.patch<Policy>(
        `/projects/${projectId}/archive/policy`,
        {
          auto_enabled: draft.auto,
          interval_minutes: minutes,
        } satisfies components["schemas"]["ArchivePolicyPatch"],
      );
      setPolicy(result);
      setDraft({
        auto: result.auto_enabled,
        interval: String(result.interval_minutes),
      });
      setNotice(
        result.auto_enabled
          ? "自动归档规则已保存，仅在当前绑定范围内执行。"
          : "自动归档已关闭；未开始的自动任务已取消，运行中任务与版本保留。",
      );
      await loadJobs();
    } catch (cause) {
      setActionError(
        cause instanceof Error ? cause.message : "归档规则保存失败",
      );
    } finally {
      endAction();
    }
  }

  return (
    <section aria-label="后台归档与自动推送" className="space-y-4">
      <h2 className="font-semibold">后台归档与自动推送</h2>
      <p className="text-sm text-[var(--muted)]">{capability.write_detail}</p>
      {!capability.write_enabled && (
        <p className="text-sm font-medium">
          服务器未启用归档写入；任务与版本历史仍可查阅。
        </p>
      )}
      {actionError && (
        <div role="alert" aria-label="归档操作失败">
          <ErrorState message={actionError} />
        </div>
      )}
      {notice && (
        <p
          role="status"
          className="rounded border border-[var(--accent)] p-3 text-sm"
        >
          {notice}
        </p>
      )}
      {policy && (
        <p className="text-sm">
          自动归档：{policy.auto_enabled ? "已启用" : "已关闭"} · 每{" "}
          {policy.interval_minutes} 分钟 · 下次 {time(policy.next_archive_at)}
        </p>
      )}
      {policyError && (
        <ErrorState message={policyError} onRetry={() => void loadPolicy()} />
      )}
      <details className="rounded border border-[var(--border)]">
        <summary className="cursor-pointer p-3 text-sm">自动归档设置</summary>{" "}
        <Card>
          <CardHeader>
            <h3 className="font-semibold">持续归档规则</h3>
          </CardHeader>
          <CardContent className="space-y-4">
            {policyError && (
              <ErrorState
                message={policyError}
                onRetry={() => void loadPolicy()}
              />
            )}
            {!policy && !policyError && (
              <LoadingState label="正在读取自动归档规则…" />
            )}
            {policy && (
              <>
                <p className="text-xs leading-5 text-[var(--muted)]">
                  范围：{binding.workspace_key} → {binding.github_owner}/
                  {binding.github_repository}（私有仓库 ID{" "}
                  {binding.github_repository_id}
                  ）。仅归档核验合格的项目代码、配置模板与使用说明；科研数据、凭据和私人文件分别保存。目录、账户或目的地变化将阻止执行。
                </p>
                <dl className="grid gap-2 text-xs sm:grid-cols-2">
                  <div>
                    <dt className="text-[var(--muted)]">当前自动归档</dt>
                    <dd>
                      {policy.auto_enabled ? "已启用" : "已关闭"} · 每{" "}
                      {policy.interval_minutes} 分钟
                    </dd>
                  </div>
                  <div>
                    <dt className="text-[var(--muted)]">下次调度时间</dt>
                    <dd>{time(policy.next_archive_at)}</dd>
                  </div>
                  <div className="sm:col-span-2">
                    <dt className="text-[var(--muted)]">
                      已冻结工作区 Fingerprint
                    </dt>
                    <dd className="break-all font-mono">
                      {policy.workspace_fingerprint ||
                        "尚未冻结；启用时核验当前绑定目录"}
                    </dd>
                  </div>
                </dl>
                {capability.write_enabled && (
                  <form
                    onSubmit={savePolicy}
                    className="flex flex-wrap items-end gap-3"
                  >
                    <label className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={draft.auto}
                        disabled={busy}
                        onChange={(event) => {
                          setDraft((value) => ({
                            ...value,
                            auto: event.target.checked,
                          }));
                          setNotice("");
                        }}
                      />
                      启用自动版本归档
                    </label>
                    <label className="space-y-1.5 text-xs font-medium">
                      归档间隔（分钟）
                      <Input
                        type="number"
                        min={10}
                        max={10080}
                        step={1}
                        required
                        value={draft.interval}
                        disabled={busy}
                        onChange={(event) => {
                          setDraft((value) => ({
                            ...value,
                            interval: event.target.value,
                          }));
                          setNotice("");
                        }}
                      />
                    </label>
                    <Button type="submit" disabled={busy || !!policyError}>
                      保存自动归档规则
                    </Button>
                  </form>
                )}
                <p className="text-xs leading-5 text-[var(--muted)]">
                  关闭规则会取消尚未开始的自动任务；运行中动作不承诺即时取消，历史记录与已保存版本继续保留。
                </p>
              </>
            )}
          </CardContent>
        </Card>
      </details>
      {capability.write_enabled && (
        <Card>
          <CardHeader>
            <h3 className="font-semibold">手动创建版本</h3>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-xs leading-5 text-[var(--muted)]">
              后台核对文件清单、保存独立版本并推送已绑定私有仓库。无变化时不创建新版本；未知结果须先核验，不能重复推送。
            </p>
            <form
              onSubmit={createJob}
              className="flex flex-wrap items-end gap-3"
            >
              <details className="min-w-56 flex-1">
                <summary className="cursor-pointer py-2 text-xs text-[var(--muted)]">
                  自定义版本标签（默认自动生成）
                </summary>{" "}
                <label className="min-w-56 flex-1 space-y-1.5 text-xs font-medium">
                  版本标签（可选）
                  <Input
                    value={tag}
                    disabled={busy}
                    maxLength={120}
                    placeholder="留空由系统生成独立标签"
                    onChange={(event) => setTag(event.target.value)}
                  />
                </label>
              </details>
              <Button
                type="submit"
                disabled={
                  busy ||
                  !!jobError ||
                  jobs === null ||
                  activeJobs ||
                  !!jobs?.some((job) => job.status === "NEEDS_ATTENTION")
                }
              >
                创建版本并推送
              </Button>
            </form>
          </CardContent>
        </Card>
      )}
      <div className="flex items-center justify-between gap-3">
        <h3 className="font-semibold">归档任务 · {jobs?.length ?? 0}</h3>
        <Button
          size="sm"
          variant="secondary"
          disabled={busy}
          onClick={() => void loadJobs()}
        >
          刷新归档任务
        </Button>
      </div>
      {activeJobs && (
        <p className="text-xs text-[var(--muted)]" role="status">
          任务执行中；页面可见时每 4 秒刷新状态。
        </p>
      )}
      {jobError && (
        <ErrorState message={jobError} onRetry={() => void loadJobs()} />
      )}
      {!jobs && !jobError && <LoadingState label="正在读取归档任务…" />}
      {jobs &&
        (jobs.length ? (
          jobs.map((job) => (
            <JobCard
              key={job.id}
              projectId={projectId}
              job={job}
              writeEnabled={!!capability.write_enabled}
              busy={busy || !!jobError}
              onAction={jobAction}
            />
          ))
        ) : (
          <EmptyState
            title="尚无后台归档任务"
            detail="启用项目自动规则或手动创建版本后，任务进度会显示在这里。"
          />
        ))}
    </section>
  );
}
