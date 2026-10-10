"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/ui/state";
import { RegistryField, RegistryText, RemoveRowButton } from "./fields";
import { api } from "@/lib/api";
import type {
  ModelVersion,
  ModelVersionCreate,
  CodeRepositoryCreate,
  CodeRepository,
} from "@/lib/experiments";
import {
  nullableNumber,
  nullableText,
  requiredInteger,
  registryItems,
} from "@/lib/experiments";

export function ModelVersionForm({
  modelId,
  onCreated,
}: {
  modelId: string;
  onCreated: (version: ModelVersion) => void;
}) {
  const [version, setVersion] = useState("");
  const [repositoryId, setRepositoryId] = useState("");
  const [repositories, setRepositories] = useState<CodeRepository[]>([]);
  const [repositoryError, setRepositoryError] = useState("");
  const [commit, setCommit] = useState("");
  const [inputSize, setInputSize] = useState("");
  const [parameters, setParameters] = useState("");
  const [flops, setFlops] = useState("");
  const [fps, setFps] = useState("");
  const [checkpointId, setCheckpointId] = useState("");
  const [components, setComponents] = useState<
    { type: string; name: string; description: string; order: string }[]
  >([]);
  const [newRepository, setNewRepository] = useState("");
  const [newRepositoryUrl, setNewRepositoryUrl] = useState("");
  const [newRepositoryPath, setNewRepositoryPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [repositoryBusy, setRepositoryBusy] = useState(false);
  const [error, setError] = useState("");
  const loadRepositories = useCallback(async () => {
    try {
      setRepositories(
        await registryItems<CodeRepository>("/code-repositories"),
      );
      setRepositoryError("");
    } catch (cause) {
      setRepositoryError(
        cause instanceof Error ? cause.message : "无法读取代码仓库",
      );
    }
  }, []);
  useEffect(() => {
    queueMicrotask(() => void loadRepositories());
  }, [loadRepositories]);

  async function createRepository() {
    setRepositoryBusy(true);
    setRepositoryError("");
    try {
      const body: CodeRepositoryCreate = {
        name: newRepository.trim(),
        url: nullableText(newRepositoryUrl),
        local_uri: nullableText(newRepositoryPath),
      };
      const repository = await api.post<CodeRepository>(
        "/code-repositories",
        body,
      );
      setRepositories((rows) => [repository, ...rows]);
      setRepositoryId(repository.id);
      setNewRepository("");
      setNewRepositoryUrl("");
      setNewRepositoryPath("");
    } catch (cause) {
      setRepositoryError(
        cause instanceof Error ? cause.message : "登记代码仓库失败",
      );
    } finally {
      setRepositoryBusy(false);
    }
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const body: ModelVersionCreate = {
        version: version.trim(),
        code_repository_id: nullableText(repositoryId),
        git_commit: nullableText(commit),
        input_size: nullableText(inputSize),
        parameters: nullableNumber(parameters, "模型参数量", true),
        flops: nullableNumber(flops, "FLOPs"),
        fps: nullableNumber(fps, "FPS"),
        checkpoint_attachment_id: nullableText(checkpointId),
        components: components.map((row) => ({
          component_type: row.type.trim(),
          name: row.name.trim(),
          description: nullableText(row.description),
          sort_order: requiredInteger(row.order, "模块顺序"),
        })),
      };
      const created = await api.post<ModelVersion>(
        "/models/" + modelId + "/versions",
        body,
      );
      setVersion("");
      setComponents([]);
      setCommit("");
      setInputSize("");
      setParameters("");
      setFlops("");
      setFps("");
      setCheckpointId("");
      onCreated(created);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "创建模型版本失败");
    } finally {
      setBusy(false);
    }
  }
  return (
    <form onSubmit={submit} className="space-y-5">
      {error && <ErrorState message={error} />}
      <fieldset disabled={busy} className="space-y-5">
        <p className="text-xs leading-5 text-[var(--muted)]">
          登记版本时冻结代码、结构与权重来源。FPS、FLOPs
          仅填写已测得或计算得到的数值。
        </p>
        <div className="grid gap-4 sm:grid-cols-2">
          <RegistryField
            label="模型版本名"
            required
            value={version}
            onChange={(event) => setVersion(event.target.value)}
            maxLength={120}
          />
          <RegistryField
            label="输入尺寸"
            value={inputSize}
            onChange={(event) => setInputSize(event.target.value)}
            placeholder="例如 1×6×640×640"
          />
          <RegistryField
            label="模型参数量（可空）"
            type="number"
            min={0}
            step={1}
            value={parameters}
            onChange={(event) => setParameters(event.target.value)}
          />
          <RegistryField
            label="FLOPs（可空）"
            type="number"
            min={0}
            step="any"
            value={flops}
            onChange={(event) => setFlops(event.target.value)}
          />
          <RegistryField
            label="FPS（可空）"
            type="number"
            min={0}
            step="any"
            value={fps}
            onChange={(event) => setFps(event.target.value)}
          />
          <RegistryField
            label="模型 Git Commit"
            value={commit}
            onChange={(event) => setCommit(event.target.value)}
            maxLength={64}
          />
        </div>
        <label className="block space-y-1.5 text-xs font-medium">
          代码仓库
          <select
            aria-label="模型代码仓库"
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
        {repositoryError && (
          <ErrorState
            message={repositoryError}
            onRetry={() => void loadRepositories()}
          />
        )}
        <details className="rounded border border-[var(--border)] p-3">
          <summary className="cursor-pointer text-xs font-medium">
            登记代码仓库来源
          </summary>
          <div className="mt-3 space-y-3">
            <RegistryField
              label="仓库名称"
              value={newRepository}
              onChange={(event) => setNewRepository(event.target.value)}
            />
            <RegistryField
              label="仓库 URL（可空）"
              value={newRepositoryUrl}
              onChange={(event) => setNewRepositoryUrl(event.target.value)}
            />
            <RegistryField
              label="仓库本地位置（可空）"
              value={newRepositoryPath}
              onChange={(event) => setNewRepositoryPath(event.target.value)}
            />
            <Button
              type="button"
              size="sm"
              variant="secondary"
              disabled={repositoryBusy || !newRepository.trim()}
              onClick={() => void createRepository()}
            >
              {repositoryBusy ? "登记中…" : "登记仓库元数据"}
            </Button>
          </div>
        </details>
        <RegistryField
          label="已有 Checkpoint 附件 ID（可空）"
          value={checkpointId}
          onChange={(event) => setCheckpointId(event.target.value)}
          placeholder="后续可在运行页面上传权重并关联附件"
        />
        <div className="space-y-3">
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-xs font-semibold">结构模块</h3>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              onClick={() =>
                setComponents((rows) => [
                  ...rows,
                  {
                    type: "",
                    name: "",
                    description: "",
                    order: String(rows.length),
                  },
                ])
              }
            >
              添加结构模块
            </Button>
          </div>
          {components.map((row, index) => (
            <div
              key={index}
              className="space-y-3 rounded border border-[var(--border)] p-3"
            >
              <div className="grid gap-3 sm:grid-cols-2">
                <RegistryField
                  label={"模块类型 " + (index + 1)}
                  required
                  value={row.type}
                  onChange={(event) =>
                    setComponents((rows) =>
                      rows.map((item, i) =>
                        i === index
                          ? { ...item, type: event.target.value }
                          : item,
                      ),
                    )
                  }
                  placeholder="Backbone / Neck / Head / Fusion / Loss"
                />
                <RegistryField
                  label={"模块名称 " + (index + 1)}
                  required
                  value={row.name}
                  onChange={(event) =>
                    setComponents((rows) =>
                      rows.map((item, i) =>
                        i === index
                          ? { ...item, name: event.target.value }
                          : item,
                      ),
                    )
                  }
                />
                <RegistryField
                  label={"模块顺序 " + (index + 1)}
                  type="number"
                  required
                  min={0}
                  step={1}
                  value={row.order}
                  onChange={(event) =>
                    setComponents((rows) =>
                      rows.map((item, i) =>
                        i === index
                          ? { ...item, order: event.target.value }
                          : item,
                      ),
                    )
                  }
                />
              </div>
              <RegistryText
                label={"模块说明 " + (index + 1)}
                value={row.description}
                onChange={(event) =>
                  setComponents((rows) =>
                    rows.map((item, i) =>
                      i === index
                        ? { ...item, description: event.target.value }
                        : item,
                    ),
                  )
                }
              />
              <RemoveRowButton
                label={"移除结构模块 " + (index + 1)}
                onClick={() =>
                  setComponents((rows) => rows.filter((_, i) => i !== index))
                }
              />
            </div>
          ))}
        </div>
        <Button type="submit" disabled={busy || !version.trim()}>
          {busy ? "登记中…" : "登记模型版本"}
        </Button>
      </fieldset>
    </form>
  );
}
