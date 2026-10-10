"use client";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { api } from "@/lib/api";
import { BaselineRuntimePanel } from "./runtime-panel";
import { BaselineRunPlanDetail } from "./plan-detail";
import type { components } from "@/lib/generated";
type Version = components["schemas"]["BaselineVersionOut"];
type Runtime = components["schemas"]["BaselineRuntimeOut"];
type Plans = components["schemas"]["BaselineRunPlanPage"];
type Plan = components["schemas"]["BaselineRunPlanOut"];

export function BaselineRunsWorkspace({
  projectId,
  versionId,
}: {
  projectId: string;
  versionId: string;
}) {
  const [version, setVersion] = useState<Version | null>(null),
    [runtime, setRuntime] = useState<Runtime | null>(null),
    [plans, setPlans] = useState<Plans | null>(null),
    [selected, setSelected] = useState<Plan | null>(null);
  const [loading, setLoading] = useState(true),
    [runtimeLoading, setRuntimeLoading] = useState(false),
    [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState(""),
    [runtimeError, setRuntimeError] = useState(""),
    [detailError, setDetailError] = useState("");
  const [index, setIndex] = useState(0),
    [cursors, setCursors] = useState<(string | null)[]>([null]);
  const seq = useRef(0),
    runtimeSeq = useRef(0),
    detailSeq = useRef(0),
    retry = useRef<{ cursor: string | null; index: number }>({
      cursor: null,
      index: 0,
    }),
    detailTarget = useRef("");
  const endpoint = `/baseline-versions/${encodeURIComponent(versionId)}/run-plans`;
  const load = useCallback(
    async (cursor: string | null = null, at = 0) => {
      const token = ++seq.current;
      setLoading(true);
      retry.current = { cursor, index: at };
      const results = await Promise.allSettled([
        api.get<Version>(`/baseline-versions/${encodeURIComponent(versionId)}`),
        api.get<Plans>(
          `${endpoint}?limit=20${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
        ),
      ]);
      if (token !== seq.current) return;
      const [a, b] = results;
      if (a.status === "fulfilled" && a.value.project_id === projectId)
        setVersion(a.value);
      if (
        b.status === "fulfilled" &&
        b.value.items.every(
          (item) =>
            item.project_id === projectId && item.version_id === versionId,
        )
      ) {
        setPlans(b.value);
        setIndex(at);
      }
      const failures = results
        .filter(
          (item): item is PromiseRejectedResult => item.status === "rejected",
        )
        .map((item) =>
          item.reason instanceof Error
            ? item.reason.message
            : "基线运行资料暂不可读",
        );
      if (a.status === "fulfilled" && a.value.project_id !== projectId)
        failures.push("此基线版本不属于当前课题，未展示或创建其运行计划。");
      if (
        b.status === "fulfilled" &&
        b.value.items.some(
          (item) =>
            item.project_id !== projectId || item.version_id !== versionId,
        )
      )
        failures.push("运行计划的项目版本匹配失败。");
      setError(failures.join("；"));
      setLoading(false);
    },
    [endpoint, projectId, versionId],
  );
  const loadRuntime = useCallback(async () => {
    const token = ++runtimeSeq.current;
    setRuntimeLoading(true);
    try {
      const result = await api.get<Runtime>("/baseline-runs/runtime");
      if (token === runtimeSeq.current) {
        setRuntime(result);
        setRuntimeError("");
      }
    } catch (cause) {
      if (token === runtimeSeq.current)
        setRuntimeError(
          cause instanceof Error ? cause.message : "运行环境状态暂不可读",
        );
    } finally {
      if (token === runtimeSeq.current) setRuntimeLoading(false);
    }
  }, []);
  useEffect(() => {
    queueMicrotask(() => {
      void load();
      void loadRuntime();
    });
    return () => {
      seq.current += 1;
      runtimeSeq.current += 1;
      detailSeq.current += 1;
    };
  }, [load, loadRuntime]);
  const updatePlan = useCallback(
    (plan: Plan) => {
      if (plan.project_id !== projectId || plan.version_id !== versionId) {
        setDetailError("计划返回的项目版本不匹配。");
        return;
      }
      setSelected(plan);
      setPlans((old) =>
        old
          ? {
              ...old,
              items: old.items.map((item) =>
                item.id === plan.id ? plan : item,
              ),
            }
          : old,
      );
    },
    [projectId, versionId],
  );
  async function inspect(id: string) {
    detailTarget.current = id;
    const token = ++detailSeq.current;
    setDetailLoading(true);
    try {
      const result = await api.get<Plan>(
        `/baseline-run-plans/${encodeURIComponent(id)}`,
      );
      if (token !== detailSeq.current) return;
      if (result.project_id !== projectId || result.version_id !== versionId)
        throw new Error("计划不属于当前项目版本。");
      setSelected(result);
      setDetailError("");
    } catch (cause) {
      if (token === detailSeq.current)
        setDetailError(
          cause instanceof Error ? cause.message : "固定计划暂不可读",
        );
    } finally {
      if (token === detailSeq.current) setDetailLoading(false);
    }
  }
  if (loading && !version)
    return <LoadingState label="正在读取当前基线版本与运行计划…" />;
  if (!version)
    return (
      <ErrorState
        message={error || "项目基线版本无法读取"}
        onRetry={() => void load(retry.current.cursor, retry.current.index)}
      />
    );
  return (
    <div className="space-y-5">
      <Link
        href={`/projects/${projectId}/baselines`}
        className="text-xs text-[var(--accent)] underline"
      >
        返回项目基线
      </Link>
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">
          基线 {version.version} · 历史运行审计
        </h1>
        <p className="text-sm text-[var(--muted)]">
          实验、模型试运行、训练、评价与仿真只在课题组服务器执行。本页仅查看已有本机运行记录、取消旧任务或只读核查；不再创建、批准或追加本机运行。
        </p>
      </header>
      {error && (
        <ErrorState
          message={error}
          onRetry={() => void load(retry.current.cursor, retry.current.index)}
        />
      )}{" "}
      {runtimeError && (
        <ErrorState message={runtimeError} onRetry={() => void loadRuntime()} />
      )}
      <BaselineRuntimePanel
        runtime={runtime}
        loading={runtimeLoading}
        onRefresh={() => void loadRuntime()}
      />
      <section
        className="space-y-3 rounded border border-[var(--border)] p-4"
        aria-label="不可变运行计划历史"
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-semibold">已保存运行计划</h2>
        </div>
        {loading ? (
          <LoadingState label="正在读取计划分页…" />
        ) : plans?.items.length ? (
          <ul className="space-y-2">
            {plans.items.map((plan) => (
              <li
                key={plan.id}
                className="flex flex-wrap items-center justify-between gap-2 rounded border border-[var(--border)] p-3 text-xs"
              >
                <span>
                  {plan.state} · {plan.profile} ·{" "}
                  {new Date(plan.created_at).toLocaleString("zh-CN")} · 已用{" "}
                  {plan.used_jobs}/{plan.max_jobs} 次
                </span>
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  disabled={detailLoading}
                  aria-label={`查看运行计划 ${plan.id}`}
                  onClick={() => void inspect(plan.id)}
                >
                  查看固定计划与任务
                </Button>
              </li>
            ))}
          </ul>
        ) : (
          !error && (
            <EmptyState
              title="尚无固定运行计划"
              detail="实验在课题组服务器执行；本页不创建新的本机运行计划。"
            />
          )
        )}
        {plans && (
          <div className="flex items-center justify-between gap-2 text-xs">
            <Button
              type="button"
              size="sm"
              variant="secondary"
              disabled={loading || index === 0}
              onClick={() => void load(cursors[index - 1] ?? null, index - 1)}
            >
              上一页运行计划
            </Button>
            <span>第 {index + 1} 页</span>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              disabled={loading || !plans.page.next_cursor}
              onClick={() => {
                const next = plans.page.next_cursor;
                if (next) {
                  setCursors((old) => [...old.slice(0, index + 1), next]);
                  void load(next, index + 1);
                }
              }}
            >
              下一页运行计划
            </Button>
          </div>
        )}
      </section>
      {detailError && (
        <ErrorState
          message={detailError}
          onRetry={() => void inspect(detailTarget.current)}
        />
      )}{" "}
      {detailLoading && <LoadingState label="正在读取固定计划与批准状态…" />}
      {selected && (
        <BaselineRunPlanDetail
          key={selected.id}
          plan={selected}
          version={version}
          onChanged={updatePlan}
        />
      )}
    </div>
  );
}
