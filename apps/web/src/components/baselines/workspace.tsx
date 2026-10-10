"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { api, type Project } from "@/lib/api";
import { BaselineVersionEditor } from "./version-editor";
import { BaselineVersionDetail } from "./version-detail";
import type { components } from "@/lib/generated";
type Baseline = components["schemas"]["BaselineOut"];
type Baselines = components["schemas"]["BaselinePage"];
type Version = components["schemas"]["BaselineVersionOut"];
type Versions = components["schemas"]["BaselineVersionPage"];
type Create = components["schemas"]["BaselineVersionCreate"];
type Capability = components["schemas"]["BaselineCapabilityOut"];

export function BaselinesWorkspace({ projectId }: { projectId: string }) {
  const [project, setProject] = useState<Project | null>(null);
  const [capability, setCapability] = useState<Capability | null>(null);
  const [baselines, setBaselines] = useState<Baselines | null>(null);
  const [selected, setSelected] = useState<Baseline | null>(null);
  const [versions, setVersions] = useState<Versions | null>(null);
  const [version, setVersion] = useState<Version | null>(null);
  const [loading, setLoading] = useState(true);
  const [versionLoading, setVersionLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState("");
  const [versionError, setVersionError] = useState("");
  const [detailError, setDetailError] = useState("");
  const detailTarget = useRef("");
  const [message, setMessage] = useState("");
  const [editor, setEditor] = useState(false);
  const [editorKey, setEditorKey] = useState(0);
  const [parent, setParent] = useState<Version | null>(null);
  const [newName, setNewName] = useState<string | null>("");
  const [initialJobId, setInitialJobId] = useState("");
  const [baselinePage, setBaselinePage] = useState(0);
  const [baselineCursors, setBaselineCursors] = useState<(string | null)[]>([
    null,
  ]);
  const [versionPage, setVersionPage] = useState(0);
  const [versionCursors, setVersionCursors] = useState<(string | null)[]>([
    null,
  ]);
  const seq = useRef(0),
    versionSeq = useRef(0),
    detailSeq = useRef(0);
  const pendingIdentity = useRef<{ name: string; baseline: Baseline } | null>(
    null,
  );
  const baselineRetry = useRef<{ cursor: string | null; index: number }>({
    cursor: null,
    index: 0,
  });
  const versionRetry = useRef<{
    baselineId: string;
    cursor: string | null;
    index: number;
  }>({ baselineId: "", cursor: null, index: 0 });
  const endpoint = `/projects/${encodeURIComponent(projectId)}/baselines`;
  const load = useCallback(
    async (cursor: string | null = null, index = 0) => {
      const token = ++seq.current;
      setLoading(true);
      baselineRetry.current = { cursor, index };
      const results = await Promise.allSettled([
        api.get<Project>(`/projects/${encodeURIComponent(projectId)}`),
        api.get<Capability>("/baselines/capability"),
        api.get<Baselines>(
          `${endpoint}?limit=20${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
        ),
      ]);
      if (token !== seq.current) return;
      const [projectResult, capResult, listResult] = results;
      if (projectResult.status === "fulfilled") setProject(projectResult.value);
      if (capResult.status === "fulfilled") setCapability(capResult.value);
      if (listResult.status === "fulfilled") {
        setBaselines(listResult.value);
        setBaselinePage(index);
      }
      const failures = results.filter(
        (item): item is PromiseRejectedResult => item.status === "rejected",
      );
      setError(
        failures
          .map((item) =>
            item.reason instanceof Error
              ? item.reason.message
              : "基线页面资料暂不可读",
          )
          .join("；"),
      );
      setLoading(false);
    },
    [endpoint, projectId],
  );
  const loadVersions = useCallback(
    async (baselineId: string, cursor: string | null = null, index = 0) => {
      const token = ++versionSeq.current;
      setVersionLoading(true);
      versionRetry.current = { baselineId, cursor, index };
      try {
        const result = await api.get<Versions>(
          `/baselines/${encodeURIComponent(baselineId)}/versions?limit=20${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
        );
        if (token === versionSeq.current) {
          setVersions(result);
          setVersionPage(index);
          setVersionError("");
        }
      } catch (cause) {
        if (token === versionSeq.current)
          setVersionError(
            cause instanceof Error ? cause.message : "无法读取基线版本历史",
          );
      } finally {
        if (token === versionSeq.current) setVersionLoading(false);
      }
    },
    [],
  );
  const loadVersion = useCallback(
    async (id: string) => {
      detailTarget.current = id;
      const token = ++detailSeq.current;
      setDetailLoading(true);
      try {
        const result = await api.get<Version>(
          `/baseline-versions/${encodeURIComponent(id)}`,
        );
        if (result.project_id !== projectId)
          throw new Error("该基线版本属于另一课题，请从对应课题查阅。");
        if (token === detailSeq.current) {
          setVersion(result);
          setDetailError("");
        }
        return result;
      } catch (cause) {
        if (token === detailSeq.current)
          setDetailError(
            cause instanceof Error ? cause.message : "基线版本详情暂不可读",
          );
        throw cause;
      } finally {
        if (token === detailSeq.current) setDetailLoading(false);
      }
    },
    [projectId],
  );
  useEffect(() => {
    queueMicrotask(() => {
      const linked =
        new URLSearchParams(window.location.search).get("source_job") ?? "";
      setInitialJobId(linked);
      if (linked) {
        setEditor(true);
        setNewName("");
      }
      void load();
    });
    return () => {
      seq.current += 1;
      versionSeq.current += 1;
      detailSeq.current += 1;
    };
  }, [load]);
  function inspectBaseline(baseline: Baseline) {
    setSelected(baseline);
    setVersions(null);
    setVersion(null);
    setEditor(false);
    setNewName(null);
    setParent(null);
    setVersionCursors([null]);
    setVersionPage(0);
    setDetailError("");
    setMessage("");
    void loadVersions(baseline.id);
  }
  function beginNew() {
    setSelected(null);
    setParent(null);
    setNewName("");
    setEditor(true);
    setEditorKey((old) => old + 1);
    pendingIdentity.current = null;
    setMessage("");
  }
  function beginVersion(base: Version | null) {
    setParent(base);
    setNewName(null);
    setEditor(true);
    setEditorKey((old) => old + 1);
    setMessage("");
  }
  async function saveVersion(body: Create, name: string | null) {
    let identity = selected;
    if (name !== null) {
      const saved = pendingIdentity.current;
      identity =
        saved?.name === name
          ? saved.baseline
          : await api.post<Baseline>(endpoint, {
              name,
              purpose: body.purpose ?? null,
            });
      pendingIdentity.current = { name, baseline: identity };
      setSelected(identity);
      setNewName(null);
    }
    if (!identity) throw new Error("请先选择或命名此项目的基线。");
    const saved = await api.post<Version>(
      `/baselines/${encodeURIComponent(identity.id)}/versions`,
      body,
    );
    setVersion(saved);
    setParent(null);
    setEditor(false);
    pendingIdentity.current = null;
    setMessage(`版本 ${saved.version} 已登记；材料尚需显式核查，未启动运行。`);
    await loadVersions(identity.id);
    await load();
  }
  if (loading && !project)
    return <LoadingState label="正在读取项目基线与当前能力…" />;
  return (
    <div className="space-y-5">
      <Link
        href={`/projects/${projectId}`}
        className="text-xs text-[var(--accent)] underline"
      >
        返回课题
      </Link>
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">
          {project?.name ?? "项目"} · 基线与复现
        </h1>
        <p className="text-sm leading-6 text-[var(--muted)]">
          为模型、数据、来源和必需文件建立固定版本。先登记资料，再显式核查材料；科学协议和受控运行分别记录。
        </p>
      </header>
      {error && (
        <ErrorState
          message={error}
          onRetry={() =>
            void load(baselineRetry.current.cursor, baselineRetry.current.index)
          }
        />
      )}
      {message && (
        <p
          role="status"
          className="rounded border border-[var(--accent)] p-3 text-sm"
        >
          {message}
        </p>
      )}
      <div className="flex flex-wrap gap-3 text-xs">
        <Link
          href={`/projects/${projectId}/sources`}
          className="text-[var(--accent)] underline"
        >
          准备已保存源码资料
        </Link>
        <Link href="/models" className="text-[var(--accent)] underline">
          模型登记
        </Link>
        <Link href="/datasets" className="text-[var(--accent)] underline">
          数据集登记
        </Link>
      </div>
      <section
        className="space-y-3 rounded border border-[var(--border)] p-4"
        aria-label="项目基线列表"
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-semibold">已登记基线</h2>
          <Button
            type="button"
            size="sm"
            disabled={!capability?.catalog_available || loading}
            onClick={beginNew}
          >
            新增项目基线
          </Button>
        </div>
        {loading ? (
          <LoadingState label="正在读取项目基线分页…" />
        ) : baselines?.items.length ? (
          <ul className="space-y-2">
            {baselines.items.map((baseline) => (
              <li
                key={baseline.id}
                className="flex flex-wrap items-center justify-between gap-2 rounded border border-[var(--border)] p-3"
              >
                <div>
                  <p className="text-sm font-medium">{baseline.name}</p>
                  {baseline.purpose && (
                    <p className="mt-1 line-clamp-2 text-xs text-[var(--muted)]">
                      {baseline.purpose}
                    </p>
                  )}
                </div>
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  disabled={versionLoading}
                  onClick={() => inspectBaseline(baseline)}
                >
                  查看基线版本
                </Button>
              </li>
            ))}
          </ul>
        ) : (
          !error && (
            <EmptyState
              title="本项目尚无固定基线"
              detail="可以先登记缺材料的草稿，再逐步补齐为新版本。"
            />
          )
        )}
        {baselines && (
          <div className="flex items-center justify-between gap-2 text-xs">
            <Button
              type="button"
              size="sm"
              variant="secondary"
              disabled={loading || baselinePage === 0}
              onClick={() =>
                void load(
                  baselineCursors[baselinePage - 1] ?? null,
                  baselinePage - 1,
                )
              }
            >
              上一页项目基线
            </Button>
            <span>第 {baselinePage + 1} 页</span>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              disabled={loading || !baselines.page.next_cursor}
              onClick={() => {
                const next = baselines.page.next_cursor;
                if (next) {
                  setBaselineCursors((old) => [
                    ...old.slice(0, baselinePage + 1),
                    next,
                  ]);
                  void load(next, baselinePage + 1);
                }
              }}
            >
              下一页项目基线
            </Button>
          </div>
        )}
      </section>
      {selected && (
        <section
          className="space-y-3 rounded border border-[var(--border)] p-4"
          aria-label="基线不可变版本列表"
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="font-semibold">{selected.name} · 固定版本</h2>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              disabled={!capability?.catalog_available || versionLoading}
              onClick={() => beginVersion(null)}
            >
              登记独立新版本
            </Button>
          </div>
          {versionError && (
            <ErrorState
              message={versionError}
              onRetry={() =>
                void loadVersions(
                  versionRetry.current.baselineId,
                  versionRetry.current.cursor,
                  versionRetry.current.index,
                )
              }
            />
          )}
          {versionLoading ? (
            <LoadingState label="正在读取基线不可变版本…" />
          ) : versions?.items.length ? (
            <ul className="space-y-2">
              {versions.items.map((item) => (
                <li
                  key={item.id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded border border-[var(--border)] p-3 text-xs"
                >
                  <span>
                    {item.version} · {item.qualification} ·{" "}
                    {new Date(item.created_at).toLocaleString("zh-CN")}
                  </span>
                  <Button
                    type="button"
                    size="sm"
                    variant="secondary"
                    disabled={detailLoading}
                    aria-label={`查看固定版本 ${item.version}`}
                    onClick={() =>
                      void loadVersion(item.id).catch(() => undefined)
                    }
                  >
                    查看版本与材料
                  </Button>
                </li>
              ))}
            </ul>
          ) : (
            !versionError && <EmptyState title="此基线尚无固定版本" />
          )}
          {versions && (
            <div className="flex items-center justify-between gap-2 text-xs">
              <Button
                type="button"
                size="sm"
                variant="secondary"
                disabled={versionLoading || versionPage === 0}
                onClick={() =>
                  void loadVersions(
                    selected.id,
                    versionCursors[versionPage - 1] ?? null,
                    versionPage - 1,
                  )
                }
              >
                上一页基线版本
              </Button>
              <span>第 {versionPage + 1} 页</span>
              <Button
                type="button"
                size="sm"
                variant="secondary"
                disabled={versionLoading || !versions.page.next_cursor}
                onClick={() => {
                  const next = versions.page.next_cursor;
                  if (next) {
                    setVersionCursors((old) => [
                      ...old.slice(0, versionPage + 1),
                      next,
                    ]);
                    void loadVersions(selected.id, next, versionPage + 1);
                  }
                }}
              >
                下一页基线版本
              </Button>
            </div>
          )}
        </section>
      )}
      {detailError && (
        <ErrorState
          message={detailError}
          onRetry={() =>
            void loadVersion(detailTarget.current).catch(() => undefined)
          }
        />
      )}
      {detailLoading && <LoadingState label="正在读取固定版本详情…" />}
      {version && (
        <BaselineVersionDetail
          key={version.id}
          version={version}
          capability={capability}
          onChanged={async () => {
            await loadVersion(version.id);
            if (selected)
              await loadVersions(
                selected.id,
                versionCursors[versionPage] ?? null,
                versionPage,
              );
          }}
          onExtend={() => beginVersion(version)}
        />
      )}
      {editor && (
        <BaselineVersionEditor
          key={editorKey}
          projectId={projectId}
          parent={parent}
          initialJobId={initialJobId || undefined}
          available={!!capability?.catalog_available}
          newBaselineName={newName}
          onNewBaselineName={setNewName}
          onSave={saveVersion}
        />
      )}
    </div>
  );
}
