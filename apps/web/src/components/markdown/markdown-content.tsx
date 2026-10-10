"use client";

import { Component, type ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { remarkFormulaCompat } from "./remark-formula-compat";
import { cn } from "@/lib/utils";

export interface MarkdownContentProps {
  content: string;
  className?: string;
}

function navigable(href: string | undefined): string | undefined {
  if (!href) return undefined;
  if (href.startsWith("/")) {
    try {
      const decoded = decodeURIComponent(href);
      return !href.startsWith("//") &&
        !decoded.startsWith("//") &&
        !/[\\\u0000-\u001f\u007f]/.test(href + decoded)
        ? href
        : undefined;
    } catch {
      return undefined;
    }
  }
  if (href.startsWith("#")) return href;
  try {
    const url = new URL(href);
    return ["http:", "https:"].includes(url.protocol) &&
      !url.username &&
      !url.password
      ? url.href
      : undefined;
  } catch {
    return undefined;
  }
}

const components: Components = {
  a: ({
    href,
    children,
    title,
    id,
    className,
    "aria-describedby": describedBy,
    "aria-label": label,
  }) => {
    const safe = navigable(href);
    if (!safe)
      return (
        <span title={href ? `链接地址：${href}` : undefined}>{children}</span>
      );
    const external = !safe.startsWith("#") && !safe.startsWith("/");
    return (
      <a
        href={safe}
        id={id}
        className={className}
        title={title}
        aria-describedby={describedBy}
        aria-label={label}
        target={external ? "_blank" : undefined}
        rel={external ? "noopener noreferrer" : undefined}
        referrerPolicy="no-referrer"
      >
        {children}
      </a>
    );
  },
  img: ({ src, alt, title }) => (
    <span className="markdown-image-reference" role="note">
      <span>{alt || title || "图片引用"}</span>
      {typeof src === "string" && src && <code>{src}</code>}
      <span className="markdown-reference-hint">图片未自动加载</span>
    </span>
  ),
  table: ({ children }) => (
    <div
      className="markdown-table-scroll"
      role="region"
      aria-label="Markdown 表格"
      tabIndex={0}
    >
      <table>{children}</table>
    </div>
  ),
};

class RenderBoundary extends Component<
  { content: string; children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    if (this.state.failed)
      return (
        <div>
          <p role="alert" className="markdown-error">
            Markdown 暂时无法排版，以下保留原文。
          </p>
          <pre className="markdown-raw">{this.props.content}</pre>
        </div>
      );
    return this.props.children;
  }
}

function frontmatter(content: string): {
  metadata: string | null;
  body: string;
} {
  const match =
    /^\uFEFF?---[^\S\r\n]*\r?\n([\s\S]*?)\r?\n(?:---|\.\.\.)[^\S\r\n]*(?:\r?\n|$)/.exec(
      content,
    );
  const hasMetadataKey =
    match !== null &&
    /^[ \t]*(?:[A-Za-z_\u3400-\u9fff][A-Za-z0-9_. \-\u3400-\u9fff]*|"[^"\r\n]+"|'[^'\r\n]+'):(?:[ \t]+|\r?$)/m.test(
      match[1],
    );
  return match && hasMetadataKey
    ? { metadata: match[0], body: content.slice(match[0].length) }
    : { metadata: null, body: content };
}

/** Source text stays immutable. Only GFM and bounded, untrusted KaTeX are rendered. */
export function MarkdownContent({ content, className }: MarkdownContentProps) {
  const { metadata, body } = frontmatter(content);
  return (
    <div className={cn("markdown-content", className)}>
      {metadata !== null && (
        <details className="markdown-frontmatter">
          <summary>文档元数据</summary>
          <pre className="markdown-raw">{metadata}</pre>
        </details>
      )}
      <RenderBoundary key={content} content={content}>
        <ReactMarkdown
          skipHtml
          remarkPlugins={[remarkGfm, remarkMath, remarkFormulaCompat]}
          rehypePlugins={[
            [
              rehypeKatex,
              {
                trust: false,
                throwOnError: false,
                maxExpand: 1000,
                maxSize: 20,
                strict: "ignore",
              },
            ],
          ]}
          components={components}
          urlTransform={(url) => url}
        >
          {body}
        </ReactMarkdown>
      </RenderBoundary>
      {content.length === 0 && (
        <p className="markdown-empty">暂无 Markdown 内容。</p>
      )}
    </div>
  );
}
