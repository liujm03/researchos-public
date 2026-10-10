"use client";
import Link from "next/link";
import { useState } from "react";
import { api, type Project } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/ui/state";
import { MarkdownViewer } from "@/components/markdown/markdown-viewer";
import { IdeaActions } from "./actions";
import {
  detailFields,
  errorText,
  statusLabel,
  type Idea,
  type Revision,
  type RevisionPage,
} from "./types";

function RevisionBody({ revision }: { revision: Revision }) {
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-3 text-xs text-[var(--muted)]">
        <span>
          版本 {revision.revision} · {statusLabel(revision.status)}
        </span>
        <span>{revision.created_at.slice(0, 16).replace("T", " ")}</span>
        <span>
          {revision.integrity_valid ? "版本完整性可核对" : "版本完整性异常"}
        </span>
      </div>
      <h2 className="text-lg font-semibold">{revision.title}</h2>
      {!!revision.tags?.length && (
        <p className="text-xs text-[var(--accent)]">
          {revision.tags.map((tag) => `#${tag}`).join(" · ")}
        </p>
      )}
      {revision.content && (
        <MarkdownViewer content={revision.content} label="灵感内容" />
      )}
      <div className="space-y-3">
        {detailFields.map(
          ([key, label]) =>
            revision[key] && (
              <details key={key}>
                <summary className="cursor-pointer text-sm font-medium">
                  {label}
                </summary>
                <MarkdownViewer content={revision[key] ?? ""} label={label} />
              </details>
            ),
        )}
      </div>
      <p className="text-xs text-[var(--muted)]">
        本人状态与判断尚不等于科学验证；笔记依据为 AI_DERIVED。
      </p>
      {!revision.context_current && (
        <p role="alert" className="text-sm text-[var(--danger)]">
          来源已变化：此版本保留原摘录与 SHA，不能当作当前有效来源直接转化。
        </p>
      )}
      <details>
        <summary className="cursor-pointer text-sm">
          精确文献依据 · {revision.sources.length} 个摘录
        </summary>
        <div className="mt-3 space-y-3">
          {!revision.sources.length && (
            <p className="text-sm text-[var(--muted)]">
              当前为本人输入，尚未选择精读笔记依据。
            </p>
          )}
          {revision.sources.map((source, index) => (
            <div
              key={source.id}
              className="space-y-2 rounded border p-3 text-xs"
            >
              <Link
                className="text-[var(--accent)]"
                href={`/papers/${source.paper_id}`}
              >
                {source.paper_title}
              </Link>
              <p>
                原笔记选段 · 字符 {source.start_offset}–{source.end_offset} ·{" "}
                {source.context_current ? "来源当前可核对" : "来源已变化"}
              </p>
              <pre
                className="max-h-56 overflow-auto whitespace-pre-wrap break-words"
                aria-label={`已保存文献摘录 ${index + 1}`}
              >
                {source.exact_quote}
              </pre>
              <details>
                <summary className="cursor-pointer">来源身份与哈希</summary>
                <pre className="overflow-auto whitespace-pre-wrap break-words">
                  {JSON.stringify(
                    {
                      canonical_note_id: source.canonical_note_id,
                      note_sha256: source.note_sha256,
                      source_sha256: source.source_sha256,
                      origin: source.origin,
                      ...source.source_facts,
                    },
                    null,
                    2,
                  )}
                </pre>
              </details>
            </div>
          ))}
        </div>
      </details>
      <details>
        <summary className="cursor-pointer text-xs">版本 SHA</summary>
        <p className="break-all text-xs">{revision.sha256}</p>
      </details>
    </div>
  );
}
export function IdeaDetail({
  idea,
  projects,
  onEdit,
  onRefresh,
}: {
  idea: Idea;
  projects: Project[];
  onEdit: () => void;
  onRefresh: () => Promise<void>;
}) {
  const [history, setHistory] = useState<RevisionPage | null>(null);
  const [revision, setRevision] = useState<Revision | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function loadHistory(cursor?: string | null) {
    setBusy(true);
    setError("");
    try {
      setHistory(
        await api.get<RevisionPage>(
          `/ideas/${idea.id}/revisions?limit=10${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
        ),
      );
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section
      aria-label="灵感详情"
      className="space-y-5 rounded-xl border bg-[var(--surface)] p-5"
    >
      <div className="flex flex-wrap justify-between gap-2">
        <p className="text-xs text-[var(--muted)]">
          {idea.project_id ? (
            <Link
              className="text-[var(--accent)]"
              href={`/projects/${idea.project_id}`}
            >
              {projects.find((project) => project.id === idea.project_id)
                ?.name ?? "所属课题"}
            </Link>
          ) : (
            "全局灵感 · 未指定主课题"
          )}
        </p>
        <Button size="sm" variant="secondary" onClick={onEdit}>
          编辑并保存新版本
        </Button>
      </div>
      <RevisionBody revision={revision ?? idea.current} />
      {revision && (
        <Button variant="secondary" size="sm" onClick={() => setRevision(null)}>
          返回当前版本
        </Button>
      )}
      <details>
        <summary className="cursor-pointer text-sm">版本历史</summary>
        <div className="mt-3 space-y-2">
          <Button
            variant="secondary"
            size="sm"
            disabled={busy}
            onClick={() => void loadHistory()}
          >
            读取版本历史
          </Button>
          {busy && (
            <p role="status" className="text-xs">
              读取历史中…
            </p>
          )}
          {error && <ErrorState message={error} />}
          {history?.items.map((item) => (
            <Button
              key={item.id}
              variant="ghost"
              size="sm"
              onClick={() => setRevision(item)}
            >
              查看版本 {item.revision} · {statusLabel(item.status)}
            </Button>
          ))}
          {history?.page.next_cursor && (
            <Button
              variant="secondary"
              size="sm"
              disabled={busy}
              onClick={() => void loadHistory(history.page.next_cursor)}
            >
              下一页历史
            </Button>
          )}
        </div>
      </details>
      {!revision && (
        <IdeaActions
          key={`${idea.id}:${idea.current.sha256}`}
          idea={idea}
          projects={projects}
          onRefresh={onRefresh}
        />
      )}
      <details>
        <summary className="cursor-pointer text-sm">已关联任务与任务书</summary>
        <div className="mt-3 space-y-2 text-xs">
          {!idea.task_actions.length && !idea.brief_actions.length && (
            <p className="text-[var(--muted)]">
              尚未转化。保存灵感不会自动创建后续任务。
            </p>
          )}
          {idea.task_actions.map((action) => (
            <p className="break-all" key={action.id}>
              <Link
                className="text-[var(--accent)]"
                href={`/tasks/${action.task_id}`}
              >
                待办任务 {action.task_id}
              </Link>{" "}
              · 来源版本 SHA {action.revision_sha256}
            </p>
          ))}
          {idea.brief_actions.map((action) => (
            <p className="break-all" key={action.id}>
              <Link
                className="text-[var(--accent)]"
                href={`/projects/${action.project_id}/brief?version=${action.brief_id}`}
              >
                任务书 DRAFT {action.brief_id}
              </Link>{" "}
              · 来源版本 {action.revision_id}
            </p>
          ))}
        </div>
      </details>
    </section>
  );
}
