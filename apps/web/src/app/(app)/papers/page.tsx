"use client";

import Link from "next/link";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import {
  ArrowRight,
  FileSearch,
  FileUp,
  Link2,
  Plus,
  Search,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input, Textarea } from "@/components/ui/input";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { VenueBadges } from "@/components/papers/venue-ratings";
import {
  ClassificationEditor,
  ClassificationFilters,
  ProjectLabels,
  ZoteroSourceLabels,
  RefreshZoteroFolders,
  classificationQuery,
  emptyClassificationFilter,
  readClassificationFilter,
  type ClassificationOptions,
  type ClassificationFilterValue,
} from "@/components/literature/classification";
import { api, type Page, type Paper } from "@/lib/api";

const statusLabel: Record<string, string> = {
  unread: "未读",
  skimming: "略读",
  reading: "阅读中",
  deep_reading: "精读中",
  reproducing: "复现中",
  completed: "已完成",
  archived: "已归档",
};

export default function PapersPage() {
  const [papers, setPapers] = useState<Paper[]>([]);
  const [projects, setProjects] = useState<
    NonNullable<ClassificationOptions["projects"]>
  >([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [submittedQuery, setSubmittedQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [title, setTitle] = useState("");
  const [year, setYear] = useState("");
  const [authors, setAuthors] = useState("");
  const [doi, setDoi] = useState("");
  const [abstract, setAbstract] = useState("");
  const [projectIds, setProjectIds] = useState<string[]>([]);
  const [classification, setClassification] =
    useState<ClassificationFilterValue>(emptyClassificationFilter);
  const [options, setOptions] = useState<ClassificationOptions | null>(null);
  const [optionsError, setOptionsError] = useState("");
  const [optionsLoading, setOptionsLoading] = useState(true);
  const [filtersReady, setFiltersReady] = useState(false);
  const [moreLoading, setMoreLoading] = useState(false);
  const sequence = useRef(0);
  const [tags, setTags] = useState("");

  const loadOptions = useCallback(() => {
    setOptionsLoading(true);
    api
      .get<ClassificationOptions>("/literature-classification-options")
      .then((result) => {
        setOptions(result);
        setProjects(result.projects ?? []);
        setOptionsError("");
      })
      .catch((cause) =>
        setOptionsError(
          cause instanceof Error ? cause.message : "无法加载分类",
        ),
      )
      .finally(() => setOptionsLoading(false));
  }, []);
  useEffect(() => {
    queueMicrotask(() => {
      setClassification(readClassificationFilter());
      setFiltersReady(true);
      loadOptions();
    });
  }, [loadOptions]);

  const load = useCallback(() => {
    if (!filtersReady) return;
    const current = ++sequence.current;
    setLoading(true);
    setPapers([]);
    setCursor(null);
    const search = submittedQuery
      ? `&q=${encodeURIComponent(submittedQuery)}`
      : "";
    api
      .get<Page<Paper>>(
        `/papers?limit=30${search}${classificationQuery(classification)}`,
      )
      .then((paperResult) => {
        if (sequence.current !== current) return;
        setPapers(paperResult.items);
        setCursor(paperResult.page.next_cursor);
        setError("");
      })
      .catch((cause) => {
        if (sequence.current === current)
          setError(cause instanceof Error ? cause.message : "无法加载文献");
      })
      .finally(() => {
        if (sequence.current === current) setLoading(false);
      });
  }, [submittedQuery, classification, filtersReady]);
  useEffect(() => {
    queueMicrotask(load);
  }, [load]);

  async function create(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.post<Paper>("/papers", {
        title,
        year: year ? Number(year) : null,
        doi: doi || null,
        abstract: abstract || null,
        authors: authors
          .split(/[;,，；]/)
          .map((part) => part.trim())
          .filter(Boolean),
        tags: tags
          .split(/[;,，；]/)
          .map((part) => part.trim())
          .filter(Boolean),
        project_ids: projectIds,
      });
      setTitle("");
      setYear("");
      setAuthors("");
      setDoi("");
      setAbstract("");
      setTags("");
      setProjectIds([]);
      setShowForm(false);
      load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "保存论文失败");
    } finally {
      setBusy(false);
    }
  }

  async function loadMore() {
    if (!cursor || moreLoading) return;
    const current = sequence.current;
    setMoreLoading(true);
    try {
      const search = submittedQuery
        ? `&q=${encodeURIComponent(submittedQuery)}`
        : "";
      const result = await api.get<Page<Paper>>(
        `/papers?limit=30&cursor=${encodeURIComponent(cursor)}${search}${classificationQuery(classification)}`,
      );
      if (sequence.current !== current) return;
      setPapers((previous) => [...previous, ...result.items]);
      setCursor(result.page.next_cursor);
    } catch (cause) {
      if (sequence.current === current)
        setError(cause instanceof Error ? cause.message : "加载失败");
    } finally {
      setMoreLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="mb-1 text-xs font-medium uppercase tracking-[0.18em] text-[var(--accent)]">
            Literature hub
          </p>
          <h1 className="text-2xl font-semibold">文献中心</h1>
          <p className="mt-1 text-sm text-[var(--muted)]">
            管理论文、阅读状态、相关度与课题关联。
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" asChild>
            <Link href="/integrations/zotero">Zotero 文献库</Link>
          </Button>
          <Button
            aria-expanded={addOpen}
            aria-controls="paper-add-methods"
            onClick={() => setAddOpen(!addOpen)}
          >
            <Plus className="h-4 w-4" />
            添加论文
          </Button>
        </div>
      </div>
      {addOpen && (
        <div id="paper-add-methods" aria-label="添加论文方式">
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" asChild>
              <Link href="/papers/import/arxiv">
                <FileSearch className="h-4 w-4" />
                通过 arXiv 导入
              </Link>
            </Button>
            <Button variant="secondary" asChild>
              <Link href="/papers/import/doi">
                <Link2 className="h-4 w-4" />
                通过 DOI 导入
              </Link>
            </Button>
            <Button variant="secondary" asChild>
              <Link href="/papers/import">
                <FileUp className="h-4 w-4" />
                导入 BibTeX / RIS
              </Link>
            </Button>
            <Button
              onClick={() => {
                setShowForm(!showForm);
                setAddOpen(false);
              }}
            >
              <Plus className="h-4 w-4" />
              手工录入论文
            </Button>
          </div>
        </div>
      )}
      <form
        onSubmit={(event) => {
          event.preventDefault();
          setSubmittedQuery(query);
        }}
        className="flex max-w-lg gap-2"
      >
        <div className="relative flex-1">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-[var(--muted)]" />
          <Input
            className="pl-9"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="按标题搜索已收录论文"
          />
        </div>
        <Button variant="secondary" type="submit">
          搜索
        </Button>
      </form>
      <ClassificationFilters
        value={classification}
        onChange={setClassification}
        options={options}
        loading={optionsLoading}
        error={optionsError}
        onRetry={loadOptions}
      />
      <RefreshZoteroFolders
        onRefreshed={() => {
          loadOptions();
          load();
        }}
      />
      {showForm && (
        <Card>
          <CardHeader>
            <h2 className="font-semibold">录入论文</h2>
          </CardHeader>
          <CardContent>
            <form onSubmit={create} className="grid gap-4 md:grid-cols-2">
              <label className="space-y-1.5 text-xs font-medium md:col-span-2">
                标题
                <Input
                  required
                  value={title}
                  onChange={(event) => setTitle(event.target.value)}
                  placeholder="论文完整标题"
                />
              </label>
              <label className="space-y-1.5 text-xs font-medium">
                作者（用逗号分隔）
                <Input
                  value={authors}
                  onChange={(event) => setAuthors(event.target.value)}
                  placeholder="Author A, Author B"
                />
              </label>
              <label className="space-y-1.5 text-xs font-medium">
                年份
                <Input
                  type="number"
                  min="1400"
                  max="2200"
                  value={year}
                  onChange={(event) => setYear(event.target.value)}
                />
              </label>
              <label className="space-y-1.5 text-xs font-medium">
                DOI
                <Input
                  value={doi}
                  onChange={(event) => setDoi(event.target.value)}
                  placeholder="10.xxxx/..."
                />
              </label>
              <fieldset
                className="space-y-1.5 text-xs font-medium"
                disabled={optionsLoading || !!optionsError}
              >
                <legend>关联课题（可多选）</legend>
                {projects.map((project) => (
                  <label key={project.id} className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={projectIds.includes(project.id)}
                      onChange={(event) =>
                        setProjectIds((previous) =>
                          event.target.checked
                            ? [...previous, project.id]
                            : previous.filter((id) => id !== project.id),
                        )
                      }
                    />
                    {project.name}
                  </label>
                ))}
                {!projects.length && (
                  <p className="text-[var(--muted)]">暂无课题，可暂不关联。</p>
                )}
              </fieldset>
              <label className="space-y-1.5 text-xs font-medium">
                标签（用逗号分隔）
                <Input
                  value={tags}
                  onChange={(event) => setTags(event.target.value)}
                  placeholder="RGBT, TransmissionLine"
                />
              </label>
              <label className="space-y-1.5 text-xs font-medium md:col-span-2">
                摘要
                <Textarea
                  value={abstract}
                  onChange={(event) => setAbstract(event.target.value)}
                  placeholder="摘要或研究简介"
                />
              </label>
              <div className="md:col-span-2">
                <Button type="submit" disabled={busy}>
                  {busy ? "保存中…" : "保存论文"}
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      )}
      {error && <ErrorState message={error} onRetry={load} />}
      {loading ? (
        <LoadingState />
      ) : error && !papers.length ? null : papers.length ? (
        <Card>
          <div className="divide-y divide-[var(--border)]">
            {papers.map((paper) => (
              <div
                key={paper.id}
                className="flex flex-wrap items-center gap-2 pr-4"
              >
                <Link
                  href={`/papers/${paper.id}/analysis`}
                  className="flex min-w-0 flex-1 items-center justify-between gap-4 px-5 py-4 hover:bg-[var(--surface-hover)]"
                >
                  <div className="min-w-0">
                    <div className="line-clamp-1 text-sm font-medium">
                      {paper.title}
                    </div>
                    <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-[var(--muted)]">
                      <span>
                        {paper.authors
                          .map((author) => author.display_name)
                          .join(", ") || "作者未录入"}
                      </span>
                      <span>{paper.year ?? "年份未知"}</span>
                      <span>{paper.venue?.name ?? "来源未录入"}</span>
                      <span>
                        {statusLabel[paper.reading.status] ??
                          paper.reading.status}
                      </span>
                      {paper.reading.importance && (
                        <span className="text-amber-500">
                          {"★".repeat(paper.reading.importance)}
                        </span>
                      )}
                    </div>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {paper.tags.map((tag) => (
                        <span
                          key={tag}
                          className="rounded bg-[var(--surface-hover)] px-1.5 py-0.5 text-[10px] text-[var(--muted)]"
                        >
                          #{tag}
                        </span>
                      ))}
                    </div>
                  </div>
                  <ArrowRight className="h-4 w-4 shrink-0 text-[var(--muted)]" />
                </Link>
                <Link
                  href={`/papers/${paper.id}`}
                  aria-label={`文献信息：${paper.title}`}
                  className="shrink-0 rounded-md px-2 py-2 text-xs text-[var(--muted)] hover:text-[var(--accent)]"
                >
                  信息
                </Link>
                <div className="w-full px-5 pb-3">
                  <div className="mb-2 space-y-2">
                    <ProjectLabels
                      projects={paper.literature_context?.projects}
                    />
                    <ZoteroSourceLabels context={paper.literature_context} />
                    <ClassificationEditor paperId={paper.id} onSaved={load} />
                  </div>
                  <VenueBadges records={paper.venue_assessments} />
                </div>
              </div>
            ))}
          </div>
        </Card>
      ) : (
        <Card>
          <EmptyState
            title={
              classification.project ||
              classification.collection ||
              submittedQuery
                ? "当前筛选没有论文"
                : "还没有论文"
            }
            detail="可调整课题或 Zotero 文件夹筛选，或从 Zotero 读取文献。"
          />
        </Card>
      )}
      {cursor && (
        <div className="text-center">
          <Button variant="secondary" disabled={moreLoading} onClick={loadMore}>
            {moreLoading ? "加载中…" : "加载更多"}
          </Button>
        </div>
      )}
    </div>
  );
}
