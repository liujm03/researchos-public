"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { ErrorState } from "@/components/ui/state";
import { api } from "@/lib/api";
import type {
  DatasetVersion,
  ExperimentRun,
  ModelVersion,
} from "@/lib/experiments";

function RecordedValue({
  label,
  value,
}: {
  label: string;
  value: string | number | null | undefined;
}) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-[var(--muted)]">{label}</dt>
      <dd className="mt-1 break-all font-mono text-xs leading-5">
        {value === null || value === undefined || value === "" ? (
          <span className="font-sans text-[var(--muted)]">未记录</span>
        ) : (
          value
        )}
      </dd>
    </div>
  );
}

export function RunProvenance({ run }: { run: ExperimentRun }) {
  const [model, setModel] = useState<ModelVersion | null>(null);
  const [datasets, setDatasets] = useState<DatasetVersion[]>([]);
  const [error, setError] = useState("");
  const generation = useRef(0);
  const modelId = run.model_version_id;
  const runDatasets = run.datasets ?? [];
  const parameters = run.parameters ?? [];
  const datasetIds = [
    ...new Set(runDatasets.map((item) => item.dataset_version_id)),
  ]
    .sort()
    .join(",");
  const load = useCallback(async () => {
    const request = ++generation.current;
    setError("");
    const [modelResult, datasetResults] = await Promise.all([
      modelId
        ? api
            .get<ModelVersion>(`/model-versions/${modelId}`)
            .then((value) => ({ value, error: false }))
            .catch(() => ({ value: null, error: true }))
        : Promise.resolve({ value: null, error: false }),
      Promise.allSettled(
        datasetIds
          ? datasetIds
              .split(",")
              .map((value) =>
                api.get<DatasetVersion>(`/dataset-versions/${value}`),
              )
          : [],
      ),
    ]);
    if (request !== generation.current) return;
    setModel(modelResult.value);
    setDatasets(
      datasetResults.flatMap((result) =>
        result.status === "fulfilled" ? [result.value] : [],
      ),
    );
    if (
      modelResult.error ||
      datasetResults.some((result) => result.status === "rejected")
    )
      setError("部分版本详情无法读取，请重试；已冻结的版本 ID 保留供核查。");
  }, [modelId, datasetIds]);
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
  const fields = [
    ["ModelVersion ID", run.model_version_id],
    ["CodeRepository ID", run.code_repository_id],
    ["Git Commit", run.git_commit],
    ["代码版本", run.code_version],
    ["配置附件 ID", run.config_attachment_id],
    ["配置 SHA-256", run.config_sha256],
    ["随机种子", run.random_seed],
    ["GPU", run.gpu],
    ["Python", run.python_version],
    ["PyTorch", run.pytorch_version],
    ["CUDA", run.cuda_version],
  ] as const;

  return (
    <Card>
      <CardHeader>
        <div>
          <h2 className="font-semibold">运行来源与配置</h2>
          <p className="mt-1 text-xs leading-5 text-[var(--muted)]">
            创建时冻结。更正模型、数据或环境需要建立新运行，历史结果保留原始来源。
          </p>
        </div>
      </CardHeader>
      <CardContent className="space-y-5">
        {error && (
          <ErrorState
            message={error}
            onRetry={() => {
              void load();
            }}
          />
        )}
        {model && (
          <p className="text-xs">
            <span className="mr-2 text-[var(--muted)]">模型版本</span>
            <Link
              href={`/models/${model.model_id}`}
              className="text-[var(--accent)] underline"
            >
              {model.version}
            </Link>
          </p>
        )}
        <dl className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {fields.map(([label, value]) => (
            <RecordedValue key={label} label={label} value={value} />
          ))}
        </dl>
        {run.reproduction_task_id && (
          <div className="text-xs">
            <span className="mr-2 text-[var(--muted)]">论文复现准备任务</span>
            <Link
              className="break-all text-[var(--accent)] underline"
              href={`/ai-tasks/${run.reproduction_task_id}`}
            >
              {run.reproduction_task_id}
            </Link>
          </div>
        )}
        <div>
          <h3 className="mb-2 text-sm font-medium">DatasetVersion 与用途</h3>
          {runDatasets.length ? (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="text-[var(--muted)]">
                  <tr>
                    <th className="py-2 pr-4 font-medium">精确版本 ID</th>
                    <th className="py-2 font-medium">角色</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--border)]">
                  {runDatasets.map((dataset) => (
                    <tr key={`${dataset.dataset_version_id}:${dataset.role}`}>
                      <td className="py-2 pr-4 font-mono">
                        {dataset.dataset_version_id}
                        {datasets
                          .filter(
                            (version) =>
                              version.id === dataset.dataset_version_id,
                          )
                          .map((version) => (
                            <Link
                              key={version.id}
                              href={`/datasets/${version.dataset_id}`}
                              className="ml-2 font-sans text-[var(--accent)] underline"
                            >
                              {version.version}
                            </Link>
                          ))}
                      </td>
                      <td className="py-2">{dataset.role}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-xs text-[var(--muted)]">未关联数据集版本。</p>
          )}
        </div>
        <div>
          <h3 className="mb-2 text-sm font-medium">关键配置参数</h3>
          {parameters.length ? (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="text-[var(--muted)]">
                  <tr>
                    <th className="py-2 pr-4 font-medium">参数</th>
                    <th className="py-2 pr-4 font-medium">值</th>
                    <th className="py-2 pr-4 font-medium">类型</th>
                    <th className="py-2 font-medium">单位</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--border)]">
                  {parameters.map((parameter) => (
                    <tr key={parameter.name}>
                      <td className="py-2 pr-4 font-mono">{parameter.name}</td>
                      <td className="py-2 pr-4 font-mono">
                        {parameter.value_text}
                      </td>
                      <td className="py-2 pr-4">{parameter.value_type}</td>
                      <td className="py-2">{parameter.unit ?? "未指定"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-xs text-[var(--muted)]">尚无关键参数记录。</p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
