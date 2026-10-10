"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { MarkdownViewer } from "@/components/markdown/markdown-viewer";
import { message, type Bundle, type BundlePage, type Fields } from "./types";
export function PublicationSources({
  projectId,
  sources,
  details,
  busy,
  onChange,
}: {
  projectId: string;
  sources: Fields["sources"];
  details: Bundle[];
  busy: boolean;
  onChange: (sources: Fields["sources"], details: Bundle[]) => void;
}) {
  const [page, setPage] = useState<BundlePage | null>(null),
    [loading, setLoading] = useState(false),
    [error, setError] = useState("");
  async function load(cursor?: string | null) {
    setLoading(true);
    setError("");
    try {
      setPage(
        await api.get<BundlePage>(
          `/projects/${projectId}/publications/source-options?limit=20${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
        ),
      );
    } catch (cause) {
      setError(message(cause));
    } finally {
      setLoading(false);
    }
  }
  async function add(id: string) {
    setLoading(true);
    setError("");
    try {
      const value = await api.get<Bundle>(
        `/projects/${projectId}/evidence-bundles/${id}`,
      );
      if (
        value.project_id !== projectId ||
        value.status !== "READY" ||
        !value.integrity_valid
      )
        throw new Error("证据包不属于本课题或尚未完整保存。");
      onChange(
        [
          ...sources,
          { bundle_id: id, expected_bundle_sha256: value.bundle_sha256 },
        ],
        [...details, value],
      );
    } catch (cause) {
      setError(message(cause));
    } finally {
      setLoading(false);
    }
  }
  return (
    <section className="space-y-3" aria-label="论文证据来源">
      <h3 className="font-medium">选择已保存的文本证据包</h3>
      <p className="text-xs text-[var(--muted)]">
        READY 表示文本包已保存，未包含源图表文件，也不代表科学结论或引用已核验。
      </p>
      <Button
        size="sm"
        variant="secondary"
        disabled={busy || loading}
        onClick={() => void load()}
      >
        读取可选证据包
      </Button>
      {loading && <p role="status">读取来源中…</p>}
      {error && <p role="alert">{error}</p>}
      {page?.items.map((row) => (
        <div
          key={row.id}
          className="flex items-center justify-between border p-2 text-sm"
        >
          <span>
            {row.label} · {row.status}
          </span>
          <Button
            size="sm"
            disabled={
              busy ||
              loading ||
              sources.some((s) => s.bundle_id === row.id) ||
              row.status !== "READY"
            }
            onClick={() => void add(row.id)}
          >
            选择证据包
          </Button>
        </div>
      ))}
      {page && !page.items.length && (
        <p>没有可选证据包，请先到科研主张与证据保存包。</p>
      )}
      {page?.page.next_cursor && (
        <Button
          disabled={busy || loading}
          variant="ghost"
          onClick={() => void load(page.page.next_cursor)}
        >
          下一页证据包
        </Button>
      )}
      {sources.map((source) => {
        const detail = details.find((d) => d.id === source.bundle_id);
        return (
          <details className="rounded border p-3" key={source.bundle_id}>
            <summary>{detail?.label ?? source.bundle_id} · 固定来源</summary>
            <p className="break-all text-xs">
              SHA-256：{source.expected_bundle_sha256}
            </p>
            {detail && (
              <>
                <p className="text-xs">
                  完整性：{detail.integrity_valid ? "完整" : "异常"} ·
                  当前来源：{detail.context_current ? "未变化" : "已变化"}
                </p>
                <ul className="text-xs">
                  {detail.current_gaps.map((g, i) => (
                    <li key={i}>{g}</li>
                  ))}
                </ul>
                {detail.files
                  .filter((f) => f.path === "claims.md")
                  .map((f) => (
                    <MarkdownViewer
                      key={f.path}
                      content={f.content}
                      label="包内主张"
                    />
                  ))}
              </>
            )}
            <Button
              size="sm"
              disabled={busy}
              variant="ghost"
              onClick={() =>
                onChange(
                  sources.filter((s) => s.bundle_id !== source.bundle_id),
                  details.filter((d) => d.id !== source.bundle_id),
                )
              }
            >
              移除来源
            </Button>
          </details>
        );
      })}
    </section>
  );
}
