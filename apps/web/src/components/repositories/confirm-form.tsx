"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ErrorState, LoadingState } from "@/components/ui/state";
import { api, ApiError } from "@/lib/api";
import {
  registryItems,
  type Dataset,
  type ResearchModel,
  type CodeRepository,
} from "@/lib/experiments";
import type {
  RepositoryConfirmRequest,
  RepositoryImport,
} from "@/lib/repositories";

export function RepositoryConfirmForm({
  record,
  onConfirmed,
}: {
  record: RepositoryImport;
  onConfirmed: (result: RepositoryImport) => void;
}) {
  const [name, setName] = useState(record.candidate.name);
  const [task, setTask] = useState("");
  const [modalities, setModalities] = useState("");
  const [existingId, setExistingId] = useState("");
  const [targets, setTargets] = useState<
    (Dataset | ResearchModel | CodeRepository)[]
  >([]);
  const [loading, setLoading] = useState(false);
  const [targetError, setTargetError] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [invalidPreview, setInvalidPreview] = useState(false);
  const generation = useRef(0);
  const scientificRegistry =
    record.repo_kind === "model" || record.repo_kind === "dataset";
  const path =
    record.repo_kind === "model"
      ? "/models"
      : record.repo_kind === "dataset"
        ? "/datasets"
        : "/code-repositories";

  const loadTargets = useCallback(async () => {
    if (record.existing_binding) return;
    const request = ++generation.current;
    setLoading(true);
    setTargetError("");
    try {
      const rows = await registryItems<
        Dataset | ResearchModel | CodeRepository
      >(path);
      if (request === generation.current)
        setTargets(rows.filter((item) => !item.archived_at));
    } catch (cause) {
      if (request === generation.current)
        setTargetError(
          cause instanceof Error ? cause.message : "无法读取已有资源",
        );
    } finally {
      if (request === generation.current) setLoading(false);
    }
  }, [record.existing_binding, path]);

  useEffect(() => {
    let active = true;
    const controller = generation;
    queueMicrotask(() => {
      if (active) void loadTargets();
    });
    return () => {
      active = false;
      controller.current++;
    };
  }, [loadTargets]);

  async function confirm(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      const body: RepositoryConfirmRequest = {
        expected_source_hash: record.source_hash,
      };
      if (!record.existing_binding && existingId)
        body.existing_entity_id = existingId;
      if (!record.existing_binding && !existingId) {
        const codes = [
          ...new Set(
            modalities
              .trim()
              .split(/[,，/\s]+/)
              .filter(Boolean)
              .map((code) => code.toUpperCase()),
          ),
        ];
        if (codes.some((code) => !/^[A-Z0-9_-]{1,40}$/.test(code)))
          throw new Error(
            "模态代码需要 1–40 位大写字母、数字、下划线或连字符。",
          );
        body.name = name.trim();
        if (scientificRegistry) {
          if (!task.trim()) throw new Error("请填写此资源用于哪项科研任务。");
          body.task = task.trim();
          body.modalities = codes;
        }
      }
      onConfirmed(
        await api.post<RepositoryImport>(
          `/repository-imports/${record.id}/confirm`,
          body,
        ),
      );
    } catch (cause) {
      if (
        cause instanceof ApiError &&
        ["SOURCE_HASH_MISMATCH", "INVALID_SOURCE_SNAPSHOT"].includes(cause.code)
      ) {
        setInvalidPreview(true);
        setError("当前冻结预览无法确认，请重新获取仓库预览并核对来源。");
      } else
        setError(cause instanceof Error ? cause.message : "仓库元数据确认失败");
    } finally {
      setSaving(false);
    }
  }

  const usesExisting = Boolean(record.existing_binding || existingId);
  return (
    <form
      onSubmit={confirm}
      className="space-y-4 rounded-lg border border-[var(--border)] p-4"
    >
      <div>
        <h3 className="text-sm font-semibold">确认登记目标</h3>
        <p className="mt-1 text-xs leading-5 text-[var(--muted)]">
          保存当前冻结的来源与版本，已有资源的人工字段保持原样。
        </p>
      </div>
      {record.existing_binding ? (
        <div className="space-y-1 text-xs leading-5">
          <p>已匹配来源：{record.existing_binding.entity_name}</p>
          <p className="break-all font-mono text-[var(--muted)]">
            {record.existing_binding.entity_id}
          </p>
          <p>
            科研任务：{record.existing_binding.task || "不适用"} · 模态：
            {(record.existing_binding.modalities ?? []).join(" / ") || "未记录"}
          </p>
        </div>
      ) : (
        <>
          {loading && <LoadingState label="正在读取可关联资源…" />}
          {targetError && (
            <ErrorState
              message={targetError}
              onRetry={() => void loadTargets()}
            />
          )}
          <label className="block space-y-1.5 text-xs font-medium">
            登记方式
            <select
              aria-label="登记方式"
              value={existingId}
              onChange={(event) => setExistingId(event.target.value)}
              disabled={loading || saving}
              className="block h-9 w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-3 text-sm"
            >
              <option value="">
                新建
                {record.repo_kind === "model"
                  ? "模型"
                  : record.repo_kind === "dataset"
                    ? "数据集"
                    : "代码仓库"}
              </option>
              {targets.map((item) => (
                <option key={item.id} value={item.id}>
                  关联已有：{item.name}
                </option>
              ))}
            </select>
          </label>
        </>
      )}
      {!usesExisting && (
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="space-y-1.5 text-xs font-medium sm:col-span-2">
            登记名称
            <Input
              aria-label="登记名称"
              required
              maxLength={240}
              value={name}
              onChange={(event) => setName(event.target.value)}
              disabled={saving}
            />
          </label>
          {scientificRegistry && (
            <>
              <label className="space-y-1.5 text-xs font-medium">
                科研任务
                <Input
                  aria-label="科研任务"
                  required
                  maxLength={120}
                  value={task}
                  onChange={(event) => setTask(event.target.value)}
                  placeholder="例如：山火语义分割"
                  disabled={saving}
                />
              </label>
              <label className="space-y-1.5 text-xs font-medium">
                模态代码（可选）
                <Input
                  aria-label="模态代码"
                  value={modalities}
                  onChange={(event) => setModalities(event.target.value)}
                  placeholder="RGB, IR, RGB-T, LIDAR"
                  disabled={saving}
                />
              </label>
            </>
          )}
        </div>
      )}
      {usesExisting && (
        <p className="text-xs leading-5 text-[var(--muted)]">
          本次只建立来源关联与版本回执，不修改已有名称、任务或模态。
        </p>
      )}
      {error && <ErrorState message={error} />}
      <Button type="submit" disabled={saving || loading || invalidPreview}>
        {saving ? "正在确认…" : "确认导入元数据"}
      </Button>
    </form>
  );
}
