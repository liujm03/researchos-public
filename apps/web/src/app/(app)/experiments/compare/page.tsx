"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { ArrowLeft, AlertTriangle } from "lucide-react";
import { MetricChart } from "@/components/experiments/metric-chart";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { api } from "@/lib/api";
import type {
  Experiment,
  ExperimentPage,
  ExperimentRun,
  ExperimentRunPage,
  ExperimentComparison,
  RunCompareRequest,
} from "@/lib/experiments";

const pageSize = 20;

function ComparisonWorkspace() {
  const searchParams = useSearchParams();
  const requestedRunId = searchParams.get("run_id");
  const [runs, setRuns] = useState<ExperimentRun[]>([]);
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [experimentId, setExperimentId] = useState("");
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);
  const [selected, setSelected] = useState<ExperimentRun[]>([]);
  const [comparison, setComparison] = useState<ExperimentComparison | null>(
    null,
  );
  const [loading, setLoading] = useState(true);
  const [comparing, setComparing] = useState(false);
  const [error, setError] = useState("");
  const generation = useRef(0);
  const loadedSeed = useRef<string | null>(null);

  const load = useCallback(async () => {
    const request = ++generation.current;
    setLoading(true);
    setError("");
    try {
      const query = new URLSearchParams({
        limit: String(pageSize),
        offset: String(offset),
      });
      if (experimentId) query.set("experiment_id", experimentId);
      const [page, designs] = await Promise.all([
        api.get<ExperimentRunPage>(`/experiment-runs?${query}`),
        api.get<ExperimentPage>("/experiments?limit=100&offset=0"),
      ]);
      const allDesigns = [...designs.items];
      for (let next = designs.items.length; next < designs.total;) {
        if (request !== generation.current) return;
        const more = await api.get<ExperimentPage>(
          `/experiments?limit=100&offset=${next}`,
        );
        if (!more.items.length)
          throw new Error("实验设计分页未推进，请刷新后重试。");
        allDesigns.push(...more.items);
        next += more.items.length;
      }
      if (requestedRunId && loadedSeed.current !== requestedRunId) {
        const seeded =
          page.items.find((item) => item.id === requestedRunId) ??
          (await api.get<ExperimentRun>(`/experiment-runs/${requestedRunId}`));
        if (request !== generation.current) return;
        setSelected((current) =>
          current.some((item) => item.id === seeded.id)
            ? current
            : [...current, seeded],
        );
        loadedSeed.current = requestedRunId;
      }
      if (request !== generation.current) return;
      setRuns(page.items);
      setTotal(page.total);
      setExperiments(allDesigns);
    } catch (cause) {
      if (request === generation.current)
        setError(
          cause instanceof Error ? cause.message : "无法读取可比较的运行",
        );
    } finally {
      if (request === generation.current) setLoading(false);
    }
  }, [experimentId, offset, requestedRunId]);

  useEffect(() => {
    let active = true;
    const controller = generation;
    queueMicrotask(() => {
      if (active) void load();
    });
    return () => {
      active = false;
      controller.current++;
    };
  }, [load]);

  function runLabel(run: ExperimentRun) {
    const design = experiments.find((item) => item.id === run.experiment_id);
    return `${design?.name ?? run.experiment_id} · #${run.run_number}`;
  }

  function toggleRun(run: ExperimentRun) {
    setSelected((current) =>
      current.some((item) => item.id === run.id)
        ? current.filter((item) => item.id !== run.id)
        : [...current, run],
    );
    setComparison(null);
    setError("");
  }

  async function compare() {
    setComparing(true);
    setError("");
    setComparison(null);
    const body: RunCompareRequest = { run_ids: selected.map((run) => run.id) };
    try {
      setComparison(
        await api.post<ExperimentComparison>("/experiments/compare", body),
      );
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "实验对比失败");
    } finally {
      setComparing(false);
    }
  }

  return (
    <div className="space-y-6">
      <Link
        href="/experiments"
        className="inline-flex items-center gap-2 text-xs text-[var(--muted)] hover:text-[var(--accent)]"
      >
        <ArrowLeft className="h-4 w-4" />
        返回实验
      </Link>
      <div>
        <p className="mb-1 text-xs uppercase tracking-[0.18em] text-[var(--accent)]">
          Experiment comparison
        </p>
        <h1 className="text-2xl font-semibold">实验运行对比</h1>
        <p className="mt-2 text-sm text-[var(--muted)]">
          按精确数据版本、分割和评估协议解释结果，缺失值保持缺失。
        </p>
      </div>
      {error && (
        <ErrorState
          message={error}
          onRetry={
            loading || runs.length
              ? undefined
              : () => {
                  void load();
                }
          }
        />
      )}
      <Card>
        <CardHeader>
          <h2 className="font-semibold">选择运行</h2>
          <span className="text-xs text-[var(--muted)]">
            已选 {selected.length} / 20
          </span>
        </CardHeader>
        <CardContent className="space-y-4">
          <label className="block space-y-1.5 text-xs font-medium">
            按实验设计筛选
            <select
              aria-label="按实验设计筛选"
              value={experimentId}
              onChange={(event) => {
                setExperimentId(event.target.value);
                setOffset(0);
              }}
              className="block h-9 w-full max-w-lg rounded-md border border-[var(--border)] bg-[var(--background)] px-3 text-sm"
            >
              <option value="">所有实验设计</option>
              {experiments.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
          {selected.length > 0 && (
            <div className="flex flex-wrap gap-2" aria-label="已选择的运行">
              {selected.map((run) => (
                <button
                  type="button"
                  key={run.id}
                  disabled={comparing}
                  onClick={() => toggleRun(run)}
                  className="rounded-md border border-[var(--accent)]/30 bg-[var(--accent)]/5 px-3 py-2 text-xs text-[var(--accent)]"
                  aria-label={`移除 ${runLabel(run)}`}
                >
                  {runLabel(run)} ×
                </button>
              ))}
            </div>
          )}
          {loading ? (
            <LoadingState label="正在读取运行列表…" />
          ) : runs.length ? (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="text-[var(--muted)]">
                  <tr>
                    {["选择", "运行", "状态", "GPU", "Seed"].map((label) => (
                      <th key={label} className="py-2 pr-4 font-medium">
                        {label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--border)]">
                  {runs.map((run) => {
                    const checked = selected.some((item) => item.id === run.id);
                    return (
                      <tr key={run.id}>
                        <td className="py-3 pr-4">
                          <input
                            type="checkbox"
                            checked={checked}
                            disabled={
                              comparing || (!checked && selected.length >= 20)
                            }
                            onChange={() => toggleRun(run)}
                            aria-label={`选择 ${runLabel(run)}`}
                          />
                        </td>
                        <td className="py-3 pr-4">
                          <Link
                            href={`/experiment-runs/${run.id}`}
                            className="text-[var(--accent)] underline"
                          >
                            {runLabel(run)}
                          </Link>
                          <p className="mt-1 break-all font-mono text-[10px] text-[var(--muted)]">
                            {run.id}
                          </p>
                        </td>
                        <td className="py-3 pr-4">{run.status}</td>
                        <td className="py-3 pr-4">{run.gpu ?? "未记录"}</td>
                        <td className="py-3">{run.random_seed ?? "未记录"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState
              title="没有可比较的运行"
              detail="先在实验设计中记录一次外部运行及其真实指标。"
            />
          )}
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-xs text-[var(--muted)]">
              {total
                ? `${offset + 1}–${Math.min(offset + runs.length, total)} / ${total}`
                : "0 条运行"}
            </p>
            <div className="flex gap-2">
              <Button
                variant="secondary"
                size="sm"
                disabled={loading || offset === 0}
                onClick={() => setOffset(Math.max(0, offset - pageSize))}
              >
                上一页
              </Button>
              <Button
                variant="secondary"
                size="sm"
                disabled={loading || offset + runs.length >= total}
                onClick={() => setOffset(offset + pageSize)}
              >
                下一页
              </Button>
            </div>
          </div>
          <Button
            disabled={comparing || selected.length < 2}
            onClick={() => {
              void compare();
            }}
          >
            {comparing ? "正在比较…" : "比较所选运行"}
          </Button>
        </CardContent>
      </Card>
      {comparison && (
        <>
          {comparison.warnings.length > 0 && (
            <div
              role="status"
              className="space-y-2 rounded-lg border border-amber-500/30 bg-amber-500/5 p-4 text-sm"
            >
              <p className="flex items-center gap-2 font-medium text-amber-700 dark:text-amber-400">
                <AlertTriangle className="h-4 w-4" />
                比较条件需要核对
              </p>
              <ul className="list-disc space-y-1 pl-5 text-xs leading-5">
                {comparison.warnings.map((warning, index) => (
                  <li key={`${index}:${warning}`}>{warning}</li>
                ))}
              </ul>
            </div>
          )}
          <Card>
            <CardHeader>
              <h2 className="font-semibold">比较来源</h2>
            </CardHeader>
            <CardContent>
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="text-[var(--muted)]">
                    <tr>
                      {[
                        "运行",
                        "ModelVersion",
                        "DatasetVersion / 角色",
                        "Git Commit",
                        "配置 SHA-256",
                        "GPU / 环境 / Seed",
                      ].map((label) => (
                        <th key={label} className="py-2 pr-4 font-medium">
                          {label}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[var(--border)]">
                    {comparison.runs.map((run) => (
                      <tr key={run.id}>
                        <td className="py-3 pr-4">
                          {runLabel(run)}
                          <p className="mt-1 break-all font-mono text-[10px] text-[var(--muted)]">
                            {run.id}
                          </p>
                        </td>
                        <td className="py-3 pr-4 font-mono">
                          {run.model_version_id ?? "未记录"}
                        </td>
                        <td className="py-3 pr-4">
                          {(run.datasets ?? []).length
                            ? (run.datasets ?? []).map((item) => (
                                <p
                                  key={`${item.dataset_version_id}:${item.role}`}
                                  className="break-all font-mono"
                                >
                                  {item.dataset_version_id} / {item.role}
                                </p>
                              ))
                            : "未记录"}
                        </td>
                        <td className="py-3 pr-4 font-mono">
                          {run.git_commit ?? "未记录"}
                        </td>
                        <td className="py-3 pr-4 break-all font-mono">
                          {run.config_sha256 ?? "未记录"}
                        </td>
                        <td className="py-3 pr-4">
                          {run.gpu ?? "未记录"}
                          <p className="mt-1 text-[var(--muted)]">
                            Python {run.python_version ?? "?"} · PyTorch{" "}
                            {run.pytorch_version ?? "?"} · CUDA{" "}
                            {run.cuda_version ?? "?"}
                          </p>
                          <p className="mt-1 text-[var(--muted)]">
                            Seed {run.random_seed ?? "未记录"}
                          </p>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
          {!comparison.metrics.length ? (
            <Card>
              <CardContent>
                <EmptyState
                  title="所选运行尚无指标"
                  detail="比较只显示已记录结果，不补齐缺失值。"
                />
              </CardContent>
            </Card>
          ) : (
            comparison.metrics.map((group) => {
              const definition = group.metric_definition;
              const valueByRun = new Map(
                group.values.map((item) => [item.run_id, item.value]),
              );
              const steps = group.series
                .map((series) => ({
                  name: runLabel(
                    comparison.runs.find((item) => item.id === series.run_id)!,
                  ),
                  points: series.points
                    .filter(
                      (item) => item.step !== null && item.step !== undefined,
                    )
                    .sort((a, b) => a.step! - b.step!)
                    .map(
                      (item) => [item.step!, item.value] as [number, number],
                    ),
                }))
                .filter((series) => series.points.length);
              const epochs = group.series
                .map((series) => ({
                  name: runLabel(
                    comparison.runs.find((item) => item.id === series.run_id)!,
                  ),
                  points: series.points
                    .filter(
                      (item) =>
                        item.step == null &&
                        item.epoch !== null &&
                        item.epoch !== undefined,
                    )
                    .sort((a, b) => a.epoch! - b.epoch!)
                    .map(
                      (item) => [item.epoch!, item.value] as [number, number],
                    ),
                }))
                .filter((series) => series.points.length);
              const title = `${definition.name} · ${group.split_name}`;
              return (
                <Card key={`${definition.id}:${group.split_name}`}>
                  <CardHeader>
                    <div>
                      <h2 className="font-semibold">{title}</h2>
                      <p className="mt-1 text-xs leading-5 text-[var(--muted)]">
                        协议：{definition.evaluation_protocol} · 单位：
                        {definition.unit ?? "未指定"} ·{" "}
                        {definition.higher_is_better ? "越高越好" : "越低越好"}
                      </p>
                    </div>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    <div className="overflow-x-auto">
                      <table className="w-full text-left text-xs">
                        <thead className="text-[var(--muted)]">
                          <tr>
                            <th className="py-2 pr-4 font-medium">运行</th>
                            <th className="py-2 font-medium">
                              比较值（优先汇总）
                              {definition.unit ? `（${definition.unit}）` : ""}
                            </th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-[var(--border)]">
                          {comparison.runs.map((run) => {
                            const value = valueByRun.get(run.id);
                            return (
                              <tr key={run.id}>
                                <td className="py-2 pr-4">{runLabel(run)}</td>
                                <td className="py-2 font-mono">
                                  {value === null || value === undefined ? (
                                    <span className="font-sans text-[var(--muted)]">
                                      未记录
                                    </span>
                                  ) : (
                                    value
                                  )}
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                    <p className="text-xs leading-5 text-[var(--muted)]">
                      优先使用已记录的汇总指标；缺少汇总时使用观测值，并在比较提示中标明来源。观测曲线的最佳点不代表独立测试集的最终结果。
                    </p>
                    {group.values.some((item) => item.value !== null) && (
                      <MetricChart
                        title={title}
                        unit={definition.unit ?? null}
                        axisLabel="实验运行"
                        kind="bar"
                        series={[
                          {
                            name: definition.name,
                            points: comparison.runs.map((run) => [
                              runLabel(run),
                              valueByRun.get(run.id) ?? null,
                            ]),
                          },
                        ]}
                      />
                    )}
                    {steps.length > 0 && (
                      <MetricChart
                        title={title}
                        unit={definition.unit ?? null}
                        axisLabel="Step"
                        series={steps}
                      />
                    )}
                    {epochs.length > 0 && (
                      <MetricChart
                        title={title}
                        unit={definition.unit ?? null}
                        axisLabel="Epoch"
                        series={epochs}
                      />
                    )}
                    {group.series.some((series) => series.points.length) && (
                      <details>
                        <summary className="cursor-pointer text-xs text-[var(--accent)]">
                          查看比较曲线的原始数据
                        </summary>
                        <div className="mt-3 overflow-x-auto">
                          <table className="w-full text-left text-xs">
                            <thead className="text-[var(--muted)]">
                              <tr>
                                {["运行", "Step", "Epoch", "值"].map(
                                  (label) => (
                                    <th
                                      key={label}
                                      className="py-2 pr-4 font-medium"
                                    >
                                      {label}
                                    </th>
                                  ),
                                )}
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-[var(--border)]">
                              {group.series.flatMap((series) =>
                                series.points.map((point, index) => (
                                  <tr key={`${series.run_id}:${index}`}>
                                    <td className="py-2 pr-4">
                                      {runLabel(
                                        comparison.runs.find(
                                          (run) => run.id === series.run_id,
                                        )!,
                                      )}
                                    </td>
                                    <td className="py-2 pr-4">
                                      {point.step ?? "—"}
                                    </td>
                                    <td className="py-2 pr-4">
                                      {point.epoch ?? "—"}
                                    </td>
                                    <td className="py-2 font-mono">
                                      {point.value}
                                    </td>
                                  </tr>
                                )),
                              )}
                            </tbody>
                          </table>
                        </div>
                      </details>
                    )}
                  </CardContent>
                </Card>
              );
            })
          )}
        </>
      )}
    </div>
  );
}

export default function ExperimentComparisonPage() {
  return (
    <Suspense fallback={<LoadingState label="正在读取实验对比…" />}>
      <ComparisonWorkspace />
    </Suspense>
  );
}
