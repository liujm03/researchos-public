"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { api, type ReadingPlan } from "@/lib/api";
import type { components } from "@/lib/generated";

type SourceContent = components["schemas"]["ReadingSourceFileContentOut"];

export function ReadingPlanSources({
  paperId,
  plan,
}: {
  paperId: string;
  plan: ReadingPlan;
}) {
  const [contents, setContents] = useState<SourceContent[] | null>(null);
  const [visible, setVisible] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const sourceFiles = plan.source_files ?? [];

  async function loadFiles() {
    setVisible(true);
    setLoading(true);
    setError("");
    try {
      setContents(
        await api.get<SourceContent[]>(
          `/papers/${encodeURIComponent(paperId)}/reading-plans/${encodeURIComponent(plan.id)}/source-files`,
        ),
      );
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "无法读取本篇绑定文件快照",
      );
    } finally {
      setLoading(false);
    }
  }

  if (!sourceFiles.length)
    return (
      <p className="rounded border border-[var(--border)] p-2 text-xs text-[var(--muted)]">
        历史方案未记录文件级来源。保留原有技能、模板和批准计划哈希，不推断原始文件内容。
      </p>
    );

  return (
    <section
      aria-label="本篇冻结的技能与模板来源"
      className="space-y-3 rounded border border-[var(--border)] p-3 text-xs"
    >
      <h4 className="font-medium">本篇绑定文件 · {sourceFiles.length} 个</h4>
      <dl className="space-y-2">
        <div>
          <dt className="text-[var(--muted)]">文件绑定版本</dt>
          <dd className="break-all">
            {plan.source_binding_version || "版本未记录"}
          </dd>
        </div>
        <div>
          <dt className="text-[var(--muted)]">来源文件清单 SHA-256</dt>
          <dd className="break-all font-mono text-[10px]">
            {plan.source_manifest_sha256 || "清单哈希未记录"}
          </dd>
        </div>
      </dl>
      <ul className="space-y-2">
        {sourceFiles.map((file) => (
          <li
            key={`${file.role}:${file.path}`}
            className="space-y-1 rounded bg-[var(--surface)] p-2"
          >
            <p className="break-all">{file.path}</p>
            <p className="text-[var(--muted)]">
              {file.role === "TEMPLATE" ? "精读模板" : "指令 / 参考文件"} ·{" "}
              {file.size_bytes.toLocaleString("zh-CN")} 字节
            </p>
            <p className="break-all font-mono text-[10px]">
              原始文件 SHA-256：{file.sha256}
            </p>
          </li>
        ))}
      </ul>
      <p className="leading-5 text-[var(--muted)]">
        原始文件哈希、组装技能指令哈希和批准计划哈希分别记录。此清单仅说明本篇冻结使用的文件，不代表全局技能已经完成信任审核或运行测试。
      </p>
      <Button
        size="sm"
        variant="secondary"
        disabled={loading}
        aria-expanded={visible}
        aria-controls={`reading-source-files-${plan.id}`}
        onClick={() => {
          if (visible) setVisible(false);
          else if (contents) setVisible(true);
          else void loadFiles();
        }}
      >
        {loading
          ? "正在读取绑定文件…"
          : visible
            ? "收起绑定文件"
            : "查看绑定文件"}
      </Button>
      {visible && (
        <div id={`reading-source-files-${plan.id}`} className="space-y-2">
          {loading && <LoadingState label="正在读取冻结的原始文件快照…" />}
          {error && (
            <ErrorState message={error} onRetry={() => void loadFiles()} />
          )}
          {!loading &&
            !error &&
            contents &&
            (contents.length ? (
              contents.map((file) => (
                <details
                  key={`${file.role}:${file.path}`}
                  className="rounded border border-[var(--border)]"
                >
                  <summary className="cursor-pointer break-all p-2">
                    {file.path}
                  </summary>
                  <div className="space-y-2 border-t border-[var(--border)] p-2">
                    <p className="break-all font-mono text-[10px]">
                      原始文件 SHA-256：{file.sha256} ·{" "}
                      {file.size_bytes.toLocaleString("zh-CN")} 字节
                    </p>
                    <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-words rounded bg-[var(--surface)] p-3 font-mono leading-5">
                      {file.content}
                    </pre>
                  </div>
                </details>
              ))
            ) : (
              <EmptyState title="尚无绑定文件快照" />
            ))}
        </div>
      )}
    </section>
  );
}
