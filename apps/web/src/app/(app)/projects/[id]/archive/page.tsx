"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { ArrowLeft, FileText, GitBranch, ShieldCheck } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { api, type Project } from "@/lib/api";
import { ArchiveJobsWorkspace } from "@/components/projects/archive-jobs-workspace";
import { ProjectProvisioningWorkspace } from "@/components/projects/project-provisioning-workspace";
import type { components } from "@/lib/generated";

type Capability = components["schemas"]["ArchiveStatusOut"];
type Inventory = components["schemas"]["ArchiveInventoryOut"];
type Binding = components["schemas"]["ArchiveBindingOut"];
type Version = components["schemas"]["ArchiveVersionOut"];
type ArchiveFile = components["schemas"]["ArchiveFileOut"];

function timestamp(value: string | null | undefined) {
  return value ? new Date(value).toLocaleString("zh-CN") : "尚未核验";
}

function githubRepository(binding: Binding) {
  if (
    ![binding.github_owner, binding.github_repository].every((value) =>
      /^[A-Za-z0-9_.-]+$/.test(value),
    )
  )
    return null;
  return `https://github.com/${encodeURIComponent(binding.github_owner)}/${encodeURIComponent(binding.github_repository)}`;
}

function VersionCard({
  projectId,
  version,
  binding,
}: {
  projectId: string;
  version: Version;
  binding: Binding;
}) {
  const [files, setFiles] = useState<ArchiveFile[] | null>(null);
  const [visible, setVisible] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const repository = githubRepository(binding);
  const remoteVerified = version.status === "VERIFIED_REMOTE";
  const commitUrl =
    remoteVerified && repository && /^[a-f0-9]{40}$/.test(version.commit_sha)
      ? `${repository}/commit/${version.commit_sha}`
      : null;

  async function loadFiles() {
    setVisible(true);
    setBusy(true);
    setError("");
    try {
      setFiles(
        await api.get<ArchiveFile[]>(
          `/projects/${projectId}/archive/versions/${version.id}/files`,
        ),
      );
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "无法读取版本文件清单");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card data-testid="archive-version">
      <CardHeader>
        <div className="min-w-0">
          <h3 className="break-all font-semibold">{version.tag}</h3>
          <p className="mt-1 text-xs text-[var(--muted)]">
            登记于 {timestamp(version.created_at)}
          </p>
        </div>
        <span
          className={`shrink-0 rounded border px-2 py-1 text-xs ${remoteVerified ? "border-[var(--accent)] text-[var(--accent)]" : "border-[var(--border)] text-[var(--muted)]"}`}
        >
          {remoteVerified ? "远端版本已核验" : "仅本地版本"}
        </span>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <p>
          {version.file_count} 个文件 ·{" "}
          {version.total_bytes.toLocaleString("zh-CN")} 字节
        </p>
        <details className="rounded border border-[var(--border)]">
          <summary className="cursor-pointer p-3 text-xs">
            查看版本校验与远端回执
          </summary>{" "}
          <dl className="grid gap-2 text-xs">
            <div>
              <dt className="text-[var(--muted)]">Commit SHA</dt>
              <dd className="mt-1 break-all font-mono">
                {commitUrl ? (
                  <a
                    href={commitUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-[var(--accent)] underline"
                  >
                    {version.commit_sha}
                  </a>
                ) : (
                  version.commit_sha
                )}
              </dd>
            </div>
            <div>
              <dt className="text-[var(--muted)]">Manifest SHA-256</dt>
              <dd className="mt-1 break-all font-mono">
                {version.manifest_sha256}
              </dd>
            </div>
            <div>
              <dt className="text-[var(--muted)]">父版本 Commit</dt>
              <dd className="mt-1 break-all font-mono">
                {version.parent_commit || "首个版本"}
              </dd>
            </div>
            <div>
              <dt className="text-[var(--muted)]">远端 Tag Commit</dt>
              <dd className="mt-1 break-all font-mono">
                {version.remote_tag_commit || "尚无远端回执"}
              </dd>
            </div>
            <div>
              <dt className="text-[var(--muted)]">远端版本核验时间</dt>
              <dd className="mt-1">{timestamp(version.remote_verified_at)}</dd>
            </div>
          </dl>
        </details>
        <p className="break-all text-xs text-[var(--muted)]">
          来源清单：.researchos/versions/{version.tag}.json
        </p>
        <Button
          variant="secondary"
          size="sm"
          disabled={busy}
          aria-expanded={visible}
          onClick={() => {
            if (visible) setVisible(false);
            else if (files) setVisible(true);
            else void loadFiles();
          }}
        >
          <FileText className="h-4 w-4" />
          {busy ? "正在读取清单…" : visible ? "收起文件清单" : "查看文件清单"}
        </Button>
        {visible && (
          <section aria-label={`${version.tag} 文件清单`} className="space-y-2">
            {busy && <LoadingState label="正在读取版本文件清单…" />}
            {error && (
              <ErrorState message={error} onRetry={() => void loadFiles()} />
            )}
            {!busy &&
              !error &&
              files &&
              (files.length ? (
                <div className="max-h-96 overflow-auto rounded border border-[var(--border)]">
                  <table className="w-full text-left text-xs">
                    <caption className="sr-only">
                      {version.tag} 的冻结文件路径、字节数和 SHA-256
                    </caption>
                    <thead className="sticky top-0 bg-[var(--surface)]">
                      <tr>
                        <th scope="col" className="p-2">
                          文件
                        </th>
                        <th scope="col" className="p-2">
                          字节
                        </th>
                        <th scope="col" className="p-2">
                          SHA-256
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {files.map((file) => (
                        <tr
                          key={file.path}
                          className="border-t border-[var(--border)]"
                        >
                          <td className="break-all p-2">{file.path}</td>
                          <td className="whitespace-nowrap p-2">
                            {file.size_bytes.toLocaleString("zh-CN")}
                          </td>
                          <td className="break-all p-2 font-mono">
                            {file.sha256}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <EmptyState title="此版本没有文件记录" />
              ))}
          </section>
        )}
      </CardContent>
    </Card>
  );
}

export default function ProjectArchivePage() {
  const { id } = useParams<{ id: string }>();
  const [project, setProject] = useState<Project | null>(null);
  const [capability, setCapability] = useState<Capability | null>(null);
  const [inventory, setInventory] = useState<Inventory | null>(null);
  const [workspace, setWorkspace] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const generation = useRef(0);

  const refreshVersionRecords = useCallback(async () => {
    const current = generation.current;
    const result = await api.get<Inventory>(`/projects/${id}/archive`);
    if (current === generation.current) {
      setInventory(result);
      if (result.binding) setWorkspace(result.binding.workspace_key);
    }
  }, [id]);

  const load = useCallback(async () => {
    const current = ++generation.current;
    setLoading(true);
    setBusy(false);
    setError("");
    setNotice("");
    try {
      const [projectResult, capabilityResult, inventoryResult] =
        await Promise.all([
          api.get<Project>(`/projects/${id}`),
          api.get<Capability>("/project-archives/capability"),
          api.get<Inventory>(`/projects/${id}/archive`),
        ]);
      if (current !== generation.current) return;
      setProject(projectResult);
      setCapability(capabilityResult);
      setInventory(inventoryResult);
      setWorkspace(inventoryResult.binding?.workspace_key ?? "");
    } catch (cause) {
      if (current === generation.current)
        setError(cause instanceof Error ? cause.message : "无法加载项目归档");
    } finally {
      if (current === generation.current) setLoading(false);
    }
  }, [id]);
  useEffect(() => {
    let active = true;
    void Promise.resolve().then(() => {
      if (active) void load();
    });
    return () => {
      active = false;
      generation.current += 1;
    };
  }, [load]);

  async function importArchive(event: FormEvent) {
    event.preventDefault();
    if (!workspace || !capability?.enabled || busy) return;
    const current = generation.current;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await api.post<Inventory>(
        `/projects/${id}/archive/import`,
        { workspace_key: workspace },
      );
      if (current !== generation.current) return;
      setInventory(result);
      setWorkspace(result.binding?.workspace_key ?? workspace);
      setNotice("现有归档已核验并接入；未上传代码。");
    } catch (cause) {
      if (current === generation.current)
        setError(cause instanceof Error ? cause.message : "归档接入失败");
    } finally {
      if (current === generation.current) setBusy(false);
    }
  }

  if (loading) return <LoadingState label="正在加载项目归档…" />;
  if (!project || !capability || !inventory)
    return (
      <ErrorState
        message={error || "归档数据不可用"}
        onRetry={() => void load()}
      />
    );
  const binding = inventory.binding;
  const repositoryUrl = binding ? githubRepository(binding) : null;
  const workspaceListed = capability.workspaces.some(
    (item) => item.key === workspace,
  );
  const workspaceAvailable = workspaceListed || !!binding?.managed_folder_name;

  return (
    <div className="space-y-6">
      <Link
        href={`/projects/${id}`}
        className="inline-flex items-center gap-2 text-xs text-[var(--muted)] hover:text-[var(--accent)]"
      >
        <ArrowLeft className="h-4 w-4" />
        返回课题
      </Link>
      <header>
        <p className="mb-1 text-xs uppercase tracking-[0.18em] text-[var(--accent)]">
          Project archive
        </p>
        <h1 className="text-2xl font-semibold">{project.name} · 版本归档</h1>
        <p className="mt-2 text-sm leading-6 text-[var(--muted)]">
          连接本项目已有的独立 Git
          归档，查阅版本、冻结文件清单与私有仓库核验回执。代码归档与科研数据备份分别保存。
        </p>
      </header>
      {error && (
        <div role="alert">
          <ErrorState message={error} />
        </div>
      )}
      {notice && (
        <p
          role="status"
          className="rounded-md border border-[var(--accent)] p-3 text-sm"
        >
          {notice}
        </p>
      )}
      {binding ? (
        <>
          <Card>
            <CardHeader>
              <h2 className="flex items-center gap-2 font-semibold">
                <ShieldCheck className="h-4 w-4 text-[var(--accent)]" />
                已绑定私有仓库
              </h2>
              <span className="text-xs text-[var(--accent)]">
                上次核验 PRIVATE
              </span>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <p className="break-all">
                {repositoryUrl ? (
                  <a
                    href={repositoryUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-[var(--accent)] underline"
                  >
                    {binding.github_owner}/{binding.github_repository}
                  </a>
                ) : (
                  `${binding.github_owner}/${binding.github_repository}`
                )}
              </p>
              <details className="rounded border border-[var(--border)]">
                <summary className="cursor-pointer p-3 text-xs">
                  查看绑定身份
                </summary>{" "}
                <dl className="grid gap-3 text-xs sm:grid-cols-2">
                  <div>
                    <dt className="text-[var(--muted)]">
                      GitHub Owner ID / Repository ID
                    </dt>
                    <dd className="mt-1 font-mono">
                      {binding.github_owner_id} / {binding.github_repository_id}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-[var(--muted)]">仓库身份核验时间</dt>
                    <dd className="mt-1">{timestamp(binding.verified_at)}</dd>
                  </div>
                  <div>
                    <dt className="text-[var(--muted)]">工作区</dt>
                    <dd className="mt-1 break-all">{binding.workspace_key}</dd>
                  </div>
                  <div>
                    <dt className="text-[var(--muted)]">本地项目身份</dt>
                    <dd className="mt-1 break-all font-mono">
                      {binding.local_project_id}
                    </dd>
                  </div>
                </dl>
              </details>
              <p className="text-xs text-[var(--muted)]">
                仓库私有性与版本是否已经推送分别核验；历史回执不代表当前远端权限未发生变化。
              </p>
            </CardContent>
          </Card>
          {inventory.versions.length > 0 && (
            <p className="text-sm">
              最近登记版本：
              {
                [...inventory.versions].sort(
                  (a, b) =>
                    new Date(b.created_at).getTime() -
                    new Date(a.created_at).getTime(),
                )[0].tag
              }{" "}
              · 共 {inventory.versions.length} 个版本记录
            </p>
          )}
          <ArchiveJobsWorkspace
            key={binding.id}
            projectId={id}
            binding={binding}
            capability={capability}
            onVersionsChanged={refreshVersionRecords}
          />
          <section aria-label="归档版本" className="space-y-4">
            <h2 className="font-semibold">
              版本记录 · {inventory.versions.length}
            </h2>
            {inventory.versions.length ? (
              inventory.versions.map((version) => (
                <VersionCard
                  key={`${version.id}:${version.remote_verified_at}:${binding.verified_at}`}
                  projectId={id}
                  binding={binding}
                  version={version}
                />
              ))
            ) : (
              <EmptyState
                title="尚无归档版本"
                detail="项目身份已绑定；尚未发现本地版本清单。"
              />
            )}
          </section>
        </>
      ) : (
        <>
          <EmptyState
            title="本课题尚未接入归档"
            detail="选择已有独立项目工作区，核验并保存项目与私有仓库的身份绑定。"
          />
          <ProjectProvisioningWorkspace
            key={id}
            projectId={id}
            onChanged={refreshVersionRecords}
          />
        </>
      )}
      <details className="rounded-md border border-[var(--border)] bg-[var(--surface)]">
        <summary className="cursor-pointer px-4 py-3 text-sm font-medium">
          {binding ? "连接与核验设置" : "连接已有项目目录"}
        </summary>{" "}
        <Card>
          <CardHeader>
            <h2 className="font-semibold">接入现有归档</h2>
            <GitBranch className="h-4 w-4 text-[var(--muted)]" />
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-sm text-[var(--muted)]">{capability.detail}</p>
            {!capability.enabled && (
              <p className="text-sm font-medium">服务器尚未启用项目归档接入</p>
            )}
            {binding && (
              <p className="text-sm text-[var(--muted)]">
                已绑定的项目及仓库身份保持固定；再次接入将核对本地版本和远端回执。
              </p>
            )}
            <form
              onSubmit={importArchive}
              className="flex flex-wrap items-end gap-3"
            >
              <label className="min-w-56 flex-1 space-y-1.5 text-xs font-medium">
                已登记的项目工作区
                <select
                  value={workspace}
                  disabled={busy || !!binding || !capability.enabled}
                  onChange={(event) => setWorkspace(event.target.value)}
                  required
                  className="block h-9 w-full rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 text-sm"
                >
                  <option value="">请选择本课题的独立项目目录</option>
                  {capability.workspaces.map((item) => (
                    <option key={item.key} value={item.key}>
                      {item.label}
                    </option>
                  ))}
                  {binding && !workspaceListed && (
                    <option value={binding.workspace_key}>
                      {binding.managed_folder_name
                        ? `${binding.managed_folder_name}（项目独立工作区）`
                        : `${binding.workspace_key}（当前未登记）`}
                    </option>
                  )}
                </select>
              </label>
              <Button
                type="submit"
                disabled={busy || !capability.enabled || !workspaceAvailable}
              >
                {busy
                  ? "正在核验…"
                  : binding
                    ? "重新核验现有归档"
                    : "核验并接入现有归档"}
              </Button>
              <Button
                type="button"
                variant="secondary"
                disabled={busy}
                onClick={() => void load()}
              >
                刷新记录
              </Button>
            </form>
            {!capability.workspaces.length && (
              <p className="text-xs text-[var(--muted)]">
                尚无已登记的项目工作区，请在执行主机配置后刷新。
              </p>
            )}
            <p className="text-xs leading-5 text-[var(--muted)]">
              本操作读取已有身份、版本清单和 GitHub
              回执，不创建仓库或上传代码，也不会启用自动推送。请先核对工作区属于本课题。
            </p>
          </CardContent>
        </Card>
      </details>
    </div>
  );
}
