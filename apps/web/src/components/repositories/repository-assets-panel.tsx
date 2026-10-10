"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { api } from "@/lib/api";
import { AssetPlanViewer } from "./asset-plan-viewer";
import type { components } from "@/lib/generated";
type Capability = components["schemas"]["AssetCapabilityOut"];
type Plan = components["schemas"]["AssetPlanOut"];
type PlanPage = components["schemas"]["AssetPlanPage"];
type JobPage = components["schemas"]["AssetJobPage"];
type Create = components["schemas"]["AssetPlanCreate"];

export function RepositoryAssetsPanel({ sourceId }: { sourceId: string }) {
  const [capability, setCapability] = useState<Capability | null>(null);
  const [plans, setPlans] = useState<PlanPage | null>(null);
  const [selected, setSelected] = useState<Plan | null>(null);
  const [jobs, setJobs] = useState<JobPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const busyRef = useRef(false);
  const seq = useRef(0);
  const endpoint = `/repository-sources/${encodeURIComponent(sourceId)}/asset-plans`;
  const load = useCallback(
    async (cursor?: string) => {
      const current = ++seq.current;
      setLoading(true);
      setError("");
      const results = await Promise.allSettled([
        api.get<Capability>("/repository-assets/capability"),
        api.get<PlanPage>(
          `${endpoint}?limit=20${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
        ),
      ]);
      if (current !== seq.current) return;
      const [capResult, pageResult] = results;
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
        (item): item is PromiseRejectedResult => item.status === "rejected",
      );
      if (failures.length)
        setError(
          failures
            .map((item) =>
              item.reason instanceof Error
                ? item.reason.message
                : "资产配置或记录不可读取",
            )
            .join("；"),
        );
      setLoading(false);
    },
    [endpoint],
  );
  useEffect(() => {
    let active = true;
    void Promise.resolve().then(() => {
      if (active) void load();
    });
    return () => {
      active = false;
      seq.current += 1;
    };
  }, [load]);
  async function readPlan(id: string) {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError("");
    try {
      const [plan, list] = await Promise.all([
        api.get<Plan>(`/repository-asset-plans/${id}`),
        api.get<JobPage>(`/repository-asset-plans/${id}/jobs?limit=20`),
      ]);
      setSelected(plan);
      setJobs(list);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "下载计划或任务不可读");
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }
  async function preview(body: Create = {}) {
    if (!capability?.enabled || busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const plan = await api.post<Plan>(endpoint, body);
      setSelected(plan);
      setJobs(null);
      setNotice("固定版本清单已预览；没有下载文件载荷或启动运行。");
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "资产清单预览失败");
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }
  async function approve() {
    if (!selected?.can_approve || !capability?.enabled || busyRef.current)
      return;
    busyRef.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const plan = await api.post<Plan>(
        `/repository-asset-plans/${selected.id}/approve`,
        {
          expected_sha256: selected.plan_sha256,
          confirm_download: true,
        } satisfies components["schemas"]["AssetPlanApprove"],
      );
      setSelected(plan);
      setJobs(
        await api.get<JobPage>(
          `/repository-asset-plans/${plan.id}/jobs?limit=20`,
        ),
      );
      setNotice("下载已按确切批准范围排队；尚未表示所有资产已取得。");
      await load();
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "下载批准失败，未推断已启动",
      );
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }
  return (
    <section aria-label="固定版本资产缓存" className="space-y-4">
      <Card>
        <CardHeader>
          <h2 className="font-semibold">固定版本资产缓存</h2>
          <Button
            size="sm"
            variant="secondary"
            disabled={busy || loading}
            onClick={() => void load()}
          >
            刷新资产记录
          </Button>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-xs leading-5 text-[var(--muted)]">
            仓库元数据登记与实际文件取得分别记录。先核对确切
            Commit、许可、文件选择和字节限制，再批准后台缓存；不会执行代码、加载模型、训练、直接挂工作区或推送第三方代码。
          </p>
          {capability && (
            <p className="text-xs text-[var(--muted)]">{capability.detail}</p>
          )}
          {capability && !capability.enabled && (
            <p className="text-sm font-medium">
              资产下载功能尚未开启；来源元数据及已有文件回执仍可查阅。
            </p>
          )}
          <Button
            disabled={busy || loading || !capability?.enabled}
            onClick={() => void preview()}
          >
            仅预览固定版本文件清单
          </Button>
        </CardContent>
      </Card>
      {error && (
        <div role="alert" aria-label="资产操作失败">
          <ErrorState message={error} />
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
      {loading && <LoadingState label="正在读取资产能力与计划记录…" />}
      {selected && (
        <AssetPlanViewer
          key={selected.id}
          plan={selected}
          capability={capability}
          busy={busy}
          onPreview={preview}
          onApprove={approve}
        />
      )}
      {jobs && jobs.items.length > 0 && (
        <section aria-label="本资产计划下载任务" className="space-y-2">
          <h3 className="text-sm font-semibold">下载任务</h3>
          {jobs.items.map((job) => (
            <Link
              key={job.id}
              className="block rounded border border-[var(--border)] p-3 text-xs text-[var(--accent)]"
              href={`/integrations/repositories/assets/jobs/${job.id}`}
            >
              下载任务 {job.id} · {job.status} · 已保存 {job.stored_files}{" "}
              个文件 / {job.stored_bytes.toLocaleString("zh-CN")} 字节
            </Link>
          ))}
        </section>
      )}
      {plans &&
        !loading &&
        (plans.items.length ? (
          <section aria-label="资产计划历史" className="space-y-2">
            <h3 className="text-sm font-semibold">清单与批准历史</h3>
            {plans.items.map((plan) => (
              <div
                key={plan.id}
                className="flex flex-wrap items-center justify-between gap-2 rounded border border-[var(--border)] p-3 text-xs"
              >
                <p className="break-all">
                  {plan.commit_sha} · {plan.scope} · {plan.state}
                </p>
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={busy}
                  onClick={() => void readPlan(plan.id)}
                >
                  查看清单与下载任务
                </Button>
              </div>
            ))}
            {plans.page.next_cursor && (
              <Button
                size="sm"
                variant="secondary"
                disabled={busy}
                onClick={() => void load(plans.page.next_cursor!)}
              >
                加载更早资产计划
              </Button>
            )}
          </section>
        ) : (
          <EmptyState
            title="尚无资产下载计划"
            detail="只有本人批准清单后才会下载真实文件。"
          />
        ))}
    </section>
  );
}
