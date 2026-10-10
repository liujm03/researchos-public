"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { EmptyState, LoadingState } from "@/components/ui/state";
import { api } from "@/lib/api";
import { BaselineInputError } from "./input-error";
import type { components } from "@/lib/generated";

type Resource =
  components["schemas"]["ModelOut"] | components["schemas"]["DatasetOut"];
type Resources =
  components["schemas"]["ModelPage"] | components["schemas"]["DatasetPage"];
type Version =
  | components["schemas"]["ModelVersionOut"]
  | components["schemas"]["DatasetVersionOut"];
type Versions =
  | components["schemas"]["ModelVersionPage"]
  | components["schemas"]["DatasetVersionPage"];
const selectClass =
  "h-9 w-full rounded border border-[var(--border)] bg-[var(--background)] px-2 text-sm";

/** Existing immutable registry versions are choices, not proof of available bytes. */
export function RegistryVersionPicker({
  kind,
  value,
  onChange,
  disabled = false,
}: {
  kind: "models" | "datasets";
  value: string;
  onChange: (version: Version | null) => void;
  disabled?: boolean;
}) {
  const title = kind === "models" ? "模型" : "数据集";
  const [resources, setResources] = useState<Resource[]>([]);
  const [resourceId, setResourceId] = useState("");
  const [versions, setVersions] = useState<Version[]>([]);
  const [nextResourceOffset, setNextResourceOffset] = useState<number | null>(
    null,
  );
  const [nextVersionOffset, setNextVersionOffset] = useState<number | null>(
    null,
  );
  const [loading, setLoading] = useState(true);
  const [versionLoading, setVersionLoading] = useState(false);
  const [error, setError] = useState("");
  const [versionError, setVersionError] = useState("");
  const seq = useRef(0);
  const versionSeq = useRef(0);
  const selectedValue = useRef(value);
  const onChangeRef = useRef(onChange);
  useEffect(() => {
    selectedValue.current = value;
    onChangeRef.current = onChange;
  }, [value, onChange]);
  const loadResources = useCallback(
    async (offset = 0) => {
      const token = ++seq.current;
      setLoading(true);
      try {
        const result = await api.get<Resources>(
          `/${kind}?limit=30&offset=${offset}`,
        );
        if (token !== seq.current) return;
        setResources((old) =>
          offset
            ? [
                ...old,
                ...result.items.filter(
                  (item) => !old.some((existing) => existing.id === item.id),
                ),
              ]
            : result.items,
        );
        setNextResourceOffset(
          offset + result.limit < result.total ? offset + result.limit : null,
        );
        setError("");
      } catch (cause) {
        if (token === seq.current)
          setError(
            cause instanceof Error ? cause.message : `无法读取${title}登记`,
          );
      } finally {
        if (token === seq.current) setLoading(false);
      }
    },
    [kind, title],
  );
  const loadVersions = useCallback(
    async (id: string, offset = 0) => {
      const token = ++versionSeq.current;
      setVersionLoading(true);
      try {
        const result = await api.get<Versions>(
          `/${kind}/${encodeURIComponent(id)}/versions?limit=30&offset=${offset}`,
        );
        if (token !== versionSeq.current) return;
        setVersions((old) => {
          const retained = offset
            ? old
            : old.filter((item) => item.id === selectedValue.current);
          return [
            ...retained,
            ...result.items.filter(
              (item) => !retained.some((existing) => existing.id === item.id),
            ),
          ];
        });
        setNextVersionOffset(
          offset + result.limit < result.total ? offset + result.limit : null,
        );
        setVersionError("");
      } catch (cause) {
        if (token === versionSeq.current)
          setVersionError(
            cause instanceof Error ? cause.message : `无法读取${title}版本`,
          );
      } finally {
        if (token === versionSeq.current) setVersionLoading(false);
      }
    },
    [kind, title],
  );
  useEffect(() => {
    queueMicrotask(() => void loadResources());
    return () => {
      seq.current += 1;
    };
  }, [loadResources]);
  useEffect(() => {
    if (!value) return;
    let active = true;
    void api
      .get<Version>(
        `/${kind === "models" ? "model" : "dataset"}-versions/${encodeURIComponent(value)}`,
      )
      .then(async (version) => {
        if (!active) return;
        const parent =
          "model_id" in version ? version.model_id : version.dataset_id;
        setResourceId(parent);
        setVersions((old) =>
          old.some((row) => row.id === version.id) ? old : [version, ...old],
        );
        const resource = await api.get<Resource>(
          `/${kind}/${encodeURIComponent(parent)}`,
        );
        if (!active) return;
        setResources((old) =>
          old.some((row) => row.id === resource.id) ? old : [resource, ...old],
        );
        await loadVersions(parent);
      })
      .catch((cause) => {
        if (active)
          setVersionError(
            cause instanceof Error ? cause.message : `无法恢复所选${title}版本`,
          );
      });
    return () => {
      active = false;
    };
  }, [kind, value, loadVersions, title]);
  function chooseResource(id: string) {
    versionSeq.current += 1;
    setResourceId(id);
    setVersions([]);
    setVersionError("");
    setNextVersionOffset(null);
    onChangeRef.current(null);
    if (id) void loadVersions(id);
  }
  return (
    <section
      className="space-y-3 rounded border border-[var(--border)] p-3"
      aria-label={`${title}版本选择`}
    >
      <h3 className="text-sm font-medium">{title}版本（可稍后补齐）</h3>
      {error && (
        <BaselineInputError
          message={error}
          onRetry={() => void loadResources()}
        />
      )}
      {loading && !resources.length ? (
        <LoadingState label={`正在读取本人${title}…`} />
      ) : (
        <label className="block space-y-1 text-xs">
          按名称选择{title}
          <select
            aria-label={`按名称选择${title}`}
            className={selectClass}
            disabled={disabled || loading}
            value={resourceId}
            onChange={(event) => chooseResource(event.target.value)}
          >
            <option value="">暂不绑定</option>
            {resources.map((row) => (
              <option key={row.id} value={row.id}>
                {row.name} · {row.task}
              </option>
            ))}
          </select>
        </label>
      )}
      {!loading && !error && !resources.length && (
        <EmptyState title={`尚无${title}登记`} />
      )}
      {nextResourceOffset !== null && (
        <Button
          type="button"
          size="sm"
          variant="secondary"
          disabled={disabled || loading}
          onClick={() => void loadResources(nextResourceOffset)}
        >
          加载更多{title}
        </Button>
      )}
      {resourceId && (
        <>
          {versionError && (
            <BaselineInputError
              message={versionError}
              onRetry={() => void loadVersions(resourceId)}
            />
          )}
          {versionLoading && !versions.length ? (
            <LoadingState label={`正在读取${title}不可变版本…`} />
          ) : (
            <label className="block space-y-1 text-xs">
              选择{title}版本
              <select
                aria-label={`选择${title}版本`}
                className={selectClass}
                disabled={disabled || versionLoading}
                value={value}
                onChange={(event) =>
                  onChangeRef.current(
                    versions.find((row) => row.id === event.target.value) ??
                      null,
                  )
                }
              >
                <option value="">暂不绑定具体版本</option>
                {versions.map((version) => (
                  <option key={version.id} value={version.id}>
                    {version.version} ·{" "}
                    {new Date(version.created_at).toLocaleDateString("zh-CN")}
                  </option>
                ))}
              </select>
            </label>
          )}
          {!versionLoading && !versionError && !versions.length && (
            <p className="text-xs text-[var(--muted)]">
              此资源尚无已登记版本。
            </p>
          )}
          {nextVersionOffset !== null && (
            <Button
              type="button"
              size="sm"
              variant="secondary"
              disabled={disabled || versionLoading}
              onClick={() => void loadVersions(resourceId, nextVersionOffset)}
            >
              加载更多{title}版本
            </Button>
          )}
          <Link
            href={`/${kind}/${resourceId}`}
            className="inline-block text-xs text-[var(--accent)] underline"
          >
            查看或登记此{title}的新版本
          </Link>
        </>
      )}
      <Link
        href={`/${kind}`}
        className="block text-xs text-[var(--accent)] underline"
      >
        管理本人{title}登记
      </Link>
      <p className="text-xs text-[var(--muted)]">
        绑定登记版本不会证明文件已取得、环境已安装或实验已通过。
      </p>
    </section>
  );
}
