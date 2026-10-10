"use client";

import Link from "next/link";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { api } from "@/lib/api";
import type { components } from "@/lib/generated";
type Snapshot = components["schemas"]["AssetSnapshotOut"];
type Projects = components["schemas"]["ProjectPage"];

export function AssetProjectTarget({ snapshot }: { snapshot: Snapshot }) {
  const [projects, setProjects] = useState<Projects | null>(null);
  const [selected, setSelected] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  async function load(cursor?: string) {
    setLoading(true);
    setError("");
    try {
      const result = await api.get<Projects>(
        `/projects?limit=50${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
      );
      setProjects((old) =>
        cursor && old
          ? { ...result, items: [...old.items, ...result.items] }
          : result,
      );
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "目标科研项目暂不可读取",
      );
    } finally {
      setLoading(false);
    }
  }
  return (
    <section
      aria-label="选择源码缓存目标项目"
      className="space-y-3 rounded border border-[var(--border)] p-3 text-xs"
    >
      <h3 className="font-semibold">加入项目源码缓存</h3>
      <p className="leading-5 text-[var(--muted)]">
        先选择已初始化独立目录与私有仓库、位于配置科研根内的本人课题，再核对固定根目录、此真实资产快照的完整文件及复制范围。此处只读取项目和打开预览，不下载、不执行代码，也不写入工作区。
      </p>
      {snapshot.status === "PARTIAL" && (
        <p className="text-amber-700 dark:text-amber-300">
          来源仍是 PARTIAL；复制到项目不会补齐缺口或变成已验证基线。
        </p>
      )}
      {!projects && (
        <Button
          size="sm"
          variant="secondary"
          disabled={loading}
          onClick={() => void load()}
        >
          读取本人科研项目
        </Button>
      )}
      {loading && <LoadingState label="正在读取可选择项目…" />}
      {error && <ErrorState message={error} onRetry={() => void load()} />}
      {projects &&
        (projects.items.length ? (
          <>
            <label className="block space-y-1.5 font-medium">
              目标科研项目
              <select
                aria-label="目标科研项目"
                value={selected}
                disabled={loading}
                onChange={(event) => setSelected(event.target.value)}
                className="block h-9 w-full rounded border border-[var(--border)] bg-[var(--surface)] px-2 text-sm"
              >
                <option value="">请选择项目</option>
                {projects.items.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.name}
                  </option>
                ))}
              </select>
            </label>
            <p className="text-[var(--muted)]">
              项目必须已绑定本人读写根目录；预览服务会校验绑定与归属，不能输入任意路径。
            </p>
            {selected && (
              <Link
                className="inline-block text-[var(--accent)] underline"
                href={`/projects/${selected}/sources?asset_snapshot=${snapshot.id}`}
              >
                预览加入此项目的源码缓存
              </Link>
            )}
            {projects.page.next_cursor && (
              <Button
                size="sm"
                variant="secondary"
                disabled={loading}
                onClick={() => void load(projects.page.next_cursor!)}
              >
                加载更多本人项目
              </Button>
            )}
          </>
        ) : (
          <EmptyState
            title="尚无可选择的科研项目"
            detail="先创建并绑定项目读写根目录。"
          />
        ))}
    </section>
  );
}
