"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/ui/state";
import {
  RegistryField,
  RegistryText,
  RemoveRowButton,
} from "@/components/registries/fields";
import { api } from "@/lib/api";
import {
  registryItems,
  nullableNumber,
  nullableText,
  type Dataset,
  type DatasetVersion,
  type ResearchModel,
  type ModelVersion,
  type CodeRepository,
  type ExperimentRun,
  type ExperimentRunCreate,
} from "@/lib/experiments";

type RunDataset = NonNullable<ExperimentRunCreate["datasets"]>[number];
type ParameterType = NonNullable<
  ExperimentRunCreate["parameters"]
>[number]["value_type"];
type DatasetRow = {
  key: string;
  datasetId: string;
  versionId: string;
  role: RunDataset["role"];
};

function DatasetRoleRow({
  row,
  index,
  datasets,
  update,
  remove,
}: {
  row: DatasetRow;
  index: number;
  datasets: Dataset[];
  update: (row: DatasetRow) => void;
  remove: () => void;
}) {
  const [versions, setVersions] = useState<DatasetVersion[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const generation = useRef(0);
  const load = useCallback(async () => {
    if (!row.datasetId) return;
    const request = ++generation.current;
    setLoading(true);
    try {
      const records = await registryItems<DatasetVersion>(
        "/datasets/" + row.datasetId + "/versions",
      );
      if (request !== generation.current) return;
      setVersions(records);
      setError("");
    } catch (cause) {
      if (request === generation.current)
        setError(cause instanceof Error ? cause.message : "无法读取数据版本");
    } finally {
      if (request === generation.current) setLoading(false);
    }
  }, [row.datasetId]);
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
  return (
    <div className="space-y-2 rounded border border-[var(--border)] p-3">
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="block space-y-1.5 text-xs font-medium">
          数据集 {index + 1}
          <select
            aria-label={"运行数据集 " + (index + 1)}
            required
            value={row.datasetId}
            onChange={(event) => {
              generation.current++;
              setVersions([]);
              update({ ...row, datasetId: event.target.value, versionId: "" });
            }}
            className="h-10 w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-3 text-sm"
          >
            <option value="">选择数据集</option>
            {datasets.map((dataset) => (
              <option key={dataset.id} value={dataset.id}>
                {dataset.name}
              </option>
            ))}
          </select>
        </label>
        <label className="block space-y-1.5 text-xs font-medium">
          数据版本 {index + 1}
          <select
            aria-label={"运行数据版本 " + (index + 1)}
            required
            value={row.versionId}
            disabled={!row.datasetId || loading}
            onChange={(event) =>
              update({ ...row, versionId: event.target.value })
            }
            className="h-10 w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-3 text-sm"
          >
            <option value="">{loading ? "读取中…" : "选择明确版本"}</option>
            {versions.map((version) => (
              <option key={version.id} value={version.id}>
                {version.version}
              </option>
            ))}
          </select>
        </label>
        <label className="block space-y-1.5 text-xs font-medium">
          用途 {index + 1}
          <select
            aria-label={"运行数据用途 " + (index + 1)}
            value={row.role}
            onChange={(event) =>
              update({ ...row, role: event.target.value as RunDataset["role"] })
            }
            className="h-10 w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-3 text-sm"
          >
            <option value="train">训练</option>
            <option value="validation">验证</option>
            <option value="test">测试</option>
            <option value="auxiliary">辅助</option>
          </select>
        </label>
      </div>
      {error && <ErrorState message={error} onRetry={() => void load()} />}
      <RemoveRowButton
        label={"移除运行数据集 " + (index + 1)}
        onClick={remove}
      />
    </div>
  );
}

export function ExperimentRunForm({
  experimentId,
  onCreated,
}: {
  experimentId: string;
  onCreated: (run: ExperimentRun) => void;
}) {
  const [models, setModels] = useState<ResearchModel[]>([]);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [repositories, setRepositories] = useState<CodeRepository[]>([]);
  const [modelId, setModelId] = useState("");
  const [modelVersions, setModelVersions] = useState<ModelVersion[]>([]);
  const [modelVersionId, setModelVersionId] = useState("");
  const [runNumber, setRunNumber] = useState("");
  const [repositoryId, setRepositoryId] = useState("");
  const [commit, setCommit] = useState("");
  const [codeVersion, setCodeVersion] = useState("");
  const [configAttachment, setConfigAttachment] = useState("");
  const [configHash, setConfigHash] = useState("");
  const [seed, setSeed] = useState("");
  const [gpu, setGpu] = useState("");
  const [python, setPython] = useState("");
  const [pytorch, setPytorch] = useState("");
  const [cuda, setCuda] = useState("");
  const [reproductionTask, setReproductionTask] = useState("");
  const [notes, setNotes] = useState("");
  const [datasetRows, setDatasetRows] = useState<DatasetRow[]>([]);
  const [parameters, setParameters] = useState<
    {
      key: string;
      name: string;
      value: string;
      type: ParameterType;
      unit: string;
    }[]
  >([]);
  const [loadingOptions, setLoadingOptions] = useState(true);
  const [optionError, setOptionError] = useState("");
  const [modelVersionError, setModelVersionError] = useState("");
  const modelVersionGeneration = useRef(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const loadOptions = useCallback(async () => {
    setLoadingOptions(true);
    try {
      const [modelRows, datasetItems, repos] = await Promise.all([
        registryItems<ResearchModel>("/models"),
        registryItems<Dataset>("/datasets"),
        registryItems<CodeRepository>("/code-repositories"),
      ]);
      setModels(modelRows);
      setDatasets(datasetItems);
      setRepositories(repos);
      setOptionError("");
    } catch (cause) {
      setOptionError(
        cause instanceof Error ? cause.message : "无法加载研究资源版本选项",
      );
    } finally {
      setLoadingOptions(false);
    }
  }, []);
  useEffect(() => {
    queueMicrotask(() => void loadOptions());
  }, [loadOptions]);
  const loadModelVersions = useCallback(async () => {
    if (!modelId) return;
    const request = ++modelVersionGeneration.current;
    try {
      const records = await registryItems<ModelVersion>(
        "/models/" + modelId + "/versions",
      );
      if (request !== modelVersionGeneration.current) return;
      setModelVersions(records);
      setModelVersionError("");
    } catch (cause) {
      if (request === modelVersionGeneration.current)
        setModelVersionError(
          cause instanceof Error ? cause.message : "无法读取模型版本",
        );
    }
  }, [modelId]);
  useEffect(() => {
    let active = true;
    const controller = modelVersionGeneration;
    queueMicrotask(() => {
      if (active) void loadModelVersions();
    });
    return () => {
      active = false;
      controller.current++;
    };
  }, [loadModelVersions]);
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const body: ExperimentRunCreate = {
        run_number: nullableNumber(runNumber, "运行编号", true),
        model_version_id: nullableText(modelVersionId),
        code_repository_id: nullableText(repositoryId),
        git_commit: nullableText(commit),
        code_version: nullableText(codeVersion),
        config_attachment_id: nullableText(configAttachment),
        config_sha256: nullableText(configHash)?.toLowerCase() ?? null,
        random_seed: nullableNumber(seed, "随机种子", true),
        gpu: nullableText(gpu),
        python_version: nullableText(python),
        pytorch_version: nullableText(pytorch),
        cuda_version: nullableText(cuda),
        reproduction_task_id: nullableText(reproductionTask),
        notes: nullableText(notes),
        datasets: datasetRows.map((row) => ({
          dataset_version_id: row.versionId,
          role: row.role,
        })),
        parameters: parameters.map((row) => ({
          name: row.name.trim(),
          value_text: row.value,
          value_type: row.type,
          unit: nullableText(row.unit),
        })),
      };
      onCreated(
        await api.post<ExperimentRun>(
          "/experiments/" + experimentId + "/runs",
          body,
        ),
      );
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "登记实验运行失败");
    } finally {
      setBusy(false);
    }
  }
  return (
    <form onSubmit={submit} className="space-y-5">
      {optionError && (
        <ErrorState message={optionError} onRetry={() => void loadOptions()} />
      )}
      {modelVersionError && (
        <ErrorState
          message={modelVersionError}
          onRetry={() => void loadModelVersions()}
        />
      )}
      {error && <ErrorState message={error} />}
      <fieldset disabled={busy || loadingOptions} className="space-y-5">
        <p className="text-xs leading-5 text-[var(--muted)]">
          此操作登记外部运行，冻结来源配置；实际训练在你自己的环境中执行。
        </p>
        <div className="grid gap-4 sm:grid-cols-2">
          <RegistryField
            label="运行编号（空则自动分配）"
            type="number"
            min={1}
            step={1}
            value={runNumber}
            onChange={(event) => setRunNumber(event.target.value)}
          />
          <RegistryField
            label="随机种子（可空）"
            type="number"
            min={0}
            step={1}
            value={seed}
            onChange={(event) => setSeed(event.target.value)}
          />
          <label className="block space-y-1.5 text-xs font-medium">
            模型
            <select
              aria-label="运行模型"
              value={modelId}
              onChange={(event) => {
                setModelId(event.target.value);
                setModelVersionId("");
                setModelVersions([]);
              }}
              className="h-10 w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-3 text-sm"
            >
              <option value="">未指定</option>
              {models.map((model) => (
                <option key={model.id} value={model.id}>
                  {model.name}
                </option>
              ))}
            </select>
          </label>
          <label className="block space-y-1.5 text-xs font-medium">
            模型版本
            <select
              aria-label="运行模型版本"
              value={modelVersionId}
              onChange={(event) => setModelVersionId(event.target.value)}
              disabled={!modelId}
              required={!!modelId}
              className="h-10 w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-3 text-sm"
            >
              <option value="">选择明确版本</option>
              {modelVersions.map((version) => (
                <option key={version.id} value={version.id}>
                  {version.version}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="space-y-3">
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-xs font-semibold">运行数据集与用途</h3>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              onClick={() =>
                setDatasetRows((rows) => [
                  ...rows,
                  {
                    key: crypto.randomUUID(),
                    datasetId: "",
                    versionId: "",
                    role: "train",
                  },
                ])
              }
            >
              添加运行数据集
            </Button>
          </div>
          {datasetRows.map((row, index) => (
            <DatasetRoleRow
              key={row.key}
              row={row}
              index={index}
              datasets={datasets}
              update={(updated) =>
                setDatasetRows((rows) =>
                  rows.map((item) => (item.key === row.key ? updated : item)),
                )
              }
              remove={() =>
                setDatasetRows((rows) =>
                  rows.filter((item) => item.key !== row.key),
                )
              }
            />
          ))}
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block space-y-1.5 text-xs font-medium">
            代码仓库
            <select
              aria-label="运行代码仓库"
              value={repositoryId}
              onChange={(event) => setRepositoryId(event.target.value)}
              className="h-10 w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-3 text-sm"
            >
              <option value="">未关联</option>
              {repositories.map((repository) => (
                <option key={repository.id} value={repository.id}>
                  {repository.name}
                </option>
              ))}
            </select>
          </label>
          <RegistryField
            label="运行 Git Commit"
            value={commit}
            onChange={(event) => setCommit(event.target.value)}
            maxLength={64}
          />
          <RegistryField
            label="代码版本说明"
            value={codeVersion}
            onChange={(event) => setCodeVersion(event.target.value)}
            maxLength={240}
          />
          <RegistryField
            label="GPU / 硬件"
            value={gpu}
            onChange={(event) => setGpu(event.target.value)}
            placeholder="例如 RTX 4090 · batch=16"
            maxLength={500}
          />
          <RegistryField
            label="Python 版本"
            value={python}
            onChange={(event) => setPython(event.target.value)}
            maxLength={80}
          />
          <RegistryField
            label="PyTorch 版本"
            value={pytorch}
            onChange={(event) => setPytorch(event.target.value)}
            maxLength={80}
          />
          <RegistryField
            label="CUDA 版本"
            value={cuda}
            onChange={(event) => setCuda(event.target.value)}
            maxLength={80}
          />
          <RegistryField
            label="关联论文复现准备任务 ID（可空）"
            value={reproductionTask}
            onChange={(event) => setReproductionTask(event.target.value)}
          />
          <RegistryField
            label="已有完整配置附件 ID（可空）"
            value={configAttachment}
            onChange={(event) => setConfigAttachment(event.target.value)}
          />
          <RegistryField
            label="完整配置 SHA-256（可空）"
            value={configHash}
            onChange={(event) => setConfigHash(event.target.value)}
            minLength={64}
            maxLength={64}
            pattern="[a-fA-F0-9]{64}"
          />
        </div>
        <div className="space-y-3">
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-xs font-semibold">关键配置参数</h3>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              onClick={() =>
                setParameters((rows) => [
                  ...rows,
                  {
                    key: crypto.randomUUID(),
                    name: "",
                    value: "",
                    type: "STRING",
                    unit: "",
                  },
                ])
              }
            >
              添加配置参数
            </Button>
          </div>
          {parameters.map((row, index) => (
            <div
              key={row.key}
              className="space-y-2 rounded border border-[var(--border)] p-3"
            >
              <div className="grid gap-3 sm:grid-cols-2">
                <RegistryField
                  label={"参数名 " + (index + 1)}
                  required
                  value={row.name}
                  onChange={(event) =>
                    setParameters((rows) =>
                      rows.map((item) =>
                        item.key === row.key
                          ? { ...item, name: event.target.value }
                          : item,
                      ),
                    )
                  }
                />
                <RegistryField
                  label={"参数值 " + (index + 1)}
                  required
                  value={row.value}
                  onChange={(event) =>
                    setParameters((rows) =>
                      rows.map((item) =>
                        item.key === row.key
                          ? { ...item, value: event.target.value }
                          : item,
                      ),
                    )
                  }
                />
                <label className="block space-y-1.5 text-xs font-medium">
                  参数类型 {index + 1}
                  <select
                    aria-label={"参数类型 " + (index + 1)}
                    value={row.type}
                    onChange={(event) =>
                      setParameters((rows) =>
                        rows.map((item) =>
                          item.key === row.key
                            ? {
                                ...item,
                                type: event.target.value as ParameterType,
                              }
                            : item,
                        ),
                      )
                    }
                    className="h-10 w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-3 text-sm"
                  >
                    <option value="STRING">文本</option>
                    <option value="INTEGER">整数</option>
                    <option value="FLOAT">小数</option>
                    <option value="BOOLEAN">布尔值</option>
                  </select>
                </label>
                <RegistryField
                  label={"参数单位 " + (index + 1)}
                  value={row.unit}
                  onChange={(event) =>
                    setParameters((rows) =>
                      rows.map((item) =>
                        item.key === row.key
                          ? { ...item, unit: event.target.value }
                          : item,
                      ),
                    )
                  }
                />
              </div>
              <RemoveRowButton
                label={"移除配置参数 " + (index + 1)}
                onClick={() =>
                  setParameters((rows) =>
                    rows.filter((item) => item.key !== row.key),
                  )
                }
              />
            </div>
          ))}
        </div>
        <RegistryText
          label="运行备注"
          value={notes}
          onChange={(event) => setNotes(event.target.value)}
          maxLength={10000}
        />
        <Button type="submit" disabled={busy || loadingOptions}>
          {busy ? "登记中…" : "登记实验运行"}
        </Button>
      </fieldset>
    </form>
  );
}
