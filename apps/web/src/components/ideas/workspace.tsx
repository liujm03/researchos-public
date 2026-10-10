"use client";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Lightbulb, Plus } from "lucide-react";
import { api, type Page, type Project } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { useIdeaCapture } from "./use-capture";
import { IdeaEditor } from "./editor";
import { IdeaDetail } from "./detail";
import {
  errorText,
  statuses,
  statusLabel,
  type Idea,
  type IdeaPage,
  type Revision,
  type Fields,
  type Source,
  type Create,
  type Revise,
} from "./types";

export function IdeasWorkspace({
  projectId,
  initialIdeaId,
}: {
  projectId: string;
  initialIdeaId?: string;
}) {
  const capture = useIdeaCapture(projectId);
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectCursor, setProjectCursor] = useState<string | null>(null);
  const [page, setPage] = useState<IdeaPage | null>(null);
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(true);
  const [listBusy, setListBusy] = useState(false);
  const [detailBusy, setDetailBusy] = useState(false);
  const [busy, setBusy] = useState(false);
  const [projectBusy, setProjectBusy] = useState(false);
  const [error, setError] = useState("");
  const [projectError, setProjectError] = useState("");
  const [detailError, setDetailError] = useState("");
  const [saveError, setSaveError] = useState("");
  const [notice, setNotice] = useState("");
  const [detail, setDetail] = useState<Idea | null>(null);
  const [editing, setEditing] = useState(false);
  const [editorBase, setEditorBase] = useState<Revision | null>(null);
  const [editorKey, setEditorKey] = useState(0);
  const listSeq = useRef(0),
    detailSeq = useRef(0),
    saving = useRef(false);
  const selectedId = useRef<string | null>(null);
  const loadList = useCallback(
    async (cursor?: string | null) => {
      const sequence = ++listSeq.current;
      setListBusy(true);
      setError("");
      const query = new URLSearchParams({ limit: "20" });
      if (projectId) query.set("project_id", projectId);
      if (status) query.set("status", status);
      if (cursor) query.set("cursor", cursor);
      try {
        const result = await api.get<IdeaPage>(`/ideas?${query}`);
        if (sequence === listSeq.current) setPage(result);
      } catch (cause) {
        if (sequence === listSeq.current) setError(errorText(cause));
      } finally {
        if (sequence === listSeq.current) {
          setListBusy(false);
          setLoading(false);
        }
      }
    },
    [projectId, status],
  );
  const loadProjects = useCallback(async (cursor?: string | null) => {
    setProjectBusy(true);
    setProjectError("");
    try {
      const result = await api.get<Page<Project>>(
        `/projects?limit=50${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
      );
      setProjects((previous) =>
        cursor
          ? [
              ...previous,
              ...result.items.filter(
                (item) => !previous.some((project) => project.id === item.id),
              ),
            ]
          : result.items,
      );
      setProjectCursor(result.page.next_cursor);
    } catch (cause) {
      setProjectError(errorText(cause));
    } finally {
      setProjectBusy(false);
    }
  }, []);
  const readDetail = useCallback(async (id: string) => {
    const sequence = ++detailSeq.current;
    selectedId.current = id;
    setDetailBusy(true);
    setDetailError("");
    try {
      const result = await api.get<Idea>(`/ideas/${encodeURIComponent(id)}`);
      if (sequence === detailSeq.current) setDetail(result);
    } catch (cause) {
      if (sequence === detailSeq.current) setDetailError(errorText(cause));
    } finally {
      if (sequence === detailSeq.current) setDetailBusy(false);
    }
  }, []);
  useEffect(() => {
    void Promise.resolve().then(() => loadList());
  }, [loadList]);
  useEffect(() => {
    void Promise.resolve().then(() => loadProjects());
  }, [loadProjects]);
  useEffect(() => {
    if (initialIdeaId)
      void Promise.resolve().then(() => readDetail(initialIdeaId));
  }, [initialIdeaId, readDetail]);
  useEffect(() => {
    if (capture.restored)
      void Promise.resolve().then(() => {
        setEditorBase(null);
        setEditing(true);
        setEditorKey((value) => value + 1);
        setSaveError("已恢复上次未确认的捕获输入，请先只读核查是否已保存。");
      });
  }, [capture.restored]);
  async function lookupCapture() {
    if (busy) return;
    setBusy(true);
    setSaveError("");
    try {
      const result = await capture.lookup();
      if (result) {
        selectedId.current = result.id;
        setDetail(result);
        setEditing(false);
        setEditorBase(null);
        setNotice("已核查捕获结果：灵感已保存，未重复创建。");
        await loadList();
      } else
        setNotice(
          "核查时尚未发现已保存灵感；可继续原捕获，或明确放弃后更改内容。",
        );
    } catch (cause) {
      setSaveError(`核查失败：${errorText(cause)}；未重发创建请求。`);
    } finally {
      setBusy(false);
    }
  }
  async function refresh() {
    if (selectedId.current) await readDetail(selectedId.current);
    await loadList();
  }
  function newIdea() {
    setEditorBase(null);
    setEditorKey((value) => value + 1);
    setEditing(true);
    setSaveError("");
    setNotice("");
  }
  function editIdea() {
    if (!detail) return;
    setEditorBase(detail.current);
    setEditorKey((value) => value + 1);
    setEditing(true);
    setSaveError("");
  }
  async function save(fields: Fields, target: string, sources: Source[]) {
    if (saving.current) return;
    saving.current = true;
    setBusy(true);
    setSaveError("");
    setNotice("");
    try {
      let result: Idea;
      if (editorBase) {
        const inherited = editorBase.sources.map((source) => ({
          canonical_note_id: source.canonical_note_id,
          expected_note_sha256: source.note_sha256,
          start_offset: source.start_offset,
          end_offset: source.end_offset,
          exact_quote: source.exact_quote,
        }));
        const body: Revise = {
          ...fields,
          expected_revision_sha256: editorBase.sha256,
          sources:
            JSON.stringify(inherited) === JSON.stringify(sources)
              ? null
              : sources,
        };
        result = await api.patch<Idea>(`/ideas/${editorBase.idea_id}`, body);
      } else {
        const body = capture.freeze({
          ...fields,
          project_id: target || null,
          sources,
        });
        result = await api.post<Idea>("/ideas", body);
      }
      if (!editorBase) capture.clear();
      ++detailSeq.current;
      selectedId.current = result.id;
      setDetail(result);
      setEditing(false);
      setEditorBase(null);
      setNotice(`已保存灵感版本 ${result.current.revision}`);
      await loadList();
    } catch (cause) {
      setSaveError(
        `${errorText(cause)}。输入仍保留；版本冲突请读取最新版本核对。捕获结果未知时，请先核查本次捕获；相同输入沿用原操作键，不自动重发。`,
      );
    } finally {
      saving.current = false;
      setBusy(false);
    }
  }
  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-[.18em] text-[var(--accent)]">
            Research ideas
          </p>
          <h1 className="mt-1 text-2xl font-semibold">科研灵感</h1>
          <p className="mt-2 text-sm text-[var(--muted)]">
            文献摘录与想法 → 本人判断 → 待办与研究任务书 → 服务器交接。
          </p>
        </div>
        <Button
          disabled={busy || editing || !capture.ready || !!capture.pending}
          onClick={newIdea}
        >
          <Plus className="h-4 w-4" />
          记录灵感
        </Button>
      </header>
      {projectId && (
        <p className="text-sm">
          当前课题：
          <Link
            className="text-[var(--accent)]"
            href={`/projects/${projectId}`}
          >
            {projects.find((project) => project.id === projectId)?.name ??
              projectId}
          </Link>{" "}
          ·{" "}
          <Link className="text-[var(--accent)]" href="/ideas">
            查看全部灵感
          </Link>
        </p>
      )}
      {projectError && (
        <ErrorState
          message={`课题选择列表：${projectError}`}
          onRetry={() => void loadProjects()}
        />
      )}
      {projectCursor && (
        <Button
          variant="ghost"
          size="sm"
          disabled={projectBusy}
          onClick={() => void loadProjects(projectCursor)}
        >
          读取更多可选课题
        </Button>
      )}
      {capture.storageWarning && (
        <p role="alert" className="text-sm text-[var(--danger)]">
          {capture.storageWarning}
        </p>
      )}
      {capture.pending && (
        <section
          aria-label="待核查灵感捕获"
          className="space-y-2 rounded border p-3 text-sm"
        >
          <p>上次捕获仍需核查 · 保存输入和原操作键已冻结。</p>
          <Button
            variant="secondary"
            size="sm"
            disabled={busy}
            onClick={() => void lookupCapture()}
          >
            核查本次灵感捕获
          </Button>
          {capture.canAbandon && (
            <Button
              variant="ghost"
              size="sm"
              disabled={busy}
              onClick={() => {
                capture.clear();
                setNotice("本人已放弃原捕获；当前输入保留，可明确保存新内容。");
              }}
            >
              放弃尚未保存的原捕获
            </Button>
          )}
        </section>
      )}
      {notice && (
        <p role="status" className="text-sm text-[var(--accent)]">
          {notice}
        </p>
      )}
      {editing && (
        <>
          <IdeaEditor
            key={editorKey}
            base={editorBase}
            initial={!editorBase ? capture.restored?.body : null}
            projects={projects}
            projectId={detail?.project_id ?? projectId}
            busy={busy}
            onSave={save}
            onCancel={() => {
              setEditing(false);
              setSaveError("");
            }}
          />
          {saveError && <ErrorState message={saveError} />}
        </>
      )}
      <div className="grid gap-5 xl:grid-cols-[minmax(280px,0.8fr)_minmax(0,1.6fr)]">
        <Card>
          <CardHeader>
            <h2 className="flex items-center gap-2 font-semibold">
              <Lightbulb className="h-4 w-4" />
              灵感列表
            </h2>
            <Button
              size="sm"
              variant="ghost"
              disabled={listBusy}
              onClick={() => void loadList()}
            >
              刷新列表
            </Button>
          </CardHeader>
          <CardContent className="space-y-3">
            <label className="block space-y-1 text-sm">
              状态筛选
              <select
                aria-label="灵感列表状态筛选"
                className="h-9 w-full rounded border bg-[var(--background)] px-2"
                value={status}
                onChange={(event) => {
                  setPage(null);
                  setStatus(event.target.value);
                }}
              >
                <option value="">全部状态</option>
                {statuses.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            {error && (
              <ErrorState message={error} onRetry={() => void loadList()} />
            )}
            {loading || listBusy ? (
              <LoadingState label="正在读取灵感…" />
            ) : !page?.items.length ? (
              <EmptyState
                title="还没有符合条件的灵感"
                detail="记录一个问题、方法组合或待核查的文献想法。"
              />
            ) : (
              <div className="space-y-2">
                {page.items.map((item) => (
                  <button
                    key={item.id}
                    className={`block w-full rounded border p-3 text-left ${detail?.id === item.id ? "border-[var(--accent)]" : "border-[var(--border)]"}`}
                    disabled={editing || busy}
                    onClick={() => {
                      setDetail(null);
                      void readDetail(item.id);
                    }}
                  >
                    <p className="text-sm font-medium">{item.title}</p>
                    <p className="mt-1 text-xs text-[var(--muted)]">
                      {statusLabel(item.status)} · 版本 {item.revision}
                      {item.project_id &&
                        ` · ${projects.find((project) => project.id === item.project_id)?.name ?? "课题灵感"}`}
                    </p>
                  </button>
                ))}
              </div>
            )}
            {page?.page.next_cursor && (
              <Button
                variant="secondary"
                size="sm"
                disabled={listBusy}
                onClick={() => void loadList(page.page.next_cursor)}
              >
                下一页灵感
              </Button>
            )}
          </CardContent>
        </Card>
        <div className="min-w-0 space-y-3">
          {detailError && (
            <ErrorState
              message={detailError}
              onRetry={() => {
                if (selectedId.current) void readDetail(selectedId.current);
              }}
            />
          )}
          {detailBusy && !detail ? (
            <LoadingState label="正在读取灵感版本…" />
          ) : detail ? (
            <IdeaDetail
              key={`${detail.id}:${detail.current.sha256}`}
              idea={detail}
              projects={projects}
              onEdit={editIdea}
              onRefresh={refresh}
            />
          ) : !detailError ? (
            <EmptyState
              title="选择灵感查看内容与来源"
              detail="或在上方记录新的科研灵感。"
            />
          ) : null}
        </div>
      </div>
    </div>
  );
}
