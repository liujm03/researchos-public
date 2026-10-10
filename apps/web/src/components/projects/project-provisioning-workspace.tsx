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

type Capability = components["schemas"]["ProvisionCapabilityOut"];
type Plan = components["schemas"]["ProvisionPlanOut"];
type Job = components["schemas"]["ProvisionJobOut"];
type JobList = components["schemas"]["ProvisionJobListOut"];
type JobEvent = components["schemas"]["ProvisionEventOut"];

const activeStatuses = new Set<Job["status"]>([
  "QUEUED",
  "PREPARING",
  "LOCAL_READY",
  "CREATING_REMOTE",
  "REMOTE_CREATED",
  "BINDING",
]);
const statusLabels: Record<Job["status"], string> = {
  QUEUED: "排队中",
  PREPARING: "核验初始化方案",
  LOCAL_READY: "独立目录已准备",
  CREATING_REMOTE: "创建私有仓库",
  REMOTE_CREATED: "私有仓库已创建",
  BINDING: "保存项目绑定",
  COMPLETED: "初始化已完成",
  FAILED: "初始化失败",
  NEEDS_ATTENTION: "需要核验初始化结果",
  CANCELLED: "已取消",
};
const message = (cause: unknown, fallback: string) =>
  cause instanceof Error ? cause.message : fallback;
const time = (value: string | null | undefined) =>
  value ? new Date(value).toLocaleString("zh-CN") : "尚无记录";

function PlanReview({ plan }: { plan: Plan }) {
  return (
    <section
      aria-label="初始化方案内容"
      className="space-y-3 rounded border border-[var(--border)] p-3 text-xs"
    >
      <dl className="grid gap-3 sm:grid-cols-2">
        <div>
          <dt className="text-[var(--muted)]">独立项目目录名</dt>
          <dd className="mt-1 break-all font-medium">{plan.folder_name}</dd>
        </div>
        <div>
          <dt className="text-[var(--muted)]">目标私有仓库</dt>
          <dd className="mt-1 break-all font-medium">
            {plan.github_owner}/{plan.repository_name}
          </dd>
        </div>
        <div>
          <dt className="text-[var(--muted)]">GitHub Owner ID</dt>
          <dd className="mt-1 font-mono">{plan.github_owner_id}</dd>
        </div>
        <div>
          <dt className="text-[var(--muted)]">模板</dt>
          <dd className="mt-1 break-all">{plan.template_key}</dd>
        </div>
        <div className="sm:col-span-2">
          <dt className="text-[var(--muted)]">冻结方案 SHA-256</dt>
          <dd className="mt-1 break-all font-mono">{plan.plan_sha256}</dd>
        </div>
        <div className="sm:col-span-2">
          <dt className="text-[var(--muted)]">模板 SHA-256</dt>
          <dd className="mt-1 break-all font-mono">{plan.template_sha256}</dd>
        </div>
      </dl>
      <p className="text-[var(--muted)]">
        将生成 {plan.files.length}{" "}
        个代码与说明文件。文件预览不执行代码，也不代表科研实验已完成。
      </p>
      <div className="space-y-2">
        {plan.files.map((file) => (
          <details
            key={file.path}
            className="rounded border border-[var(--border)]"
          >
            <summary className="cursor-pointer break-all px-3 py-2">
              {file.path} · {file.size_bytes.toLocaleString("zh-CN")} 字节
            </summary>
            <div className="space-y-2 border-t border-[var(--border)] p-3">
              <p className="break-all font-mono text-[var(--muted)]">
                SHA-256：{file.sha256}
              </p>
              <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words rounded bg-[var(--background)] p-3 font-mono leading-5">
                {file.content}
              </pre>
            </div>
          </details>
        ))}
      </div>
    </section>
  );
}

function ProvisionJobCard({
  projectId,
  job,
  capability,
  plan,
  busy,
  loadPlan,
  onAction,
}: {
  projectId: string;
  job: Job;
  capability: Capability;
  plan: Plan | undefined;
  busy: boolean;
  loadPlan: (id: string) => Promise<Plan>;
  onAction: (
    job: Job,
    action: "cancel" | "reconcile" | "confirm-observed-repository",
  ) => Promise<void>;
}) {
  const [events, setEvents] = useState<JobEvent[] | null>(null);
  const [eventsVisible, setEventsVisible] = useState(false);
  const [eventsBusy, setEventsBusy] = useState(false);
  const [eventsError, setEventsError] = useState("");
  const [planVisible, setPlanVisible] = useState(false);
  const [planBusy, setPlanBusy] = useState(false);
  const [planError, setPlanError] = useState("");

  async function readEvents() {
    setEventsBusy(true);
    setEventsVisible(true);
    setEventsError("");
    try {
      setEvents(
        await api.get<JobEvent[]>(
          `/projects/${projectId}/provision-jobs/${job.id}/events`,
        ),
      );
    } catch (cause) {
      setEventsError(message(cause, "初始化事件读取失败"));
    } finally {
      setEventsBusy(false);
    }
  }
  async function readPlan() {
    setPlanVisible(true);
    setPlanBusy(true);
    setPlanError("");
    try {
      await loadPlan(job.plan_id);
    } catch (cause) {
      setPlanError(message(cause, "已批准方案读取失败"));
    } finally {
      setPlanBusy(false);
    }
  }

  return (
    <Card data-testid="provision-job">
      <CardHeader>
        <h3 className="min-w-0 break-all text-sm font-semibold">
          初始化任务 · {job.id}
        </h3>
        <span className="shrink-0 rounded border border-[var(--border)] px-2 py-1 text-xs">
          {statusLabels[job.status]}
        </span>
      </CardHeader>
      <CardContent className="space-y-3 text-xs">
        <p className="text-[var(--muted)]">
          创建于 {time(job.created_at)} · 开始 {time(job.started_at)} · 结束{" "}
          {time(job.finished_at)}
        </p>
        {job.repository_id && <p>已确认私有仓库 ID：{job.repository_id}</p>}
        {job.error_message && (
          <p className="break-all text-[var(--danger)]">
            {job.error_code ? `${job.error_code}：` : ""}
            {job.error_message}
          </p>
        )}
        {job.status === "NEEDS_ATTENTION" && (
          <div className="space-y-2 rounded border border-[var(--border)] p-3 leading-5">
            <p>
              初始化结果尚未确认。核验只检查已有目录、Git
              身份和远端仓库，不重复发送建库请求，也不会认领同名的其他项目。
            </p>
            {job.observed_repository_id && (
              <p>
                待核对的候选仓库 ID：
                <strong>{job.observed_repository_id}</strong>
                。请查阅本任务已批准方案，核对 GitHub 账户、仓库名称及此 ID
                后再决定接入。
              </p>
            )}
          </div>
        )}
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            variant="secondary"
            disabled={planBusy}
            aria-expanded={planVisible}
            onClick={() => {
              if (planVisible) setPlanVisible(false);
              else void readPlan();
            }}
          >
            {planBusy
              ? "正在读取方案…"
              : planVisible
                ? "收起批准方案"
                : "查看批准方案"}
          </Button>
          <Button
            size="sm"
            variant="secondary"
            disabled={eventsBusy}
            aria-expanded={eventsVisible}
            onClick={() => {
              if (eventsVisible) setEventsVisible(false);
              else if (events) setEventsVisible(true);
              else void readEvents();
            }}
          >
            {eventsBusy
              ? "正在读取事件…"
              : eventsVisible
                ? "收起初始化事件"
                : "查看初始化事件"}
          </Button>
          {capability.enabled && job.status === "QUEUED" && (
            <Button
              size="sm"
              variant="secondary"
              disabled={busy}
              onClick={() => void onAction(job, "cancel")}
            >
              取消排队初始化
            </Button>
          )}
          {capability.enabled && job.status === "NEEDS_ATTENTION" && (
            <Button
              size="sm"
              variant="secondary"
              disabled={busy}
              onClick={() => void onAction(job, "reconcile")}
            >
              核验未确认初始化
            </Button>
          )}
        </div>
        {planVisible && (
          <>
            {planBusy && <LoadingState label="正在读取已批准方案…" />}
            {planError && (
              <ErrorState message={planError} onRetry={() => void readPlan()} />
            )}
            {!planBusy && !planError && plan && <PlanReview plan={plan} />}
          </>
        )}
        {capability.enabled &&
          job.status === "NEEDS_ATTENTION" &&
          job.observed_repository_id &&
          plan && (
            <div className="space-y-2 rounded border border-[var(--border)] p-3">
              <p className="leading-5">
                明确接入 {plan.github_owner}/{plan.repository_name}（Owner ID{" "}
                {plan.github_owner_id}），候选 Repository ID{" "}
                {job.observed_repository_id}
                。此决定仅接入已发现仓库；后台仍核对身份与私有权限。
              </p>
              <Button
                size="sm"
                disabled={busy || planBusy || !!planError}
                onClick={() =>
                  void onAction(job, "confirm-observed-repository")
                }
              >
                确认接入已发现仓库
              </Button>
            </div>
          )}
        {eventsVisible && (
          <section aria-label="初始化任务事件" className="space-y-2">
            {eventsBusy && <LoadingState label="正在读取初始化事件…" />}
            {eventsError && (
              <ErrorState
                message={eventsError}
                onRetry={() => void readEvents()}
              />
            )}
            {!eventsBusy &&
              !eventsError &&
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
                <EmptyState title="尚无初始化事件" />
              ))}
            {!eventsBusy && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => void readEvents()}
              >
                刷新初始化事件
              </Button>
            )}
          </section>
        )}
      </CardContent>
    </Card>
  );
}

export function ProjectProvisioningWorkspace({
  projectId,
  onChanged,
}: {
  projectId: string;
  onChanged: () => Promise<void>;
}) {
  const [capability, setCapability] = useState<Capability | null>(null);
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [plans, setPlans] = useState<Record<string, Plan>>({});
  const [folder, setFolder] = useState("");
  const [repository, setRepository] = useState("");
  const [busy, setBusy] = useState(false);
  const [capError, setCapError] = useState("");
  const [jobsError, setJobsError] = useState("");
  const [actionError, setActionError] = useState("");
  const [notice, setNotice] = useState("");
  const capSequence = useRef(0);
  const jobSequence = useRef(0);
  const jobsRef = useRef<Job[]>([]);
  const busyRef = useRef(false);
  const pollingRef = useRef(false);
  const completionSeen = useRef(new Set<string>());

  const applyJobs = useCallback(
    async (next: Job[]) => {
      jobsRef.current = next;
      setJobs(next);
      setJobsError("");
      const completed = next.filter(
        (item) =>
          item.status === "COMPLETED" &&
          item.binding_id &&
          !completionSeen.current.has(item.id),
      );
      if (completed.length) {
        completed.forEach((item) => completionSeen.current.add(item.id));
        try {
          await onChanged();
        } catch (cause) {
          completed.forEach((item) => completionSeen.current.delete(item.id));
          setJobsError(message(cause, "项目绑定刷新失败，请重试"));
        }
      }
    },
    [onChanged],
  );
  const loadJobs = useCallback(async () => {
    const sequence = ++jobSequence.current;
    try {
      const result = await api.get<JobList>(
        `/projects/${projectId}/provision-jobs`,
      );
      if (sequence === jobSequence.current) await applyJobs(result.items);
    } catch (cause) {
      if (sequence === jobSequence.current)
        setJobsError(message(cause, "初始化任务读取失败"));
    }
  }, [projectId, applyJobs]);
  const loadCapability = useCallback(async () => {
    const sequence = ++capSequence.current;
    try {
      const result = await api.get<Capability>(
        "/project-provisioning/capability",
      );
      if (sequence === capSequence.current) {
        setCapability(result);
        setCapError("");
      }
    } catch (cause) {
      if (sequence === capSequence.current)
        setCapError(message(cause, "初始化能力读取失败"));
    }
  }, []);
  useEffect(() => {
    let active = true;
    void Promise.resolve().then(() => {
      if (active) {
        void loadCapability();
        void loadJobs();
      }
    });
    return () => {
      active = false;
      capSequence.current += 1;
      jobSequence.current += 1;
    };
  }, [loadCapability, loadJobs]);
  const activeJobs = !!jobs?.some((item) => activeStatuses.has(item.status));
  const needsAttention = !!jobs?.some(
    (item) => item.status === "NEEDS_ATTENTION",
  );
  useEffect(() => {
    if (!activeJobs) return;
    let active = true;
    const poll = async () => {
      if (!active || document.hidden || busyRef.current || pollingRef.current)
        return;
      pollingRef.current = true;
      try {
        await loadJobs();
      } finally {
        pollingRef.current = false;
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
  async function preview(event: FormEvent) {
    event.preventDefault();
    if (!capability?.enabled || !beginAction()) return;
    setPlan(null);
    try {
      const result = await api.post<Plan>(
        `/projects/${projectId}/provision-plans`,
        {
          ...(folder.trim() ? { folder_name: folder.trim() } : {}),
          ...(repository.trim() ? { repository_name: repository.trim() } : {}),
        } satisfies components["schemas"]["ProvisionPlanCreate"],
      );
      setPlan(result);
      setPlans((value) => ({ ...value, [result.id]: result }));
      setNotice("初始化方案已冻结；目录和私有仓库尚未创建。");
    } catch (cause) {
      setActionError(message(cause, "初始化方案预览失败"));
    } finally {
      endAction();
    }
  }
  async function approve() {
    if (!capability?.enabled || !plan || !beginAction()) return;
    try {
      const result = await api.post<Job>(
        `/projects/${projectId}/provision-jobs`,
        {
          plan_id: plan.id,
          expected_plan_sha256: plan.plan_sha256,
          approved: true,
        } satisfies components["schemas"]["ProvisionStart"],
      );
      await applyJobs([
        result,
        ...jobsRef.current.filter((item) => item.id !== result.id),
      ]);
      setNotice("初始化任务已排队；请查阅实际进度，尚未完成目录与仓库绑定。");
    } catch (cause) {
      setActionError(message(cause, "批准初始化失败"));
    } finally {
      endAction();
    }
  }
  async function loadPlan(id: string): Promise<Plan> {
    if (plans[id]) return plans[id];
    const result = await api.get<Plan>(
      `/projects/${projectId}/provision-plans/${id}`,
    );
    setPlans((value) => ({ ...value, [id]: result }));
    return result;
  }
  async function jobAction(
    job: Job,
    action: "cancel" | "reconcile" | "confirm-observed-repository",
  ) {
    if (
      action === "confirm-observed-repository" &&
      (job.status !== "NEEDS_ATTENTION" ||
        !job.observed_repository_id ||
        !plans[job.plan_id])
    ) {
      setActionError("请先读取本任务已批准方案并核对候选仓库身份。");
      return;
    }
    if (!capability?.enabled || !beginAction()) return;
    try {
      const body =
        action === "confirm-observed-repository"
          ? ({
              expected_repository_id: job.observed_repository_id!,
              adopt: true,
            } satisfies components["schemas"]["ProvisionObservedConfirm"])
          : undefined;
      const result = await api.post<Job>(
        `/projects/${projectId}/provision-jobs/${job.id}/${action}`,
        body,
      );
      await applyJobs(
        jobsRef.current.map((item) => (item.id === result.id ? result : item)),
      );
      setNotice(
        action === "cancel"
          ? "已取消排队初始化。"
          : action === "reconcile"
            ? "已核验现有初始化结果；未重复创建仓库。"
            : "已提交明确接入决定，请查阅实际绑定结果。",
      );
    } catch (cause) {
      setActionError(message(cause, "初始化任务操作失败"));
    } finally {
      endAction();
    }
  }

  return (
    <section aria-label="新项目独立初始化" className="space-y-4">
      <h2 className="font-semibold">创建本项目的独立工作区与私有仓库</h2>
      {capError && (
        <ErrorState message={capError} onRetry={() => void loadCapability()} />
      )}
      {!capability && !capError && (
        <LoadingState label="正在读取项目初始化能力…" />
      )}
      {capability && (
        <Card>
          <CardHeader>
            <h3 className="font-semibold">一次选择，后台完成初始化</h3>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-sm text-[var(--muted)]">{capability.detail}</p>
            <p className="text-xs text-[var(--muted)]">
              受管理项目区域：{capability.managed_root_label} · GitHub 账户：
              {capability.github_owner || "尚未核验"}（Owner ID{" "}
              {capability.github_owner_id ?? "未知"}）
            </p>
            {!capability.enabled && (
              <p className="text-sm font-medium">
                服务器尚未启用新项目初始化；已有初始化记录仍可查阅。
              </p>
            )}
            {capability.enabled && (
              <form onSubmit={preview} className="grid gap-3 sm:grid-cols-2">
                <label className="space-y-1.5 text-xs font-medium">
                  独立目录名（可选）
                  <Input
                    disabled={busy || activeJobs || needsAttention}
                    maxLength={160}
                    value={folder}
                    placeholder="留空由系统建议安全目录名"
                    onChange={(event) => {
                      setFolder(event.target.value);
                      setPlan(null);
                      setNotice("");
                    }}
                  />
                </label>
                <label className="space-y-1.5 text-xs font-medium">
                  GitHub 私有仓库名（可选）
                  <Input
                    disabled={busy || activeJobs || needsAttention}
                    maxLength={100}
                    value={repository}
                    placeholder="留空由系统建议独立仓库名"
                    onChange={(event) => {
                      setRepository(event.target.value);
                      setPlan(null);
                      setNotice("");
                    }}
                  />
                </label>
                <div className="sm:col-span-2">
                  <Button
                    type="submit"
                    disabled={
                      busy ||
                      jobs === null ||
                      !!jobsError ||
                      activeJobs ||
                      needsAttention
                    }
                  >
                    预览初始化方案
                  </Button>
                </div>
              </form>
            )}
            <p className="text-xs leading-5 text-[var(--muted)]">
              先查看目录、私有仓库身份和完整文件预览，再批准启动。后台准备独立
              Git
              历史及教程，不覆盖已有目录、不接管无关同名仓库，也不执行模型或训练。持续自动归档在完成绑定后单独设置。
              初始化完成表示目录与私有仓库绑定已就绪；代码是否推送以归档任务的独立回执为准。
            </p>
          </CardContent>
        </Card>
      )}
      {actionError && (
        <div role="alert" aria-label="初始化操作失败">
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
      {plan && (
        <Card>
          <CardHeader>
            <h3 className="font-semibold">待批准初始化方案</h3>
          </CardHeader>
          <CardContent className="space-y-4">
            <PlanReview plan={plan} />
            {capability?.enabled && (
              <Button
                disabled={busy || activeJobs || needsAttention || !!jobsError}
                onClick={() => void approve()}
              >
                批准初始化
              </Button>
            )}
          </CardContent>
        </Card>
      )}
      <div className="flex items-center justify-between gap-3">
        <h3 className="font-semibold">初始化任务 · {jobs?.length ?? 0}</h3>
        <Button
          variant="secondary"
          size="sm"
          disabled={busy}
          onClick={() => void loadJobs()}
        >
          刷新初始化任务
        </Button>
      </div>
      {activeJobs && (
        <p role="status" className="text-xs text-[var(--muted)]">
          初始化进行中；页面可见时每 4 秒刷新进度。
        </p>
      )}
      {jobsError && (
        <ErrorState message={jobsError} onRetry={() => void loadJobs()} />
      )}
      {!jobs && !jobsError && <LoadingState label="正在读取初始化任务…" />}
      {jobs &&
        (jobs.length ? (
          jobs.map((job) => (
            <ProvisionJobCard
              key={job.id}
              projectId={projectId}
              job={job}
              capability={
                capability ?? {
                  enabled: false,
                  managed_root_label: "",
                  github_owner: null,
                  github_owner_id: null,
                  detail: "",
                }
              }
              plan={plans[job.plan_id]}
              busy={busy || !!jobsError}
              loadPlan={loadPlan}
              onAction={jobAction}
            />
          ))
        ) : (
          <EmptyState title="尚无项目初始化任务" />
        ))}
    </section>
  );
}
