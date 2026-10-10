"use client";
import { useRef, useState } from "react";
import {
  api,
  type ReproductionSourcePage,
  type ReproductionSourceContent,
  type ReproductionExcerptRange,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/ui/state";
import {
  ReproductionExcerptPicker,
  exactExcerpt,
} from "@/components/papers/reproduction-excerpts";
import { MarkdownViewer } from "@/components/markdown/markdown-viewer";
import { errorText, type Source } from "./types";

export function IdeaSourcePicker({
  selections,
  onChange,
  disabled,
  projectId,
}: {
  selections: Source[];
  onChange: (values: Source[]) => void;
  disabled: boolean;
  projectId?: string;
}) {
  const [page, setPage] = useState<ReproductionSourcePage | null>(null);
  const [content, setContent] = useState<ReproductionSourceContent | null>(
    null,
  );
  const [ranges, setRanges] = useState<ReproductionExcerptRange[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const sequence = useRef(0);
  async function load(cursor?: string | null) {
    const current = ++sequence.current;
    setBusy(true);
    setError("");
    try {
      const result = await api.get<ReproductionSourcePage>(
        `${projectId ? `/claims/canonical-sources?project_id=${encodeURIComponent(projectId)}&` : "/ideas/sources?"}limit=20${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
      );
      if (current === sequence.current) setPage(result);
    } catch (cause) {
      if (current === sequence.current) setError(errorText(cause));
    } finally {
      if (current === sequence.current) setBusy(false);
    }
  }
  async function open(id: string, paperId: string) {
    const current = ++sequence.current;
    setBusy(true);
    setError("");
    setContent(null);
    setRanges([]);
    try {
      const result = await api.get<ReproductionSourceContent>(
        projectId
          ? `/claims/canonical-sources/${encodeURIComponent(id)}?project_id=${encodeURIComponent(projectId)}&paper_id=${encodeURIComponent(paperId)}`
          : `/ideas/sources/${encodeURIComponent(id)}?paper_id=${encodeURIComponent(paperId)}`,
      );
      if (current === sequence.current) setContent(result);
    } catch (cause) {
      if (current === sequence.current) setError(errorText(cause));
    } finally {
      if (current === sequence.current) setBusy(false);
    }
  }
  function include() {
    if (!content || !ranges.length) return;
    const rows: Source[] = ranges.map((range) => ({
      canonical_note_id: content.id,
      expected_note_sha256: content.note_sha256,
      start_offset: range.start,
      end_offset: range.end,
      exact_quote: exactExcerpt(content.markdown, range),
    }));
    if (selections.length + rows.length > (projectId ? 40 : 20)) {
      setError(
        projectId
          ? "单个主张最多保存40个来源摘录。"
          : "单个灵感最多保存 20 个来源摘录。",
      );
      return;
    }
    if (
      rows.some((row) =>
        selections.some(
          (existing) =>
            existing.canonical_note_id === row.canonical_note_id &&
            existing.start_offset < row.end_offset &&
            row.start_offset < existing.end_offset,
        ),
      )
    ) {
      setError("摘录与已有选段重复或重叠，请先移除已有选段。");
      return;
    }
    onChange([...selections, ...rows]);
    setRanges([]);
    setError("");
  }
  return (
    <details className="space-y-3">
      <summary className="cursor-pointer text-sm">
        文献依据 · 已选 {selections.length} 个精确摘录
      </summary>
      <p className="text-xs text-[var(--muted)]">
        从已批准 Skill 精读的实际 Markdown 标题或原文选段；摘录为 AI
        派生笔记，不能当作论文作者的原始事实。
      </p>
      <Button
        type="button"
        size="sm"
        variant="secondary"
        disabled={disabled || busy}
        onClick={() => void load()}
      >
        读取精读笔记来源
      </Button>
      {busy && (
        <p role="status" className="text-xs">
          读取来源中…
        </p>
      )}
      {error && <ErrorState message={error} />}
      {page && (
        <div className="space-y-2">
          {!page.items.length && (
            <p className="text-sm text-[var(--muted)]">
              没有可用精读笔记，请先在文献页面批准 Skill 精读。
            </p>
          )}
          {page.items.map((source) => (
            <div
              key={source.id}
              className="flex flex-wrap items-center justify-between gap-2 rounded border p-2 text-xs"
            >
              <span>
                {source.paper_title || `笔记 ${source.id.slice(0, 8)}`} ·{" "}
                {source.note_characters} 字符 · {source.created_at.slice(0, 10)}
                {!source.can_prepare && ` · ${source.gaps.join("；")}`}
              </span>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                disabled={disabled || busy || !source.can_prepare}
                onClick={() => void open(source.id, source.paper_id)}
              >
                选择原文摘录
              </Button>
            </div>
          ))}
          {page.page.next_cursor && (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              disabled={busy || disabled}
              onClick={() => void load(page.page.next_cursor)}
            >
              下一页笔记来源
            </Button>
          )}
        </div>
      )}
      {content && (
        <>
          <p className="break-all text-xs">
            原笔记 SHA · {content.note_sha256}
          </p>
          <details>
            <summary className="cursor-pointer text-xs">浏览完整源笔记</summary>
            <MarkdownViewer
              content={content.markdown}
              label={projectId ? "主张源笔记" : "灵感源笔记"}
            />
          </details>
          <ReproductionExcerptPicker
            source={content}
            ranges={ranges}
            onChange={setRanges}
            disabled={disabled || busy}
          />
          <Button
            type="button"
            size="sm"
            disabled={disabled || busy || !ranges.length}
            onClick={include}
          >
            {projectId ? "将明确选段加入主张依据" : "将明确选段加入灵感依据"}
          </Button>
        </>
      )}
      <div className="space-y-2">
        {selections.map((source, index) => (
          <div
            className="rounded border p-3 text-xs"
            key={`${source.canonical_note_id}:${source.start_offset}:${source.end_offset}`}
          >
            <p className="break-all">
              笔记 {source.canonical_note_id} · 字符 {source.start_offset}–
              {source.end_offset} · SHA {source.expected_note_sha256}
            </p>
            <pre
              className="max-h-40 overflow-auto whitespace-pre-wrap break-words"
              aria-label={`${projectId ? "主张" : "灵感"}依据摘录 ${index + 1}`}
            >
              {source.exact_quote}
            </pre>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              disabled={disabled}
              onClick={() =>
                onChange(selections.filter((_, at) => at !== index))
              }
            >
              移除摘录 {index + 1}
            </Button>
          </div>
        ))}
      </div>
    </details>
  );
}
