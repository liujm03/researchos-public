"use client";

import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ErrorState } from "@/components/ui/state";
import { api } from "@/lib/api";
import {
  repositoryKindLabels,
  type RepositoryImport,
  type RepositoryPreviewRequest,
  type RepositoryProviders,
} from "@/lib/repositories";

export function RepositoryLookupForm({
  catalog,
  initialProvider,
  initialKind,
  onLookupStart,
  onPreview,
}: {
  catalog: RepositoryProviders;
  initialProvider: string | null;
  initialKind: string | null;
  onLookupStart: () => void;
  onPreview: (record: RepositoryImport) => void;
}) {
  const first =
    catalog.items.find(
      (item) => item.enabled && item.provider_key === initialProvider,
    ) ?? catalog.items.find((item) => item.enabled);
  const [provider, setProvider] = useState<
    RepositoryPreviewRequest["provider_key"]
  >(first?.provider_key ?? catalog.items[0]?.provider_key ?? "github");
  const [kind, setKind] = useState<RepositoryPreviewRequest["repo_kind"]>(
    first?.repo_kinds.find((item) => item === initialKind) ??
      first?.repo_kinds[0] ??
      "code",
  );
  const [repository, setRepository] = useState("");
  const [revision, setRevision] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const selected = catalog.items.find((item) => item.provider_key === provider);
  const supported = Boolean(
    selected?.enabled && selected.repo_kinds.includes(kind),
  );
  async function preview(event: FormEvent) {
    event.preventDefault();
    if (!supported) return;
    setBusy(true);
    setError("");
    onLookupStart();
    try {
      const body: RepositoryPreviewRequest = {
        provider_key: provider,
        repo_kind: kind,
        repository: repository.trim(),
        revision: revision.trim() || null,
      };
      onPreview(
        await api.post<RepositoryImport>("/repository-imports/preview", body),
      );
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "无法获取仓库元数据预览",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <form onSubmit={preview} className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="space-y-1.5 text-xs font-medium">
          仓库来源
          <select
            aria-label="仓库来源"
            value={provider}
            disabled={busy}
            onChange={(event) => {
              const next = catalog.items.find(
                (item) => item.provider_key === event.target.value,
              );
              if (!next) return;
              setProvider(next.provider_key);
              setKind(next.repo_kinds[0] ?? "code");
              setError("");
            }}
            className="block h-9 w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-3 text-sm"
          >
            {catalog.items.map((item) => (
              <option
                key={item.provider_key}
                value={item.provider_key}
                disabled={!item.enabled}
              >
                {item.label}
                {item.enabled ? "" : "（尚未启用）"}
              </option>
            ))}
          </select>
        </label>
        <label className="space-y-1.5 text-xs font-medium">
          资源类型
          <select
            aria-label="资源类型"
            value={kind}
            disabled={busy}
            onChange={(event) => {
              const next = selected?.repo_kinds.find(
                (item) => item === event.target.value,
              );
              if (next) setKind(next);
            }}
            className="block h-9 w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-3 text-sm"
          >
            {(["code", "model", "dataset", "space"] as const).map((item) => (
              <option
                key={item}
                value={item}
                disabled={!selected?.repo_kinds.includes(item)}
              >
                {repositoryKindLabels[item]}
                {selected?.repo_kinds.includes(item)
                  ? ""
                  : "（当前来源不支持）"}
              </option>
            ))}
          </select>
        </label>
        <label className="space-y-1.5 text-xs font-medium sm:col-span-2">
          仓库 URL 或 ID
          <Input
            aria-label="仓库 URL 或 ID"
            required
            maxLength={2000}
            value={repository}
            onChange={(event) => setRepository(event.target.value)}
            disabled={busy}
            placeholder={
              provider === "github"
                ? "https://github.com/owner/repository 或 owner/repository"
                : "https://huggingface.co/owner/repository 或 owner/repository"
            }
          />
        </label>
        <label className="space-y-1.5 text-xs font-medium sm:col-span-2">
          Revision（可选）
          <Input
            aria-label="Revision"
            maxLength={160}
            value={revision}
            onChange={(event) => setRevision(event.target.value)}
            disabled={busy}
            placeholder="分支、Tag 或 Commit；留空读取默认版本"
          />
        </label>
      </div>
      {selected && (
        <p className="text-xs leading-5 text-[var(--muted)]">
          {selected.token_configured
            ? "服务器已配置来源令牌。"
            : "公开仓库可匿名读取；未配置来源令牌。"}{" "}
          页面只显示配置状态，令牌由服务器环境变量管理。
        </p>
      )}
      {error && <ErrorState message={error} />}
      <Button type="submit" disabled={busy || !supported}>
        {busy ? "正在读取公开元数据…" : "获取仓库预览"}
      </Button>
    </form>
  );
}
