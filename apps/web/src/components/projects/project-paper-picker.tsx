"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ZoteroSourceLabels } from "@/components/literature/classification";
import {
  api,
  type ClassificationOptions,
  type Page,
  type Paper,
  type ProjectPaper,
} from "@/lib/api";

type Scope = { collection: string; query: string; descendants: boolean };
const initialScope: Scope = { collection: "", query: "", descendants: true };
const messageOf = (cause: unknown, fallback: string) =>
  cause instanceof Error ? cause.message : fallback;

export function ProjectPaperPicker({
  projectId,
  relatedPapers,
  onLinked,
}: {
  projectId: string;
  relatedPapers: ProjectPaper[];
  onLinked: (papers: ProjectPaper[]) => void;
}) {
  const [options, setOptions] = useState<ClassificationOptions | null>(null);
  const [optionsError, setOptionsError] = useState("");
  const [optionsLoading, setOptionsLoading] = useState(true);
  const [optionsAttempt, setOptionsAttempt] = useState(0);
  const [scope, setScope] = useState<Scope>(initialScope);
  const [draftQuery, setDraftQuery] = useState("");
  const [page, setPage] = useState<Page<Paper> | null>(null);
  const [shownPageNumber, setShownPageNumber] = useState(1);
  const [cursor, setCursor] = useState<string | null>(null);
  const [previous, setPrevious] = useState<(string | null)[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const [selected, setSelected] = useState<Map<string, Paper>>(new Map());
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState("");
  const [pendingCheck, setPendingCheck] = useState<{
    ids: string[];
    acknowledged: string[];
  } | null>(null);
  const sequence = useRef(0);
  const targetPageNumber = useRef(1);
  const busy = useRef(false);
  const linked = new Set(relatedPapers.map((paper) => paper.id));

  useEffect(() => {
    let active = true;
    api
      .get<ClassificationOptions>("/literature-classification-options")
      .then((result) => {
        if (active) {
          setOptions(result);
          setOptionsError("");
        }
      })
      .catch((cause) => {
        if (active) setOptionsError(messageOf(cause, "板块加载失败"));
      })
      .finally(() => {
        if (active) setOptionsLoading(false);
      });
    return () => {
      active = false;
    };
  }, [optionsAttempt]);

  useEffect(() => {
    const ticket = ++sequence.current;
    let active = true;
    const requestedPageNumber = targetPageNumber.current;
    const query = new URLSearchParams({ limit: "30" });
    if (scope.collection) {
      query.set("collection_id", scope.collection);
      query.set("include_subcollections", String(scope.descendants));
    }
    if (scope.query) query.set("q", scope.query);
    if (cursor) query.set("cursor", cursor);
    api
      .get<Page<Paper>>(`/papers?${query}`)
      .then((result) => {
        if (active && sequence.current === ticket) {
          setPage(result);
          setShownPageNumber(requestedPageNumber);
        }
      })
      .catch((cause) => {
        if (active && sequence.current === ticket)
          setError(messageOf(cause, "文献加载失败"));
      })
      .finally(() => {
        if (active && sequence.current === ticket) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [scope, cursor, retry]);

  function changeScope(next: Scope) {
    sequence.current++;
    setLoading(true);
    setError("");
    setScope(next);
    setCursor(null);
    setPrevious([]);
    targetPageNumber.current = 1;
    setPage(null);
    setSelected(new Map());
    setNotice("");
  }

  function search(event: FormEvent) {
    event.preventDefault();
    changeScope({ ...scope, query: draftQuery.trim() });
  }

  async function reconcile(ids: string[], acknowledged: string[]) {
    try {
      const current = await api.get<ProjectPaper[]>(
        `/projects/${projectId}/papers`,
      );
      const confirmed = new Set(current.map((paper) => paper.id));
      onLinked(current);
      setSelected(
        (old) => new Map([...old].filter(([id]) => !confirmed.has(id))),
      );
      const count = ids.filter((id) => confirmed.has(id)).length;
      setNotice(
        `本次选择 ${ids.length} 篇：已确认关联 ${count} 篇，未关联 ${ids.length - count} 篇。未关联文献保留勾选；如需继续，请再次主动提交。`,
      );
      setPendingCheck(null);
    } catch (cause) {
      setPendingCheck({ ids, acknowledged });
      const confirmed = new Set(acknowledged);
      setSelected(
        (old) => new Map([...old].filter(([id]) => !confirmed.has(id))),
      );
      setNotice(
        `本次 ${ids.length} 篇：已收到成功回执 ${acknowledged.length} 篇，其余 ${ids.length - acknowledged.length} 篇未确认。当前关联结果尚未核查，${messageOf(cause, "读取关联结果失败")}。请先只读核查，系统不会自动重发关联请求。`,
      );
    }
  }

  async function submit() {
    if (busy.current || pendingCheck || !selected.size) return;
    busy.current = true;
    setSaving(true);
    setNotice("");
    const ids = [...selected.keys()].filter((id) => !linked.has(id));
    const acknowledged: string[] = [];
    let failure = "";
    try {
      for (const id of ids) {
        try {
          await api.post(`/projects/${projectId}/papers/${id}`, {
            role: "related",
          });
          acknowledged.push(id);
        } catch (cause) {
          failure = messageOf(cause, "关联请求未完成");
          break;
        }
      }
      await reconcile(ids, acknowledged);
      if (failure) setNotice((value) => `关联已暂停：${failure}。${value}`);
    } finally {
      busy.current = false;
      setSaving(false);
    }
  }

  async function checkOnly() {
    if (busy.current || !pendingCheck) return;
    busy.current = true;
    setSaving(true);
    try {
      await reconcile(pendingCheck.ids, pendingCheck.acknowledged);
    } finally {
      busy.current = false;
      setSaving(false);
    }
  }

  const selectable = page?.items.filter((paper) => !linked.has(paper.id)) ?? [];
  const allChecked =
    selectable.length > 0 &&
    selectable.every((paper) => selected.has(paper.id));
  const controlsDisabled = saving || pendingCheck !== null;
  return (
    <section aria-label="按文献板块关联课题" className="mb-5 space-y-3">
      <p className="text-sm text-[var(--muted)]">
        选择 Zotero 文献板块，再勾选要关联的论文。每页 30
        篇，可翻页查看全部已收录文献；切换板块或搜索会清除待选。
      </p>
      <div className="flex flex-wrap items-center gap-3">
        <label className="min-w-0 flex-1 text-sm">
          文献板块
          <select
            aria-label="关联文献板块"
            className="mt-1 block w-full rounded-md border border-[var(--border)] bg-[var(--background)] p-2"
            value={scope.collection}
            disabled={controlsDisabled || optionsLoading}
            onChange={(event) =>
              changeScope({ ...scope, collection: event.target.value })
            }
          >
            <option value="">全部已收录文献</option>
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
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={scope.descendants}
            disabled={controlsDisabled || !scope.collection}
            onChange={(event) =>
              changeScope({ ...scope, descendants: event.target.checked })
            }
          />
          包含子文件夹
        </label>
      </div>
      {optionsLoading && (
        <p role="status" className="text-sm">
          正在加载文献板块…
        </p>
      )}
      {optionsError && (
        <div role="alert" className="text-sm">
          {optionsError}{" "}
          <Button
            size="sm"
            variant="ghost"
            disabled={controlsDisabled}
            onClick={() => {
              setOptionsLoading(true);
              setOptionsAttempt((value) => value + 1);
            }}
          >
            重新加载板块
          </Button>
        </div>
      )}
      <form onSubmit={search} className="flex gap-2">
        <Input
          aria-label="搜索板块文献"
          placeholder="按标题搜索当前板块"
          value={draftQuery}
          disabled={controlsDisabled}
          onChange={(event) => setDraftQuery(event.target.value)}
        />
        <Button type="submit" variant="secondary" disabled={controlsDisabled}>
          搜索文献
        </Button>
      </form>
      {loading && (
        <p role="status" className="text-sm">
          正在加载文献…
        </p>
      )}
      {error && (
        <div role="alert" className="text-sm">
          {error} {page && "保留上次页面，尚未加载目标页面。"}
          <Button
            size="sm"
            variant="ghost"
            disabled={controlsDisabled}
            onClick={() => {
              setLoading(true);
              setError("");
              setRetry((value) => value + 1);
            }}
          >
            重试加载文献
          </Button>
        </div>
      )}
      {page && (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                aria-label="全选本页可关联文献"
                checked={allChecked}
                disabled={
                  controlsDisabled || loading || !!error || !selectable.length
                }
                onChange={() =>
                  setSelected((old) => {
                    const next = new Map(old);
                    for (const paper of selectable) {
                      if (allChecked) next.delete(paper.id);
                      else next.set(paper.id, paper);
                    }
                    return next;
                  })
                }
              />
              全选本页可关联文献
            </label>
            <span>
              第 {shownPageNumber} 页 · 本页 {page.items.length} 篇 · 已选{" "}
              {selected.size} 篇（含其他页）
            </span>
          </div>
          <ul className="max-h-[28rem] divide-y divide-[var(--border)] overflow-y-auto rounded-md border border-[var(--border)]">
            {page.items.map((paper) => (
              <li key={paper.id} className="flex items-start gap-3 p-3">
                <input
                  type="checkbox"
                  className="mt-1"
                  aria-label={`选择文献：${paper.title}`}
                  checked={linked.has(paper.id) || selected.has(paper.id)}
                  disabled={
                    controlsDisabled ||
                    loading ||
                    !!error ||
                    linked.has(paper.id)
                  }
                  onChange={(event) =>
                    setSelected((old) => {
                      const next = new Map(old);
                      if (event.target.checked) next.set(paper.id, paper);
                      else next.delete(paper.id);
                      return next;
                    })
                  }
                />
                <div className="min-w-0 flex-1 space-y-1">
                  <Link
                    href={`/papers/${paper.id}`}
                    className="break-words text-sm hover:text-[var(--accent)]"
                  >
                    {paper.title}
                  </Link>
                  <p className="text-xs text-[var(--muted)]">
                    {paper.year ?? "年份未知"} ·{" "}
                    {typeof paper.venue === "string"
                      ? paper.venue
                      : (paper.venue?.name ?? "来源未录入")}
                    {linked.has(paper.id) && " · 已关联本课题"}
                  </p>
                  <ZoteroSourceLabels context={paper.literature_context} />
                </div>
              </li>
            ))}
          </ul>
          {!page.items.length && (
            <p className="text-sm text-[var(--muted)]">
              当前板块没有符合搜索的已收录文献。
            </p>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="secondary"
              size="sm"
              disabled={
                controlsDisabled || loading || !!error || !previous.length
              }
              onClick={() => {
                setLoading(true);
                setError("");
                targetPageNumber.current = previous.length;
                setCursor(previous.at(-1) ?? null);
                setPrevious((value) => value.slice(0, -1));
              }}
            >
              上一页文献
            </Button>
            <Button
              variant="secondary"
              size="sm"
              disabled={
                controlsDisabled || loading || !!error || !page.page.next_cursor
              }
              onClick={() => {
                setLoading(true);
                setError("");
                targetPageNumber.current = previous.length + 2;
                setPrevious((value) => [...value, cursor]);
                setCursor(page.page.next_cursor);
              }}
            >
              下一页文献
            </Button>
            {!page.page.next_cursor && !loading && !error && (
              <span className="text-xs text-[var(--muted)]">
                已到当前筛选结果末页
              </span>
            )}
          </div>
        </>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <Button
          disabled={controlsDisabled || loading || !!error || !selected.size}
          onClick={submit}
        >
          {saving ? "正在处理…" : `关联已选 ${selected.size} 篇`}
        </Button>
        <Button
          variant="ghost"
          disabled={controlsDisabled || !selected.size}
          onClick={() => setSelected(new Map())}
        >
          清除待选
        </Button>
        {pendingCheck && (
          <Button variant="secondary" disabled={saving} onClick={checkOnly}>
            核查关联结果（不重发）
          </Button>
        )}
      </div>
      {notice && (
        <p role="status" className="text-sm">
          {notice}
        </p>
      )}
    </section>
  );
}
