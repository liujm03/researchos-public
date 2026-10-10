"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from "react";
import {
  MetricChart,
  type MetricSeries,
} from "@/components/experiments/metric-chart";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input, Textarea } from "@/components/ui/input";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { api } from "@/lib/api";
import type {
  ExperimentMetric,
  MetricBatch,
  MetricBatchOut,
  MetricDefinition,
  MetricDefinitionCreate,
  MetricDefinitionPage,
  MetricPage,
} from "@/lib/experiments";

function metricTitle(definition: MetricDefinition, split: string) {
  return `${definition.name} · ${split}`;
}

export function RunMetrics({
  runId,
  archived = false,
}: {
  runId: string;
  archived?: boolean;
}) {
  const [definitions, setDefinitions] = useState<MetricDefinition[]>([]);
  const [metrics, setMetrics] = useState<ExperimentMetric[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [saving, setSaving] = useState(false);
  const [definitionId, setDefinitionId] = useState("");
  const [split, setSplit] = useState("test");
  const [inputKind, setInputKind] = useState<"summary" | "step" | "epoch">(
    "summary",
  );
  const [value, setValue] = useState("");
  const [curve, setCurve] = useState("");
  const [isBest, setIsBest] = useState(false);
  const [showDefinition, setShowDefinition] = useState(false);
  const [name, setName] = useState("");
  const [unit, setUnit] = useState("");
  const [protocol, setProtocol] = useState("");
  const [description, setDescription] = useState("");
  const [higherIsBetter, setHigherIsBetter] = useState(true);
  const generation = useRef(0);

  const load = useCallback(async () => {
    const request = ++generation.current;
    setLoading(true);
    setError("");
    try {
      const [definitionResult, first] = await Promise.all([
        api.get<MetricDefinitionPage>("/metric-definitions?limit=100&offset=0"),
        api.get<MetricPage>(
          `/experiment-runs/${runId}/metrics?limit=100&offset=0`,
        ),
      ]);
      const allDefinitions = [...definitionResult.items];
      for (
        let offset = definitionResult.items.length;
        offset < definitionResult.total;
      ) {
        if (request !== generation.current) return;
        const page = await api.get<MetricDefinitionPage>(
          `/metric-definitions?limit=100&offset=${offset}`,
        );
        if (!page.items.length)
          throw new Error("指标定义分页未推进，请刷新后重试。");
        allDefinitions.push(...page.items);
        offset += page.items.length;
      }
      const allMetrics = [...first.items];
      for (let offset = first.items.length; offset < first.total;) {
        if (request !== generation.current) return;
        const page = await api.get<MetricPage>(
          `/experiment-runs/${runId}/metrics?limit=100&offset=${offset}`,
        );
        if (!page.items.length)
          throw new Error("指标结果分页未推进，请刷新后重试。");
        allMetrics.push(...page.items);
        offset += page.items.length;
      }
      if (request !== generation.current) return;
      setDefinitions(allDefinitions);
      setMetrics(allMetrics);
    } catch (cause) {
      if (request === generation.current)
        setError(cause instanceof Error ? cause.message : "无法读取指标");
    } finally {
      if (request === generation.current) setLoading(false);
    }
  }, [runId]);

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

  const selectedDefinition = definitions.find(
    (item) => item.id === definitionId,
  );
  const groups = useMemo(() => {
    const result: {
      definition: MetricDefinition;
      split: string;
      items: ExperimentMetric[];
      stepSeries: MetricSeries[];
      epochSeries: MetricSeries[];
    }[] = [];
    for (const definition of definitions) {
      const matching = metrics.filter(
        (item) => item.metric_definition_id === definition.id,
      );
      for (const name of new Set(
        matching.map((item) => item.split_name ?? "all"),
      )) {
        const items = matching.filter(
          (item) => (item.split_name ?? "all") === name,
        );
        result.push({
          definition,
          split: name,
          items,
          stepSeries: [
            {
              name: definition.name,
              points: items
                .filter((item) => item.step != null)
                .sort((a, b) => a.step! - b.step!)
                .map((item) => [item.step!, item.value]),
            },
          ],
          epochSeries: [
            {
              name: definition.name,
              points: items
                .filter((item) => item.step == null && item.epoch != null)
                .sort((a, b) => a.epoch! - b.epoch!)
                .map((item) => [item.epoch!, item.value]),
            },
          ],
        });
      }
    }
    return result;
  }, [definitions, metrics]);

  async function createDefinition(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    setNotice("");
    const body: MetricDefinitionCreate = {
      name: name.trim(),
      unit: unit.trim() || null,
      higher_is_better: higherIsBetter,
      evaluation_protocol: protocol.trim(),
      description: description.trim() || null,
    };
    try {
      const result = await api.post<MetricDefinition>(
        "/metric-definitions",
        body,
      );
      setDefinitions((previous) => [
        ...previous.filter((item) => item.id !== result.id),
        result,
      ]);
      setDefinitionId(result.id);
      setShowDefinition(false);
      setName("");
      setUnit("");
      setProtocol("");
      setDescription("");
      setNotice("指标定义已保存。单位与评估协议将用于解释和比较结果。");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "指标定义保存失败");
    } finally {
      setSaving(false);
    }
  }

  async function saveMetrics(event: FormEvent) {
    event.preventDefault();
    if (archived) return;
    setSaving(true);
    setError("");
    setNotice("");
    try {
      if (!selectedDefinition) throw new Error("请选择已保存的指标定义。");
      const rows: MetricBatch["metrics"] = [];
      if (inputKind === "summary") {
        if (!value.trim() || !Number.isFinite(Number(value)))
          throw new Error("指标值必须是有效有限数值。");
        rows.push({
          metric_definition_id: definitionId,
          split_name: split.trim() || "all",
          value: Number(value),
          step: null,
          epoch: null,
          is_best: isBest,
        });
      } else {
        const lines = curve.split(/\r?\n/).filter((line) => line.trim());
        if (!lines.length)
          throw new Error("请填写曲线数据，每行包含序号和值。");
        if (lines.length > 1000)
          throw new Error("单次最多保存 1000 个曲线点，请分批录入。");
        const seen = new Set<number>();
        for (const [index, line] of lines.entries()) {
          const cells = line.trim().split(/[\s,，]+/);
          const coordinate = Number(cells[0]);
          const result = Number(cells[1]);
          if (
            cells.length !== 2 ||
            !Number.isSafeInteger(coordinate) ||
            coordinate < 0 ||
            !Number.isFinite(result)
          )
            throw new Error(
              `第 ${index + 1} 行需要非负整数 ${inputKind} 和有限数值，例如 1,0.68。`,
            );
          if (seen.has(coordinate))
            throw new Error(
              `第 ${index + 1} 行的 ${inputKind} 重复，请检查原始数据。`,
            );
          seen.add(coordinate);
          rows.push({
            metric_definition_id: definitionId,
            split_name: split.trim() || "all",
            value: result,
            step: inputKind === "step" ? coordinate : null,
            epoch: inputKind === "epoch" ? coordinate : null,
            is_best: false,
          });
        }
      }
      const body: MetricBatch = { metrics: rows };
      const receipt = await api.post<MetricBatchOut>(
        `/experiment-runs/${runId}/metrics`,
        body,
      );
      setNotice(
        `已新增 ${receipt.created} 条，复用 ${receipt.reused} 条相同记录。`,
      );
      setValue("");
      setCurve("");
      setIsBest(false);
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "指标保存失败");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <div>
          <h2 className="font-semibold">实验指标与训练曲线</h2>
          <p className="mt-1 text-xs leading-5 text-[var(--muted)]">
            记录实际评估结果；同一位置的矛盾值会被拒绝并保留原始值。
          </p>
        </div>
        <Button
          variant="secondary"
          size="sm"
          disabled={saving || loading || archived}
          onClick={() => setShowDefinition(!showDefinition)}
        >
          {showDefinition ? "取消定义" : "新建指标定义"}
        </Button>
      </CardHeader>
      <CardContent className="space-y-5">
        {archived && (
          <p className="text-xs text-[var(--muted)]">
            该运行已归档，指标只读；补充新的结果需要创建新的运行记录。
          </p>
        )}
        {error && (
          <ErrorState
            message={error}
            onRetry={
              !metrics.length && !definitions.length
                ? () => {
                    void load();
                  }
                : undefined
            }
          />
        )}
        {notice && (
          <p
            role="status"
            className="text-sm text-emerald-600 dark:text-emerald-400"
          >
            {notice}
          </p>
        )}
        {loading ? (
          <LoadingState label="正在读取指标定义和结果…" />
        ) : (
          <>
            {showDefinition && (
              <form
                onSubmit={createDefinition}
                className="grid gap-4 rounded-lg border border-[var(--border)] p-4 sm:grid-cols-2"
              >
                <label className="space-y-1.5 text-xs font-medium">
                  指标名称
                  <Input
                    required
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                    placeholder="mIoU / FPS / Loss"
                  />
                </label>
                <label className="space-y-1.5 text-xs font-medium">
                  单位
                  <Input
                    value={unit}
                    onChange={(event) => setUnit(event.target.value)}
                    placeholder="例如 %、frames/s；无量纲可留空"
                  />
                </label>
                <label className="space-y-1.5 text-xs font-medium sm:col-span-2">
                  评估协议
                  <Input
                    required
                    value={protocol}
                    onChange={(event) => setProtocol(event.target.value)}
                    placeholder="例如固定测试集、IoU 0.5、单张图像与 batch=1"
                  />
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={higherIsBetter}
                    onChange={(event) =>
                      setHigherIsBetter(event.target.checked)
                    }
                  />
                  数值越高越好
                </label>
                <label className="space-y-1.5 text-xs font-medium sm:col-span-2">
                  定义说明
                  <Textarea
                    value={description}
                    onChange={(event) => setDescription(event.target.value)}
                  />
                </label>
                <div className="sm:col-span-2">
                  <Button type="submit" disabled={saving}>
                    {saving ? "保存中…" : "保存指标定义"}
                  </Button>
                </div>
              </form>
            )}
            {definitions.length ? (
              <form
                onSubmit={saveMetrics}
                className="grid gap-4 rounded-lg border border-[var(--border)] p-4 sm:grid-cols-2"
              >
                <label className="space-y-1.5 text-xs font-medium">
                  指标定义
                  <select
                    required
                    aria-label="指标定义"
                    value={definitionId}
                    onChange={(event) => setDefinitionId(event.target.value)}
                    className="block h-9 w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-3 text-sm"
                  >
                    <option value="">选择名称与协议</option>
                    {definitions.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.name} · {item.evaluation_protocol}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="space-y-1.5 text-xs font-medium">
                  数据分割
                  <Input
                    required
                    value={split}
                    onChange={(event) => setSplit(event.target.value)}
                    placeholder="train / validation / test"
                  />
                </label>
                {selectedDefinition && (
                  <p className="text-xs leading-5 text-[var(--muted)] sm:col-span-2">
                    单位：{selectedDefinition.unit ?? "未指定"} ·{" "}
                    {selectedDefinition.higher_is_better
                      ? "越高越好"
                      : "越低越好"}{" "}
                    · 协议：{selectedDefinition.evaluation_protocol}
                  </p>
                )}
                <label className="space-y-1.5 text-xs font-medium">
                  记录方式
                  <select
                    aria-label="记录方式"
                    value={inputKind}
                    onChange={(event) =>
                      setInputKind(event.target.value as typeof inputKind)
                    }
                    className="block h-9 w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-3 text-sm"
                  >
                    <option value="summary">汇总指标</option>
                    <option value="step">按 Step 的曲线</option>
                    <option value="epoch">按 Epoch 的曲线</option>
                  </select>
                </label>
                {inputKind === "summary" ? (
                  <>
                    <label className="space-y-1.5 text-xs font-medium">
                      指标值
                      <Input
                        type="number"
                        step="any"
                        required
                        value={value}
                        onChange={(event) => setValue(event.target.value)}
                      />
                    </label>
                    <label className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={isBest}
                        onChange={(event) => setIsBest(event.target.checked)}
                      />
                      标记为本次运行的最佳记录
                    </label>
                  </>
                ) : (
                  <label className="space-y-1.5 text-xs font-medium sm:col-span-2">
                    曲线数据（每行 {inputKind},value）
                    <Textarea
                      required
                      value={curve}
                      onChange={(event) => setCurve(event.target.value)}
                      placeholder={"1,0.68\n2,0.72\n3,0.75"}
                      className="font-mono"
                    />
                  </label>
                )}
                <div className="sm:col-span-2">
                  <Button
                    disabled={saving || !definitionId || archived}
                    type="submit"
                  >
                    {saving ? "保存中…" : "保存指标"}
                  </Button>
                </div>
              </form>
            ) : (
              <EmptyState
                title="尚无指标定义"
                detail="先定义指标的单位、方向和评估协议，再录入实际结果。"
              />
            )}
            {!metrics.length ? (
              <EmptyState
                title="尚无实验结果"
                detail="录入汇总结果或 Step/Epoch 曲线后显示，不会生成示例数值。"
              />
            ) : (
              groups.map((group) => {
                const steps = group.items
                  .filter(
                    (item) => item.step !== null && item.step !== undefined,
                  )
                  .sort((a, b) => a.step! - b.step!);
                const epochs = group.items
                  .filter(
                    (item) =>
                      item.step == null &&
                      item.epoch !== null &&
                      item.epoch !== undefined,
                  )
                  .sort((a, b) => a.epoch! - b.epoch!);
                const summary = group.items.filter(
                  (item) => item.step == null && item.epoch == null,
                );
                return (
                  <section
                    key={`${group.definition.id}:${group.split}`}
                    className="space-y-3 rounded-lg border border-[var(--border)] p-4"
                  >
                    <div>
                      <h3 className="text-sm font-semibold">
                        {metricTitle(group.definition, group.split)}
                      </h3>
                      <p className="mt-1 text-xs leading-5 text-[var(--muted)]">
                        {group.definition.evaluation_protocol} · 单位：
                        {group.definition.unit ?? "未指定"} ·{" "}
                        {group.definition.higher_is_better
                          ? "越高越好"
                          : "越低越好"}
                      </p>
                    </div>
                    {summary.length > 0 && (
                      <div className="flex flex-wrap gap-3">
                        {summary.map((item) => (
                          <p
                            key={item.id}
                            className="text-xl font-semibold tabular-nums"
                          >
                            {item.value}
                            <span className="ml-1 text-xs font-normal text-[var(--muted)]">
                              {group.definition.unit ?? ""}
                              {item.is_best ? " · Best" : " · 汇总"}
                            </span>
                          </p>
                        ))}
                      </div>
                    )}
                    {steps.length > 0 && (
                      <MetricChart
                        title={metricTitle(group.definition, group.split)}
                        unit={group.definition.unit ?? null}
                        axisLabel="Step"
                        series={group.stepSeries}
                      />
                    )}
                    {epochs.length > 0 && (
                      <MetricChart
                        title={metricTitle(group.definition, group.split)}
                        unit={group.definition.unit ?? null}
                        axisLabel="Epoch"
                        series={group.epochSeries}
                      />
                    )}
                    <details>
                      <summary className="cursor-pointer text-xs text-[var(--accent)]">
                        查看 {group.items.length} 条原始指标
                      </summary>
                      <div className="mt-3 overflow-x-auto">
                        <table className="w-full text-left text-xs">
                          <thead className="text-[var(--muted)]">
                            <tr>
                              {["Step", "Epoch", "值", "测量时间", "Best"].map(
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
                            {group.items.map((item) => (
                              <tr key={item.id}>
                                <td className="py-2 pr-4">
                                  {item.step ?? "—"}
                                </td>
                                <td className="py-2 pr-4">
                                  {item.epoch ?? "—"}
                                </td>
                                <td className="py-2 pr-4 font-mono">
                                  {item.value}
                                </td>
                                <td className="py-2 pr-4">
                                  {item.measured_at
                                    ? new Date(item.measured_at).toLocaleString(
                                        "zh-CN",
                                      )
                                    : "未记录"}
                                </td>
                                <td className="py-2">
                                  {item.is_best ? "是" : "否"}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </details>
                  </section>
                );
              })
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
