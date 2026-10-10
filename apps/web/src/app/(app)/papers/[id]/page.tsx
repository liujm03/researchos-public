"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { ArrowLeft, ExternalLink, Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { MarkdownViewer } from "@/components/markdown/markdown-viewer";
import { MarkdownContent } from "@/components/markdown/markdown-content";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input, Textarea } from "@/components/ui/input";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import {
  VenueBadges,
  VenueRatingsEditor,
} from "@/components/papers/venue-ratings";
import { api, type Note, type Paper } from "@/lib/api";
import {
  ClassificationEditor,
  ProjectLabels,
  ZoteroSourceLabels,
} from "@/components/literature/classification";

const statuses = [
  ["unread", "未读"],
  ["skimming", "略读"],
  ["reading", "阅读中"],
  ["deep_reading", "精读中"],
  ["reproducing", "复现中"],
  ["completed", "已完成"],
  ["archived", "已归档"],
] as const;

export default function PaperDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [paper, setPaper] = useState<Paper | null>(null);
  const [notes, setNotes] = useState<Note[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [noteTitle, setNoteTitle] = useState("");
  const [noteBody, setNoteBody] = useState("");

  const load = useCallback(() => {
    Promise.all([
      api.get<Paper>(`/papers/${id}`),
      api.get<Note[]>(`/papers/${id}/notes`),
    ])
      .then(([paperResult, noteResult]) => {
        setPaper(paperResult);
        setNotes(noteResult);
        setError("");
      })
      .catch((cause) =>
        setError(cause instanceof Error ? cause.message : "无法加载论文"),
      )
      .finally(() => setLoading(false));
  }, [id]);
  useEffect(load, [load]);

  async function saveReading(patch: Partial<Paper["reading"]>) {
    if (!paper) return;
    setSaving(true);
    setError("");
    try {
      const reading = await api.put<Paper["reading"]>(`/papers/${id}/reading`, {
        status: patch.status ?? paper.reading.status,
        importance:
          patch.importance === undefined
            ? paper.reading.importance
            : patch.importance,
        relevance:
          patch.relevance === undefined
            ? paper.reading.relevance
            : patch.relevance,
      });
      setPaper({ ...paper, reading });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "阅读状态保存失败");
    } finally {
      setSaving(false);
    }
  }

  async function addNote(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      const note = await api.post<Note>(`/papers/${id}/notes`, {
        title: noteTitle || null,
        body_markdown: noteBody,
      });
      setNotes((previous) => [note, ...previous]);
      setNoteTitle("");
      setNoteBody("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "笔记保存失败");
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <LoadingState />;
  if (error && !paper) return <ErrorState message={error} onRetry={load} />;
  if (!paper) return null;

  return (
    <div className="space-y-6">
      <Link
        href="/papers"
        className="inline-flex items-center gap-2 text-xs text-[var(--muted)] hover:text-[var(--accent)]"
      >
        <ArrowLeft className="h-4 w-4" />
        返回文献中心
      </Link>
      <div>
        <p className="mb-2 text-xs uppercase tracking-[0.18em] text-[var(--accent)]">
          Paper workspace
        </p>
        <h1 className="max-w-4xl text-2xl font-semibold leading-snug">
          {paper.title}
        </h1>
        <p className="mt-2 text-sm text-[var(--muted)]">
          {paper.authors.map((author) => author.display_name).join(", ") ||
            "作者未录入"}{" "}
          · {paper.venue?.name ?? "来源未录入"} · {paper.year ?? "年份未知"}
        </p>
        <div className="mt-3 flex flex-wrap gap-2 text-xs">
          {paper.tags.map((tag) => (
            <span
              key={tag}
              className="rounded-full border border-[var(--border)] px-2 py-1 text-[var(--muted)]"
            >
              #{tag}
            </span>
          ))}
          {paper.doi && (
            <a
              className="inline-flex items-center gap-1 text-[var(--accent)] hover:underline"
              href={`https://doi.org/${encodeURIComponent(paper.doi)}`}
              target="_blank"
              rel="noopener noreferrer"
            >
              DOI <ExternalLink className="h-3 w-3" />
            </a>
          )}
          {paper.pdf_url && (
            <a
              className="inline-flex items-center gap-1 text-[var(--accent)] hover:underline"
              href={paper.pdf_url}
              target="_blank"
              rel="noopener noreferrer"
            >
              PDF 来源 <ExternalLink className="h-3 w-3" />
            </a>
          )}
          {paper.sources
            .filter((source) => source.provider_key === "zotero_local")
            .map((source) => {
              const key = source.provider_id.split(":").at(-1);
              return key ? (
                <Link
                  key={source.provider_id}
                  className="inline-flex items-center gap-1 rounded-full border border-[var(--border)] px-2 py-0.5 text-[var(--accent)] hover:bg-[var(--surface-hover)]"
                  href={`/integrations/zotero?item=${encodeURIComponent(key)}`}
                >
                  在 Zotero 中查阅 <ExternalLink className="h-3 w-3" />
                </Link>
              ) : null;
            })}
        </div>
        <VenueBadges records={paper.venue_assessments} />
        <div className="mt-3 space-y-2">
          <ProjectLabels projects={paper.literature_context?.projects} />
          <ZoteroSourceLabels context={paper.literature_context} />
          <ClassificationEditor key={id} paperId={id} onSaved={load} />
        </div>
      </div>
      <VenueRatingsEditor
        key={id}
        paperId={id}
        records={paper.venue_assessments}
        onChange={(venue_assessments) =>
          setPaper((current) =>
            current?.id === id ? { ...current, venue_assessments } : current,
          )
        }
      />
      {error && <ErrorState message={error} onRetry={load} />}
      <div className="flex flex-wrap gap-2">
        <Link
          href={`/papers/${id}/analysis`}
          className="inline-flex h-9 items-center rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 text-sm text-[var(--accent)] hover:bg-[var(--surface-hover)]"
        >
          原始 PDF 技能精读 →
        </Link>
        <Link
          href={`/papers/${id}/reproduction`}
          className="inline-flex h-9 items-center rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 text-sm text-[var(--accent)] hover:bg-[var(--surface-hover)]"
        >
          论文复现准备 →
        </Link>
      </div>
      <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <h2 className="font-semibold">摘要</h2>
            </CardHeader>
            <CardContent>
              <p className="whitespace-pre-wrap text-sm leading-7 text-[var(--muted)]">
                {paper.abstract || "尚未录入摘要。"}
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <h2 className="font-semibold">阅读笔记</h2>
              <span className="text-xs text-[var(--muted)]">
                {notes.length} 条
              </span>
            </CardHeader>
            <CardContent>
              <form onSubmit={addNote} className="space-y-3">
                <Input
                  value={noteTitle}
                  onChange={(event) => setNoteTitle(event.target.value)}
                  placeholder="笔记标题（可选）"
                />
                <Textarea
                  required
                  aria-label="手写笔记 Markdown"
                  value={noteBody}
                  onChange={(event) => setNoteBody(event.target.value)}
                  placeholder="记录问题来源、研究 Gap、方法和你的想法…"
                />
                <details className="rounded border border-[var(--border)] p-3">
                  <summary className="cursor-pointer text-xs">
                    预览手写笔记
                  </summary>
                  <div className="mt-3" aria-label="手写笔记只读预览">
                    {noteBody ? (
                      <MarkdownContent content={noteBody} />
                    ) : (
                      <p className="text-xs text-[var(--muted)]">
                        输入正文后显示预览。
                      </p>
                    )}
                  </div>
                </details>
                <Button type="submit" disabled={saving}>
                  <Plus className="h-4 w-4" />
                  保存笔记
                </Button>
              </form>
              <div className="mt-5 divide-y divide-[var(--border)]">
                {notes.length ? (
                  notes.map((note, index) => (
                    <div key={note.id} className="py-4">
                      <div className="text-sm font-medium">
                        {note.title || "阅读笔记"}
                      </div>
                      <MarkdownViewer
                        className="mt-2"
                        content={note.body_markdown}
                        label={`手写笔记「${note.title || "阅读笔记"}」原文（第${index + 1}条）`}
                      />
                    </div>
                  ))
                ) : (
                  <EmptyState title="还没有阅读笔记" />
                )}
              </div>
            </CardContent>
          </Card>
        </div>
        <Card className="h-fit">
          <CardHeader>
            <h2 className="font-semibold">阅读状态</h2>
          </CardHeader>
          <CardContent className="space-y-4">
            <label className="block space-y-1.5 text-xs font-medium">
              阶段
              <select
                disabled={saving}
                value={paper.reading.status}
                onChange={(event) =>
                  saveReading({
                    status: event.target.value as Paper["reading"]["status"],
                  })
                }
                className="h-9 w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-3 text-sm"
              >
                {statuses.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label className="block space-y-1.5 text-xs font-medium">
              重要度
              <select
                disabled={saving}
                value={paper.reading.importance ?? ""}
                onChange={(event) =>
                  saveReading({
                    importance: event.target.value
                      ? Number(event.target.value)
                      : null,
                  })
                }
                className="h-9 w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-3 text-sm"
              >
                <option value="">未评分</option>
                {[1, 2, 3, 4, 5].map((value) => (
                  <option key={value} value={value}>
                    {"★".repeat(value)}
                  </option>
                ))}
              </select>
            </label>
            <label className="block space-y-1.5 text-xs font-medium">
              课题相关度（0–100）
              <Input
                disabled={saving}
                type="number"
                min="0"
                max="100"
                defaultValue={paper.reading.relevance ?? ""}
                onBlur={(event) =>
                  saveReading({
                    relevance: event.target.value
                      ? Number(event.target.value)
                      : null,
                  })
                }
              />
            </label>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
