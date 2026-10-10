"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { api } from "@/lib/api";
import { BaselineRunJobCard } from "./job-card";
import type { components } from "@/lib/generated";
type Plan = components["schemas"]["BaselineRunPlanOut"];
type Version = components["schemas"]["BaselineVersionOut"];
type Jobs = components["schemas"]["BaselineRunJobPage"];
type Job = components["schemas"]["BaselineRunJobOut"];

export function BaselineRunPlanDetail({
  plan,
  version,
  onChanged,
}: {
  plan: Plan;
  version: Version;
  onChanged: (value: Plan) => void;
}) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [jobs, setJobs] = useState<Jobs | null>(null),
    [loading, setLoading] = useState(true),
    [jobError, setJobError] = useState("");
  const [index, setIndex] = useState(0),
    [cursors, setCursors] = useState<(string | null)[]>([null]);
  const [notice, setNotice] = useState("");
  const busyRef = useRef(false),
    seq = useRef(0),
    retry = useRef<{ cursor: string | null; index: number }>({
      cursor: null,
      index: 0,
    });
  const endpoint = `/baseline-run-plans/${encodeURIComponent(plan.id)}`;
  const refreshPlan = useCallback(async () => {
    const result = await api.get<Plan>(endpoint);
    if (
      result.project_id !== version.project_id ||
      result.version_id !== version.id
    )
      throw new Error("运行计划不属于当前项目版本。");
    onChanged(result);
  }, [endpoint, onChanged, version.id, version.project_id]);
  const loadJobs = useCallback(
    async (cursor: string | null = null, at = 0) => {
      const token = ++seq.current;
      setLoading(true);
      retry.current = { cursor, index: at };
      try {
        const result = await api.get<Jobs>(
          `${endpoint}/jobs?limit=20${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
        );
        if (token !== seq.current) return;
        if (
          result.items.some(
            (job) =>
              job.project_id !== version.project_id ||
              job.version_id !== version.id,
          )
        )
          throw new Error("任务列表返回了其他项目或版本。");
        setJobs(result);
        setIndex(at);
        setJobError("");
      } catch (cause) {
        if (token === seq.current)
          setJobError(
            cause instanceof Error ? cause.message : "任务历史暂不可读",
          );
      } finally {
        if (token === seq.current) setLoading(false);
      }
    },
    [endpoint, version.project_id, version.id],
  );
  useEffect(() => {
    queueMicrotask(() => void loadJobs());
    return () => {
      seq.current += 1;
    };
  }, [loadJobs]);
  async function revoke() {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError("");
    try {
      const result = await api.post<Plan>(`${endpoint}/revoke`, {});
      if (
        result.project_id !== version.project_id ||
        result.version_id !== version.id
      )
        throw new Error("撤销返回的项目版本不匹配。");
      onChanged(result);
      setNotice(
        "历史授权已撤销；实际停止仍须依据任务记录确认。不会创建新的本机运行。",
      );
      await loadJobs();
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "撤销结果未确认，历史记录保留。",
      );
      await refreshPlan().catch(() => undefined);
      await loadJobs().catch(() => undefined);
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }
  return (
    <section
      className="space-y-4 rounded border border-[var(--border)] p-4"
      aria-label="固定运行计划预览"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold">
          计划：{plan.state}
          {plan.expired ? " · 已到期" : ""}
        </h2>
      </div>
      <p className="text-xs">
        已用 {plan.used_jobs} / {plan.max_jobs} 次 · 剩余 {plan.jobs_remaining}{" "}
        次 · 到期 {new Date(plan.expires_at).toLocaleString("zh-CN")}
      </p>
      <p className="text-xs text-[var(--muted)]">
        历史科学资格：NOT_GRANTED。原批准与资源记录仅供审计，不再授予本机执行权限。实验与仿真均交由课题组服务器。
      </p>
      {!plan.context_current && (
        <p
          role="alert"
          aria-label="运行计划范围已变更"
          className="rounded border border-amber-500/40 p-3 text-xs"
        >
          当前来源或环境已变化，旧计划及输入仅保留审计，不会据此重新执行。
        </p>
      )}
      {plan.expired && (
        <p className="text-xs text-amber-700 dark:text-amber-300">
          授权已到期，不能新增执行。
        </p>
      )}
      {plan.gaps.length > 0 && (
        <div
          className="space-y-1 rounded border border-amber-500/40 p-3 text-xs"
          aria-label="运行计划具体缺口"
        >
          {plan.gaps.map((gap, index) => (
            <p key={`${gap}:${index}`} className="break-words">
              {gap}
            </p>
          ))}
        </div>
      )}
      <div className="grid gap-2 text-xs md:grid-cols-2">
        <p>
          入口：
          {version.assets.find((item) => item.id === plan.entry_asset_id)
            ?.path ?? "未选择"}
        </p>
        <p>
          配置：
          {version.assets.find((item) => item.id === plan.config_asset_id)
            ?.path ?? "未选择"}
        </p>
        <p>Seed：{plan.parameters.random_seed ?? "未记录"}</p>
        <p>
          CPU：{plan.limits.cpu_millicores ?? "未记录"} 毫核 · 内存：
          {plan.limits.memory_bytes ?? "未记录"} 字节 · 时间：
          {plan.limits.timeout_seconds ?? "未记录"} 秒
        </p>
      </div>
      <details className="rounded border border-[var(--border)] p-3 text-xs">
        <summary className="cursor-pointer">
          核对完整计划、资源预算和真实环境身份
        </summary>
        <div className="mt-2 space-y-2 break-all font-mono">
          <p>批准计划 SHA-256：{plan.sha256}</p>
          <p>基线版本 SHA-256：{plan.version_sha256}</p>
          <p>材料检查 SHA-256：{plan.material_check_sha256 ?? "未取得"}</p>
          <p>输入 manifest SHA-256：{plan.input_manifest_sha256}</p>
          <p>Image：{plan.image_id ?? "未取得"}</p>
          <p>Daemon：{plan.daemon_id ?? "未取得"}</p>
          <p>Profile：{plan.profile}</p>
          <pre className="overflow-auto whitespace-pre-wrap">
            {JSON.stringify(plan.limits, null, 2)}
          </pre>
        </div>
      </details>
      <details className="rounded border border-[var(--border)] p-3 text-xs">
        <summary className="cursor-pointer">核对实际执行输入与投影</summary>
        <p className="mt-2 text-[var(--muted)]">
          这里只显示计划固定输入，TRAIN / VALIDATION
          与来源字节哈希单独记录，不包含 TEST
          数据；封存状态由后续实际调用回执报告。
        </p>
        {plan.inputs.length ? (
          <ul className="mt-3 space-y-2">
            {plan.inputs.map((item) => (
              <li
                key={item.id}
                className="space-y-1 rounded border border-[var(--border)] p-2"
              >
                <p className="break-all font-medium">
                  {item.path} · {item.role}
                  {item.dataset_split ? ` · ${item.dataset_split}` : ""}
                </p>
                <p className="break-all font-mono">
                  来源 SHA-256：{item.source_sha256}
                </p>
                <p className="break-all font-mono">
                  输入 SHA-256：{item.input_sha256}
                </p>
                <p>
                  {item.size_bytes} 字节
                  {item.sample_id ? ` · sample ${item.sample_id}` : ""}
                  {item.group_id ? ` · group ${item.group_id}` : ""}
                </p>
                {item.projected_content !== null && (
                  <details>
                    <summary className="cursor-pointer">
                      查看程序生成的投影原文
                    </summary>
                    <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words font-mono">
                      {item.projected_content}
                    </pre>
                  </details>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState title="尚无可固定的运行输入" />
        )}
      </details>
      {error && <ErrorState message={error} />}
      {notice && (
        <p role="status" className="text-xs text-[var(--accent)]">
          {notice}
        </p>
      )}
      {plan.state === "ACTIVE" && (
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            variant="secondary"
            disabled={busy}
            onClick={() => void revoke()}
          >
            撤销此运行授权
          </Button>
        </div>
      )}
      <section
        className="space-y-3 border-t border-[var(--border)] pt-4"
        aria-label="运行任务历史"
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-medium">真实任务与回执</h3>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            disabled={busy || loading}
            onClick={() => {
              void loadJobs(cursors[index] ?? null, index);
              void refreshPlan().catch((cause) =>
                setError(
                  cause instanceof Error ? cause.message : "计划状态不可读",
                ),
              );
            }}
          >
            刷新计划与任务记录
          </Button>
        </div>
        {jobError && (
          <ErrorState
            message={jobError}
            onRetry={() =>
              void loadJobs(retry.current.cursor, retry.current.index)
            }
          />
        )}{" "}
        {loading ? (
          <LoadingState label="正在读取固定计划的任务历史…" />
        ) : jobs?.items.length ? (
          jobs.items.map((job) => (
            <BaselineRunJobCard
              key={job.id}
              initial={job}
              projectId={version.project_id}
              versionId={version.id}
              onChanged={async () => {
                await loadJobs(cursors[index] ?? null, index);
                await refreshPlan();
              }}
            />
          ))
        ) : (
          !jobError && <EmptyState title="尚无实际运行任务" />
        )}
        {jobs && (
          <div className="flex items-center justify-between gap-2 text-xs">
            <Button
              type="button"
              size="sm"
              variant="secondary"
              disabled={busy || loading || index === 0}
              onClick={() =>
                void loadJobs(cursors[index - 1] ?? null, index - 1)
              }
            >
              上一页运行任务
            </Button>
            <span>第 {index + 1} 页</span>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              disabled={busy || loading || !jobs.page.next_cursor}
              onClick={() => {
                const next = jobs.page.next_cursor;
                if (next) {
                  setCursors((old) => [...old.slice(0, index + 1), next]);
                  void loadJobs(next, index + 1);
                }
              }}
            >
              下一页运行任务
            </Button>
          </div>
        )}
      </section>
    </section>
  );
}
