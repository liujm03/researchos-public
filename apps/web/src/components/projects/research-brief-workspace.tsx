"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { api, type Project, type ProjectPaper } from "@/lib/api";
import { ResearchBriefEditor } from "./research-brief-editor";
import { ResearchBriefDetail } from "./research-brief-detail";
import type { components } from "@/lib/generated";

type Detail = components["schemas"]["ResearchBriefDetailOut"];
type BriefPage = components["schemas"]["ResearchBriefPage"];
type Create = components["schemas"]["ResearchBriefCreate"];
type Review = components["schemas"]["ResearchBriefReviewCreate"];
const errorMessage = (cause: unknown, fallback: string) =>
  cause instanceof Error ? cause.message : fallback;

export function ResearchBriefWorkspace({ projectId }: { projectId: string }) {
  const [project, setProject] = useState<Project | null>(null);
  const [papers, setPapers] = useState<ProjectPaper[]>([]);
  const [page, setPage] = useState<BriefPage | null>(null);
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  const [pageIndex, setPageIndex] = useState(0);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [base, setBase] = useState<Detail | null>(null);
  const [editorKey, setEditorKey] = useState(0);
  const [loading, setLoading] = useState(true);
  const [listLoading, setListLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [listError, setListError] = useState("");
  const [paperError, setPaperError] = useState("");
  const [detailError, setDetailError] = useState("");
  const [notice, setNotice] = useState("");
  const busyRef = useRef(false);
  const loadSequence = useRef(0);
  const detailSequence = useRef(0);
  const selectedId = useRef<string | null>(null);
  const endpoint = `/projects/${encodeURIComponent(projectId)}/research-briefs`;

  const loadList = useCallback(
    async (cursor: string | null, index: number) => {
      const sequence = ++loadSequence.current;
      setListLoading(true);
      setListError("");
      try {
        const result = await api.get<BriefPage>(
          `${endpoint}?limit=10${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
        );
        if (sequence !== loadSequence.current) return;
        setPage(result);
        setPageIndex(index);
      } catch (cause) {
        if (sequence === loadSequence.current)
          setListError(errorMessage(cause, "任务书版本列表读取失败"));
      } finally {
        if (sequence === loadSequence.current) setListLoading(false);
      }
    },
    [endpoint],
  );
  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [projectResult, paperResult] = await Promise.allSettled([
        api.get<Project>(`/projects/${projectId}`),
        api.get<ProjectPaper[]>(`/projects/${projectId}/papers`),
      ]);
      if (projectResult.status === "rejected") throw projectResult.reason;
      setProject(projectResult.value);
      if (paperResult.status === "fulfilled") {
        setPapers(paperResult.value);
        setPaperError("");
      } else
        setPaperError(errorMessage(paperResult.reason, "文献列表暂不可用"));
      await loadList(null, 0);
      setCursors([null]);
    } catch (cause) {
      setError(errorMessage(cause, "研究任务书读取失败"));
    } finally {
      setLoading(false);
    }
  }, [projectId, loadList]);
  const readDetail = useCallback(
    async (id: string) => {
      const sequence = ++detailSequence.current;
      selectedId.current = id;
      setDetailLoading(true);
      setDetailError("");
      try {
        const result = await api.get<Detail>(
          `${endpoint}/${encodeURIComponent(id)}`,
        );
        if (sequence === detailSequence.current) setDetail(result);
      } catch (cause) {
        if (sequence === detailSequence.current)
          setDetailError(errorMessage(cause, "任务书版本读取失败"));
      } finally {
        if (sequence === detailSequence.current) setDetailLoading(false);
      }
    },
    [endpoint],
  );
  useEffect(() => {
    let active = true;
    void Promise.resolve().then(() => {
      if (!active) return;
      void (async () => {
        await load();
        if (!active) return;
        const requestedVersion = new URLSearchParams(
          window.location.search,
        ).get("version");
        if (requestedVersion) await readDetail(requestedVersion);
      })();
    });
    return () => {
      active = false;
      loadSequence.current += 1;
      detailSequence.current += 1;
    };
  }, [load, readDetail]);
  function beginAction() {
    if (busyRef.current) return false;
    busyRef.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    return true;
  }
  function endAction() {
    busyRef.current = false;
    setBusy(false);
  }
  async function save(body: Create) {
    if (!beginAction()) return;
    try {
      const result = await api.post<Detail>(endpoint, body);
      selectedId.current = result.id;
      setDetail(result);
      setBase(result);
      setEditorKey((value) => value + 1);
      setNotice("已保存不可变任务书版本；未启动 AI、模型或训练。");
      await loadList(null, 0);
      setCursors([null]);
    } catch (cause) {
      setError(errorMessage(cause, "任务书保存失败"));
    } finally {
      endAction();
    }
  }
  async function review(body: Review) {
    if (!detail || !beginAction()) return;
    try {
      const result = await api.post<Detail>(
        `${endpoint}/${detail.id}/review`,
        body,
      );
      setDetail(result);
      setNotice(
        body.decision === "ACCEPT"
          ? "已接受本版本任务书；执行授权仍未授予。"
          : "已拒绝本版本任务书；旧版本内容保持不变。",
      );
      await loadList(cursors[pageIndex] ?? null, pageIndex);
    } catch (cause) {
      setError(
        errorMessage(cause, "任务书审阅失败") +
          "。当前版本和草稿保留，请刷新版本上下文后核对。",
      );
    } finally {
      endAction();
    }
  }
  function newDraft() {
    setBase(null);
    setEditorKey((value) => value + 1);
    setNotice("");
  }
  async function reloadPapers() {
    try {
      setPapers(await api.get<ProjectPaper[]>(`/projects/${projectId}/papers`));
      setPaperError("");
    } catch (cause) {
      setPaperError(errorMessage(cause, "文献列表暂不可用"));
    }
  }
  function edit(value: Detail) {
    setBase(value);
    setEditorKey((key) => key + 1);
    setNotice(`已载入版本 ${value.revision}，修改将创建新版本并保留原审阅。`);
  }
  function nextPage() {
    const next = page?.page.next_cursor;
    if (!next) return;
    setCursors((old) => [...old.slice(0, pageIndex + 1), next]);
    void loadList(next, pageIndex + 1);
  }
  if (loading) return <LoadingState label="正在读取研究任务书…" />;
  if (!project)
    return (
      <ErrorState message={error || "课题不可用"} onRetry={() => void load()} />
    );
  return (
    <div className="space-y-6">
      <Link
        href={`/projects/${projectId}`}
        className="text-xs text-[var(--muted)] hover:text-[var(--accent)]"
      >
        返回课题
      </Link>
      <header className="space-y-2">
        <p className="text-xs uppercase tracking-[0.18em] text-[var(--accent)]">
          Research brief
        </p>
        <h1 className="text-2xl font-semibold">{project.name} · 研究任务书</h1>
        <p className="text-sm leading-6 text-[var(--muted)]">
          从 Idea
          到研究问题、路线与协议，保留每次决策及其冻结来源。任务书审阅与模型、代码和实验执行授权分别记录。
        </p>
      </header>
      <Link
        href={`/projects/${projectId}/planning`}
        className="inline-block text-sm text-[var(--accent)] underline"
      >
        进入 AI 研究规划与阶段授权
      </Link>
      {error && (
        <div role="alert" aria-label="研究任务书操作失败">
          <ErrorState message={error} />
        </div>
      )}
      {notice && (
        <p
          role="status"
          className="rounded border border-[var(--accent)] p-3 text-sm"
        >
          {notice}
        </p>
      )}
      <div className="flex justify-end">
        <Button
          size="sm"
          variant="secondary"
          disabled={busy}
          onClick={newDraft}
        >
          新建独立草稿
        </Button>
      </div>
      <ResearchBriefEditor
        key={editorKey}
        projectId={projectId}
        base={base}
        papers={papers}
        papersUnavailable={!!paperError}
        busy={busy}
        onSave={save}
        onNew={newDraft}
      />
      {paperError && (
        <ErrorState
          message={`${paperError}。无文献的 Idea 草稿仍可保存。`}
          onRetry={() => void reloadPapers()}
        />
      )}
      <Card>
        <CardHeader>
          <h2 className="font-semibold">任务书历史版本</h2>
          <Button
            size="sm"
            variant="secondary"
            disabled={busy || listLoading}
            onClick={() => void loadList(cursors[pageIndex] ?? null, pageIndex)}
          >
            刷新版本列表
          </Button>
        </CardHeader>
        <CardContent className="space-y-3">
          {listError && (
            <ErrorState
              message={listError}
              onRetry={() =>
                void loadList(cursors[pageIndex] ?? null, pageIndex)
              }
            />
          )}
          {listLoading && <LoadingState label="正在读取版本列表…" />}
          {!listLoading &&
            page &&
            (page.items.length ? (
              <ul className="space-y-2">
                {page.items.map((item) => (
                  <li
                    key={item.id}
                    className="flex flex-wrap items-center justify-between gap-2 rounded border border-[var(--border)] p-3 text-xs"
                  >
                    <p>
                      版本 {item.revision} · {item.status}
                    </p>
                    <Button
                      size="sm"
                      variant="secondary"
                      disabled={busy || detailLoading}
                      onClick={() => void readDetail(item.id)}
                    >
                      查看版本 {item.revision}
                    </Button>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState
                title="尚无研究任务书"
                detail="先记录一个 Idea 创建第一个草稿。"
              />
            ))}
          <div className="flex items-center justify-between gap-3 text-xs">
            <Button
              size="sm"
              variant="secondary"
              disabled={busy || listLoading || pageIndex === 0}
              onClick={() =>
                void loadList(cursors[pageIndex - 1] ?? null, pageIndex - 1)
              }
            >
              上一页版本
            </Button>
            <span>
              第 {pageIndex + 1} 页
              {page?.page.total !== null && page?.page.total !== undefined
                ? ` · 共 ${page.page.total} 个版本`
                : ""}
            </span>
            <Button
              size="sm"
              variant="secondary"
              disabled={busy || listLoading || !page?.page.next_cursor}
              onClick={nextPage}
            >
              下一页版本
            </Button>
          </div>
        </CardContent>
      </Card>
      {detailLoading && <LoadingState label="正在读取冻结版本…" />}
      {detailError && (
        <ErrorState
          message={detailError}
          onRetry={() => {
            if (selectedId.current) void readDetail(selectedId.current);
          }}
        />
      )}
      {detail && (
        <ResearchBriefDetail
          key={`${detail.id}:${detail.review?.reviewed_at ?? "draft"}`}
          detail={detail}
          busy={busy || detailLoading || !!detailError}
          onEdit={edit}
          onReview={review}
          onRefresh={() => void readDetail(detail.id)}
        />
      )}
    </div>
  );
}
