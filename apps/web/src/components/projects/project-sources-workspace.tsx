"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { api, type Project } from "@/lib/api";
import { ProjectSourcePlanViewer } from "./project-source-plan-viewer";
import type { components } from "@/lib/generated";
type Capability = components["schemas"]["ProjectSourceCapabilityOut"];
type Plan = components["schemas"]["ProjectSourcePlanOut"];
type Plans = components["schemas"]["ProjectSourcePlanPage"];
type SnapshotChoice = components["schemas"]["AssetSnapshotChoiceOut"];
type SnapshotPage = components["schemas"]["AssetSnapshotChoicePage"];
type Jobs = components["schemas"]["ProjectSourceJobPage"];

export function ProjectSourcesWorkspace({ projectId }: { projectId: string }) {
  const [project, setProject] = useState<Project | null>(null);
  const [capability, setCapability] = useState<Capability | null>(null);
  const [plans, setPlans] = useState<Plans | null>(null);
  const [selected, setSelected] = useState<Plan | null>(null);
  const [jobs, setJobs] = useState<Jobs | null>(null);
  const [choices, setChoices] = useState<SnapshotChoice[]>([]);
  const [choiceCursor, setChoiceCursor] = useState<string | null>(null);
  const [choiceLoading, setChoiceLoading] = useState(true);
  const [choiceError, setChoiceError] = useState("");
  const choiceSeq = useRef(0);
  const [snapshotId, setSnapshotId] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [readError, setReadError] = useState("");
  const [notice, setNotice] = useState("");
  const busyRef = useRef(false);
  const seq = useRef(0);
  const endpoint = `/projects/${encodeURIComponent(projectId)}/source-plans`;
  const load = useCallback(
    async (cursor?: string) => {
      const current = ++seq.current;
      setReadError("");
      const results = await Promise.allSettled([
        api.get<Project>(`/projects/${projectId}`),
        api.get<Capability>("/project-sources/capability"),
        api.get<Plans>(
          `${endpoint}?limit=20${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
        ),
      ]);
      if (current !== seq.current) return;
      const [projectResult, capResult, pageResult] = results;
      if (projectResult.status === "fulfilled") setProject(projectResult.value);
      if (capResult.status === "fulfilled") setCapability(capResult.value);
      if (pageResult.status === "fulfilled")
        setPlans((old) =>
          cursor && old
            ? {
                ...pageResult.value,
                items: [...old.items, ...pageResult.value.items],
              }
            : pageResult.value,
        );
      const failures = results.filter(
        (result): result is PromiseRejectedResult =>
          result.status === "rejected",
      );
      if (failures.length)
        setReadError(
          failures
            .map((item) =>
              item.reason instanceof Error
                ? item.reason.message
                : "项目源码记录暂不可读",
            )
            .join("；"),
        );
      setLoading(false);
    },
    [projectId, endpoint],
  );
  useEffect(() => {
    let active = true;
    void Promise.resolve().then(() => {
      if (active) {
        setSnapshotId(
          new URLSearchParams(window.location.search).get("asset_snapshot") ??
            "",
        );
        void load();
      }
    });
    return () => {
      active = false;
      seq.current += 1;
    };
  }, [load]);
  const loadChoices = useCallback(async (cursor?: string) => {
    const sequence = ++choiceSeq.current;
    setChoiceLoading(true);
    setChoiceError("");
    try {
      const page = await api.get<SnapshotPage>(
        `/repository-assets/snapshots?limit=20${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
      );
      if (sequence !== choiceSeq.current) return;
      setChoices((old) =>
        cursor
          ? [
              ...new Map(
                [...old, ...page.items].map((item) => [
                  item.asset_snapshot_id,
                  item,
                ]),
              ).values(),
            ]
          : page.items,
      );
      setChoiceCursor(page.page.next_cursor);
    } catch (cause) {
      if (sequence === choiceSeq.current)
        setChoiceError(
          cause instanceof Error ? cause.message : "已保存资产列表读取失败",
        );
    } finally {
      if (sequence === choiceSeq.current) setChoiceLoading(false);
    }
  }, []);
  useEffect(() => {
    let active = true;
    queueMicrotask(() => {
      if (active) void loadChoices();
    });
    return () => {
      active = false;
      choiceSeq.current += 1;
    };
  }, [loadChoices]);
  function begin() {
    if (busyRef.current) return false;
    busyRef.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    return true;
  }
  function end() {
    busyRef.current = false;
    setBusy(false);
  }
  async function preview() {
    if (!snapshotId || !capability?.enabled || !begin()) return;
    try {
      const plan = await api.post<Plan>(endpoint, {
        asset_snapshot_id: snapshotId,
      } satisfies components["schemas"]["ProjectSourcePlanCreate"]);
      setSelected(plan);
      setJobs(null);
      setNotice("固定源码缓存计划已预览；没有写入项目、网络下载或执行代码。");
      await load();
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "源码计划预览失败，输入保留",
      );
    } finally {
      end();
    }
  }
  async function readPlan(id: string) {
    if (!begin()) return;
    try {
      const [plan, list] = await Promise.all([
        api.get<Plan>(`/project-source-plans/${id}`),
        api.get<Jobs>(`/project-source-plans/${id}/jobs?limit=20`),
      ]);
      setSelected(plan);
      setJobs(list);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "源码计划详情不可读");
    } finally {
      end();
    }
  }
  async function approve() {
    if (!selected?.can_approve || !capability?.enabled || !begin()) return;
    try {
      const plan = await api.post<Plan>(
        `/project-source-plans/${selected.id}/approve`,
        {
          expected_sha256: selected.plan_sha256,
          confirm_copy: true,
        } satisfies components["schemas"]["ProjectSourcePlanApprove"],
      );
      setSelected(plan);
      setJobs(
        await api.get<Jobs>(`/project-source-plans/${plan.id}/jobs?limit=20`),
      );
      setNotice("固定路径复制已批准并自动排队；以实际文件和完整回执确认完成。");
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "源码复制批准失败");
    } finally {
      end();
    }
  }
  if (loading) return <LoadingState label="正在读取项目绑定与源码缓存记录…" />;
  if (!project)
    return (
      <ErrorState
        message={readError || "项目不可用"}
        onRetry={() => void load()}
      />
    );
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap gap-4 text-xs text-[var(--accent)]">
        <Link href={`/projects/${projectId}`}>返回课题</Link>
        <Link href={`/projects/${projectId}/archive`}>项目绑定与私有版本</Link>
        <Link href="/integrations/repositories">
          查看仓库来源与真实资产快照
        </Link>
      </div>
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">
          {project.name} · 源码与本地资产
        </h1>
        <p className="text-sm leading-6 text-[var(--muted)]">
          从已取得资产快照到已绑定项目的固定源码缓存目录，保存真实文件、出处和复制回执。后续源码阅读、Git
          历史、运行与基线资格分别核验。
        </p>
      </header>
      {readError && (
        <ErrorState message={readError} onRetry={() => void load()} />
      )}
      {error && (
        <div role="alert" aria-label="项目源码操作失败">
          <ErrorState message={error} />
          <Link
            href={`/projects/${projectId}/archive`}
            className="mt-2 inline-block text-xs text-[var(--accent)] underline"
          >
            核对或初始化此项目的独立科研目录与私有仓库绑定
          </Link>
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
      {capability && (
        <section className="space-y-3 rounded border border-[var(--border)] p-4 text-xs">
          <p>{capability.detail}</p>
          <p>
            受管理根区域：{capability.managed_root_label}
            。实际项目根与缓存路径由服务解析，客户端不能提供任意路径。
          </p>
          {!capability.enabled && (
            <p className="font-medium">
              项目源码缓存写入尚未开启；已有计划与复制记录仍可查阅。
            </p>
          )}
          <label className="block space-y-1.5 font-medium">
            选择已保存资产
            <select
              aria-label="选择已保存资产"
              disabled={busy || !capability.enabled || choiceLoading}
              value={snapshotId}
              onChange={(event) => {
                setSnapshotId(event.target.value);
                if (selected?.state === "DRAFT") {
                  setSelected(null);
                  setJobs(null);
                }
              }}
              className="block h-10 w-full rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 text-sm"
            >
              <option value="">选择仓库资产记录</option>
              {snapshotId &&
                !choices.some(
                  (item) => item.asset_snapshot_id === snapshotId,
                ) && (
                  <option value={snapshotId}>
                    已指定快照 · {snapshotId.slice(0, 8)}（预览时核对来源）
                  </option>
                )}
              {choices.map((item) => (
                <option
                  key={item.asset_snapshot_id}
                  value={item.asset_snapshot_id}
                >
                  {item.repo_id} · {item.commit_sha.slice(0, 8)} ·{" "}
                  {item.stored_files} 文件 /{" "}
                  {item.stored_bytes.toLocaleString("zh-CN")} 字节 ·{" "}
                  {item.status === "PARTIAL" ? "有缺口" : "已保存全库存"}
                </option>
              ))}
            </select>
          </label>
          {choiceLoading && <LoadingState label="正在读取已保存资产…" />}
          {choiceError && (
            <ErrorState
              message={choiceError}
              onRetry={() => void loadChoices()}
            />
          )}
          {!choiceLoading && !choiceError && choices.length === 0 && (
            <p>
              尚无已保存资产。
              <Link
                className="text-[var(--accent)] underline"
                href="/integrations/repositories"
              >
                从开源仓库导入并下载
              </Link>
            </p>
          )}
          {choiceCursor && (
            <Button
              size="sm"
              variant="secondary"
              disabled={choiceLoading || busy}
              onClick={() => void loadChoices(choiceCursor)}
            >
              加载更多已保存资产
            </Button>
          )}
          <details>
            <summary className="cursor-pointer text-[var(--muted)]">
              按快照 ID 定位（高级）
            </summary>
            <Input
              aria-label="实际资产 Snapshot ID"
              disabled={busy || !capability.enabled}
              value={snapshotId}
              onChange={(event) => {
                setSnapshotId(event.target.value);
                if (selected?.state === "DRAFT") {
                  setSelected(null);
                  setJobs(null);
                }
              }}
            />
          </details>
          <Button
            disabled={busy || !capability.enabled || !snapshotId.trim()}
            onClick={() => void preview()}
          >
            仅预览加入项目的固定源码缓存
          </Button>
        </section>
      )}
      {selected && (
        <ProjectSourcePlanViewer
          key={selected.id}
          plan={selected}
          enabled={!!capability?.enabled}
          busy={busy}
          onApprove={approve}
        />
      )}
      {jobs && jobs.items.length > 0 && (
        <section aria-label="项目源码复制任务" className="space-y-2">
          <h2 className="font-semibold">复制任务</h2>
          {jobs.items.map((job) => (
            <Link
              key={job.id}
              href={`/projects/${projectId}/sources/jobs/${job.id}`}
              className="block rounded border border-[var(--border)] p-3 text-xs text-[var(--accent)]"
            >
              复制任务 {job.id} · {job.status} · 已复制 {job.copied_files} 文件
              / {job.copied_bytes} 字节
            </Link>
          ))}
        </section>
      )}
      <section aria-label="项目源码计划历史" className="space-y-2">
        <div className="flex items-center justify-between">
          <h2 className="font-semibold">源码缓存计划历史</h2>
          <Button
            size="sm"
            variant="secondary"
            disabled={busy}
            onClick={() => void load()}
          >
            刷新源码计划记录
          </Button>
        </div>
        {plans ? (
          plans.items.length ? (
            plans.items.map((plan) => (
              <div
                key={plan.id}
                className="flex flex-wrap items-center justify-between gap-2 rounded border border-[var(--border)] p-3 text-xs"
              >
                <p className="break-all">
                  {plan.repo_id} · {plan.commit_sha} · {plan.source_status} ·{" "}
                  {plan.state}
                </p>
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={busy}
                  onClick={() => void readPlan(plan.id)}
                >
                  查看复制计划与任务
                </Button>
              </div>
            ))
          ) : (
            <EmptyState
              title="尚无项目源码缓存计划"
              detail="在真实资产下载任务选择此项目，或提供本人已取得的资产 Snapshot ID。"
            />
          )
        ) : (
          <p className="text-xs text-[var(--muted)]">计划列表尚未读取成功。</p>
        )}
        {plans?.page.next_cursor && (
          <Button
            size="sm"
            variant="secondary"
            disabled={busy}
            onClick={() => void load(plans.page.next_cursor!)}
          >
            加载更早源码计划
          </Button>
        )}
      </section>
    </div>
  );
}
