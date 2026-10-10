"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { MarkdownContent } from "./markdown-content";

export interface MarkdownViewerProps {
  content: string;
  label?: string;
  className?: string;
  showCopy?: boolean;
}

/** Preview is a view, never a rewrite: source mode and clipboard preserve the supplied string. */
export function MarkdownViewer({
  content,
  label,
  className,
  showCopy = true,
}: MarkdownViewerProps) {
  const [mode, setMode] = useState<"preview" | "source">("preview");
  const [copyResult, setCopyResult] = useState<{
    content: string;
    error: boolean;
  } | null>(null);
  const name = label ?? "Markdown";
  async function copy() {
    try {
      await navigator.clipboard.writeText(content);
      setCopyResult({ content, error: false });
    } catch {
      setCopyResult({ content, error: true });
    }
  }
  return (
    <section
      role="region"
      aria-label={`${name}查看器`}
      className={cn("markdown-viewer min-w-0", className)}
    >
      <div
        className="markdown-toolbar"
        role="group"
        aria-label={`${name}显示方式`}
      >
        <Button
          type="button"
          size="sm"
          variant={mode === "preview" ? "secondary" : "ghost"}
          aria-label={`${name}：浏览`}
          aria-pressed={mode === "preview"}
          onClick={() => setMode("preview")}
        >
          浏览
        </Button>
        <Button
          type="button"
          size="sm"
          variant={mode === "source" ? "secondary" : "ghost"}
          aria-label={`${name}：原文`}
          aria-pressed={mode === "source"}
          onClick={() => setMode("source")}
        >
          原文
        </Button>
        {showCopy && (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            aria-label={`${name}：复制原文`}
            onClick={copy}
          >
            复制原文
          </Button>
        )}
        {copyResult?.content === content && (
          <span
            role={copyResult.error ? "alert" : "status"}
            className={
              copyResult.error ? "markdown-error" : "markdown-copy-status"
            }
          >
            {copyResult.error
              ? "复制失败，请切换原文后手动复制。"
              : "已复制原文"}
          </span>
        )}
      </div>
      {mode === "preview" ? (
        <MarkdownContent content={content} />
      ) : (
        <pre className="markdown-raw" aria-label={label}>
          {content}
        </pre>
      )}
    </section>
  );
}
