"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  api,
  type Paper,
  type PaperContext,
  type NoteProjectContext,
  type ClassificationOptions as Options,
} from "@/lib/api";

export type ProjectLabel = NoteProjectContext["projects"][number];
export type LiteratureContext = PaperContext;
export type NoteClassification = NoteProjectContext;
export type ClassificationOptions = Options;
export type ClassificationFilterValue = { project: string; collection: string };
export const emptyClassificationFilter = { project: "", collection: "" };

export function classificationQuery(value: ClassificationFilterValue) {
  const query = new URLSearchParams();
  if (value.project === "unclassified") query.set("unclassified", "true");
  else if (value.project) query.set("project_id", value.project);
  if (value.collection) query.set("collection_id", value.collection);
  return query.toString() ? `&${query}` : "";
}

export function readClassificationFilter(): ClassificationFilterValue {
  const query = new URLSearchParams(window.location.search);
  return {
    project:
      query.get("unclassified") === "true"
        ? "unclassified"
        : (query.get("project_id") ?? ""),
    collection: query.get("collection_id") ?? "",
  };
}

export function ClassificationFilters({
  value,
  onChange,
  options,
  loading,
  error,
  onRetry,
}: {
  value: ClassificationFilterValue;
  onChange: (value: ClassificationFilterValue) => void;
  options: ClassificationOptions | null;
  loading: boolean;
  error: string;
  onRetry: () => void;
}) {
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-3">
        <label className="text-xs">
          研究课题
          <select
            aria-label="按研究课题筛选"
            className="ml-2 rounded-md border border-[var(--border)] bg-[var(--background)] p-2 text-sm"
            value={value.project}
            disabled={loading}
            onChange={(event) =>
              onChange({ ...value, project: event.target.value })
            }
          >
            <option value="">全部课题</option>
            <option value="unclassified">未分类</option>
            {value.project &&
              value.project !== "unclassified" &&
              !options?.projects?.some(
                (project) => project.id === value.project,
              ) && (
                <option value={value.project}>当前课题（名称待加载）</option>
              )}
            {options?.projects?.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs">
          Zotero 文件夹
          <select
            aria-label="按 Zotero 文件夹筛选"
            className="ml-2 max-w-full rounded-md border border-[var(--border)] bg-[var(--background)] p-2 text-sm sm:max-w-md"
            value={value.collection}
            disabled={loading}
            onChange={(event) =>
              onChange({ ...value, collection: event.target.value })
            }
          >
            <option value="">全部文件夹</option>
            {value.collection &&
              !options?.collections?.some(
                (collection) => collection.collection_id === value.collection,
              ) && (
                <option value={value.collection}>
                  当前文件夹（路径待加载）
                </option>
              )}
            {options?.collections?.map((collection) => (
              <option
                key={collection.collection_id}
                value={collection.collection_id}
              >
                {collection.library_type === "user" ? "个人库" : "群组库"}{" "}
                {collection.library_id} / {collection.path}
                {collection.status === "COMPLETE" ? "" : "（路径不完整）"}
              </option>
            ))}
          </select>
        </label>
      </div>
      {loading && (
        <p role="status" className="text-xs text-[var(--muted)]">
          正在加载分类…
        </p>
      )}
      {error && (
        <div
          role="alert"
          className="flex flex-wrap items-center gap-2 text-xs text-[var(--accent)]"
        >
          <span>{error}</span>
          <Button variant="ghost" size="sm" onClick={onRetry}>
            重新加载分类
          </Button>
        </div>
      )}
    </div>
  );
}

export function ProjectLabels({
  projects,
  mode,
}: {
  projects?: ProjectLabel[];
  mode?: NoteClassification["mode"];
}) {
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-xs">
      <span className="text-[var(--muted)]">课题：</span>
      {projects?.length ? (
        projects.map((project) => (
          <Link
            key={project.id}
            href={`/projects/${project.id}`}
            className="rounded border border-[var(--border)] px-2 py-0.5 text-[var(--accent)] hover:bg-[var(--surface-hover)]"
          >
            {project.name}
          </Link>
        ))
      ) : (
        <span className="text-[var(--muted)]">
          {projects ? "未分类" : "分类信息暂不可用"}
        </span>
      )}
      {mode === "PAPER" && (
        <span className="text-[var(--muted)]">沿用论文课题</span>
      )}
      {mode === "INHERITED_NOTE" && (
        <span className="text-[var(--muted)]">继承前版笔记分类</span>
      )}
    </div>
  );
}

export function ZoteroSourceLabels({
  context,
}: {
  context?: LiteratureContext | null;
}) {
  if (!context)
    return (
      <p className="text-xs text-[var(--muted)]">Zotero 来源信息暂不可用</p>
    );
  if (context.zotero_status === "UNLINKED")
    return <p className="text-xs text-[var(--muted)]">未关联 Zotero 条目</p>;
  if (!context.zotero_sources?.length)
    return (
      <p className="text-xs text-[var(--muted)]">Zotero 来源范围尚未确认</p>
    );
  return (
    <div
      className="space-y-1 text-xs text-[var(--muted)]"
      aria-label="Zotero 来源文件夹"
    >
      {context.zotero_sources.map((source) => (
        <div
          key={`${source.server_id}:${source.library_type}:${source.library_id}:${source.item_key}`}
          className="break-words"
        >
          <span>
            {source.library_type === "user"
              ? "Zotero 个人库"
              : source.library_type === "group"
                ? "Zotero 群组库"
                : "Zotero 库"}{" "}
            {source.library_id} · 条目 {source.item_key}：
          </span>
          {source.collection_status === "INVALID_SCOPE" ? (
            <span>来源范围不完整，文件夹无法确认</span>
          ) : source.collections?.length ? (
            source.collections.map((collection, index) => (
              <span key={collection.collection_id}>
                {index > 0 ? "；" : ""}
                {collection.path}
                {collection.status !== "COMPLETE" &&
                  "（路径不完整，需同步核对）"}
              </span>
            ))
          ) : (
            <span>尚无文件夹归属记录，请同步核对</span>
          )}
        </div>
      ))}
    </div>
  );
}

export function RefreshZoteroFolders({
  onRefreshed,
}: {
  onRefreshed: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  return (
    <div className="space-y-1">
      <Button
        variant="ghost"
        size="sm"
        disabled={busy}
        onClick={async () => {
          if (busy) return;
          setBusy(true);
          setMessage("");
          setError("");
          try {
            await api.post(
              "/reference-managers/zotero/collections/refresh",
              {},
            );
            setMessage("Zotero 文件夹层级已刷新；未导入论文或启动精读。");
            onRefreshed();
          } catch (cause) {
            setError(
              cause instanceof Error
                ? cause.message
                : "刷新文件夹失败，已有分类保留",
            );
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? "正在刷新文件夹…" : "刷新 Zotero 文件夹"}
      </Button>
      {message && (
        <p role="status" className="text-xs text-[var(--muted)]">
          {message}
        </p>
      )}
      {error && (
        <p role="alert" className="text-xs text-[var(--accent)]">
          {error}。已有分类保留。
        </p>
      )}
    </div>
  );
}

export function ClassificationEditor({
  paperId,
  noteId,
  onSaved,
  blocked = false,
}: {
  paperId: string;
  noteId?: string;
  onSaved: () => void;
  blocked?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [options, setOptions] = useState<ClassificationOptions | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [version, setVersion] = useState<number | null>(null);
  const [mode, setMode] = useState<NoteClassification["mode"] | undefined>();
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [needsReload, setNeedsReload] = useState(false);
  const generation = useRef(0);
  useEffect(
    () => () => {
      generation.current += 1;
    },
    [],
  );

  async function readCurrent() {
    const sequence = ++generation.current;
    setLoading(true);
    setVersion(null);
    setError("");
    try {
      const [available, current] = await Promise.all([
        api.get<ClassificationOptions>("/literature-classification-options"),
        noteId
          ? api.get<NoteClassification>(
              `/research-notes/${noteId}/classification`,
            )
          : api.get<Paper & { literature_context: LiteratureContext }>(
              `/papers/${paperId}`,
            ),
      ]);
      if (generation.current !== sequence) return;
      const result = "classification_version" in current ? current : null;
      setOptions(available);
      setSelected(
        (
          result?.projects ??
          (current as Paper).literature_context?.projects ??
          []
        ).map((project) => project.id),
      );
      setVersion(
        result ? result.classification_version : (current as Paper).version,
      );
      setMode(result?.mode);
      setNeedsReload(false);
    } catch (cause) {
      if (generation.current === sequence) {
        setError(cause instanceof Error ? cause.message : "无法读取当前分类");
        setNeedsReload(true);
      }
    } finally {
      if (generation.current === sequence) setLoading(false);
    }
  }

  async function save() {
    if (version === null || saving || needsReload || blocked) return;
    setSaving(true);
    setError("");
    try {
      await api.put(
        noteId
          ? `/research-notes/${noteId}/classification`
          : `/papers/${paperId}/projects`,
        { expected_version: version, project_ids: selected },
      );
      setOpen(false);
      onSaved();
    } catch (cause) {
      setError(
        `${cause instanceof Error ? cause.message : "保存结果暂无法确认"}。请重新读取当前分类，核对后再次选择并保存。`,
      );
      setNeedsReload(true);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-2">
      <Button
        size="sm"
        variant="secondary"
        disabled={blocked || saving}
        aria-expanded={open}
        onClick={() => {
          if (open) {
            generation.current += 1;
            setOpen(false);
          } else {
            setOpen(true);
            void readCurrent();
          }
        }}
      >
        {open ? "收起分类" : "管理课题分类"}
      </Button>
      {open && (
        <section
          aria-label={noteId ? "笔记课题分类" : "论文课题分类"}
          className="space-y-3 rounded-md border border-[var(--border)] bg-[var(--surface)] p-3"
        >
          <p className="text-xs text-[var(--muted)]">
            可同时关联多个课题。
            {noteId
              ? "只调整这版笔记的归类，不更改正文、审核状态或其他笔记。"
              : "设置论文所属课题；Zotero 文件夹来源保持独立。"}
          </p>
          {mode === "PAPER" && (
            <p className="text-xs text-[var(--muted)]">
              当前沿用论文课题，保存后成为本版笔记的独立分类。
            </p>
          )}
          {mode === "INHERITED_NOTE" && (
            <p className="text-xs text-[var(--muted)]">
              当前继承前版笔记分类，保存后成为本版笔记的独立分类。
            </p>
          )}
          {loading ? (
            <p role="status" className="text-xs">
              正在读取当前分类…
            </p>
          ) : (
            <fieldset
              disabled={saving || needsReload || blocked || version === null}
              className="space-y-2"
            >
              <legend className="mb-2 text-sm font-medium">选择研究课题</legend>
              {options?.projects?.length ? (
                options.projects.map((project) => (
                  <label
                    key={project.id}
                    className="flex items-center gap-2 text-sm"
                  >
                    <input
                      type="checkbox"
                      checked={selected.includes(project.id)}
                      onChange={(event) =>
                        setSelected((previous) =>
                          event.target.checked
                            ? [...previous, project.id]
                            : previous.filter((id) => id !== project.id),
                        )
                      }
                    />
                    {project.name}
                  </label>
                ))
              ) : (
                <p className="text-xs text-[var(--muted)]">
                  暂无课题，可先在科研课题页创建。
                </p>
              )}
            </fieldset>
          )}
          {error && (
            <p role="alert" className="text-xs text-[var(--accent)]">
              {error}
            </p>
          )}
          {needsReload && (
            <Button
              size="sm"
              variant="secondary"
              disabled={loading || saving}
              onClick={() => void readCurrent()}
            >
              重新读取当前分类
            </Button>
          )}
          <Button
            size="sm"
            disabled={
              loading || saving || needsReload || blocked || version === null
            }
            onClick={() => void save()}
          >
            {saving
              ? "正在保存…"
              : selected.length
                ? "保存分类"
                : "保存为未分类"}
          </Button>
        </section>
      )}
    </div>
  );
}
