"use client";
import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/input";
import type {
  ReproductionExcerptRange,
  ReproductionSourceContent,
} from "@/lib/api";

/** Map normalized textarea UTF16 boundaries to original Python code-point boundaries. */
export function textareaCodePointRange(
  original: string,
  start: number,
  end: number,
): ReproductionExcerptRange {
  const points = Array.from(original),
    boundaries = new Map<number, number>([[0, 0]]);
  let utf16 = 0;
  for (let at = 0; at < points.length;) {
    const crlf = points[at] === "\r" && points[at + 1] === "\n";
    const shown = points[at] === "\r" ? "\n" : points[at];
    utf16 += shown.length;
    at += crlf ? 2 : 1;
    boundaries.set(utf16, at);
  }
  const first = boundaries.get(start),
    last = boundaries.get(end);
  if (first === undefined || last === undefined || last <= first)
    throw new Error("请选取完整 Unicode 字符，不能只选半个字符或空范围。");
  return { start: first, end: last };
}
export function exactExcerpt(
  markdown: string,
  range: ReproductionExcerptRange,
) {
  return Array.from(markdown).slice(range.start, range.end).join("");
}

export function ReproductionExcerptPicker({
  source,
  ranges,
  onChange,
  disabled,
}: {
  source: ReproductionSourceContent;
  ranges: ReproductionExcerptRange[];
  onChange: (ranges: ReproductionExcerptRange[]) => void;
  disabled: boolean;
}) {
  const raw = useRef<HTMLTextAreaElement>(null);
  const [error, setError] = useState("");
  function add(range: ReproductionExcerptRange) {
    if (
      range.start < 0 ||
      range.end > Array.from(source.markdown).length ||
      range.end <= range.start
    ) {
      setError("来源中的选段范围无效，请重新核对。");
      return;
    }
    if (ranges.some((row) => range.start < row.end && range.end > row.start)) {
      setError("此范围与已选内容重复或重叠，请先移除对应范围。");
      return;
    }
    if (ranges.length >= 100) {
      setError("单次最多选取100个不重叠范围。");
      return;
    }
    onChange([...ranges, range].sort((a, b) => a.start - b.start));
    setError("");
  }
  return (
    <section
      className="space-y-3 rounded border border-[var(--border)] p-3"
      aria-label="本人精确笔记选段"
    >
      <p className="text-xs text-[var(--muted)]">
        选择实际标题范围，或在只读原文中选中明确文字再加入。位置按原始 Unicode
        字符计算；不摘要、不裁切、不替换原笔记。
      </p>
      {error && (
        <p
          role="alert"
          aria-label="选段需核对"
          className="text-xs text-[var(--danger)]"
        >
          {error}
        </p>
      )}
      <details>
        <summary className="cursor-pointer text-xs">
          按笔记实际标题加入范围
        </summary>
        <div className="mt-2 space-y-2">
          {source.headings.length ? (
            source.headings.map((heading, index) => (
              <div
                key={`${heading.start}:${index}`}
                className="flex flex-wrap items-center justify-between gap-2 text-xs"
              >
                <span>
                  {heading.title} · {heading.start}–{heading.end}
                </span>
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  disabled={disabled}
                  aria-label={`加入标题范围 ${heading.title}`}
                  onClick={() =>
                    add({ start: heading.start, end: heading.end })
                  }
                >
                  加入范围
                </Button>
              </div>
            ))
          ) : (
            <p className="text-xs text-[var(--muted)]">
              此笔记没有可用标题范围，可使用下方精确原文选择。
            </p>
          )}
        </div>
      </details>
      <Textarea
        ref={raw}
        readOnly
        value={source.markdown}
        aria-label="精读笔记选段原文"
        className="min-h-56 font-mono text-xs"
      />
      <Button
        type="button"
        size="sm"
        variant="secondary"
        disabled={disabled}
        onClick={() => {
          const field = raw.current;
          if (!field) return;
          try {
            if (field.value !== source.markdown.replace(/\r\n?/g, "\n"))
              throw new Error("展示原文与来源不匹配，请重新加载。");
            add(
              textareaCodePointRange(
                source.markdown,
                field.selectionStart,
                field.selectionEnd,
              ),
            );
          } catch (cause) {
            setError(cause instanceof Error ? cause.message : "选段无法定位。");
          }
        }}
      >
        加入当前原文选段
      </Button>
      <h3 className="text-xs font-medium">明确选段 · {ranges.length} 个</h3>
      {ranges.map((range, index) => (
        <div
          key={`${range.start}:${range.end}`}
          className="space-y-2 rounded border border-[var(--border)] p-2 text-xs"
        >
          <p>
            字符位置 {range.start}–{range.end}
          </p>
          <pre
            aria-label={`精确选段 ${index + 1}`}
            className="max-h-48 overflow-auto whitespace-pre-wrap break-words"
          >
            {exactExcerpt(source.markdown, range)}
          </pre>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            disabled={disabled}
            aria-label={`移除精确选段 ${index + 1}`}
            onClick={() => onChange(ranges.filter((_, at) => at !== index))}
          >
            移除此范围
          </Button>
        </div>
      ))}
    </section>
  );
}
