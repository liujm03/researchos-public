"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import type { components } from "@/lib/generated";

type SourcePage = components["schemas"]["ResearchBriefCanonicalSourcePage"];
type Choice = components["schemas"]["ResearchBriefCanonicalSelection"];
type Detail = components["schemas"]["ResearchBriefDetailOut"];

export function ResearchBriefNotePicker({
  projectId,
  base,
  selected,
  busy,
  onChange,
}: {
  projectId: string;
  base: Detail | null;
  selected: Choice[];
  busy: boolean;
  onChange: (sources: Choice[]) => void;
}) {
  const [opened, setOpened] = useState(false);
  const [page, setPage] = useState<SourcePage | null>(null);
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  const [index, setIndex] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const sequence = useRef(0);
  async function load(cursor: string | null, nextIndex: number) {
    const request = ++sequence.current;
    setLoading(true);
    setError("");
    try {
      const result = await api.get<SourcePage>(
        `/projects/${encodeURIComponent(projectId)}/research-briefs/canonical-sources?limit=20${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
      );
      if (request !== sequence.current) return;
      setPage(result);
      setIndex(nextIndex);
    } catch (cause) {
      if (request === sequence.current)
        setError(cause instanceof Error ? cause.message : "精读来源读取失败");
    } finally {
      if (request === sequence.current) setLoading(false);
    }
  }
  return (
    <fieldset className="space-y-3 rounded border border-[var(--border)] p-3">
      <legend className="px-1 text-xs font-medium">
        精读笔记来源 · {selected.length}/20
      </legend>
      <p className="text-xs leading-5 text-[var(--muted)]">
        选择本课题论文的 Canonical Markdown
        原笔记，保存完整原文及批准来源快照。笔记是 AI
        派生候选，需要本人核对；选择不发送 PDF、不启动 AI。
      </p>
      {selected.length > 0 && (
        <ul aria-label="已选精读来源" className="space-y-2">
          {selected.map((choice) => {
            const frozen = base?.canonical_note_sources?.find(
              (source) => source.canonical_note_id === choice.canonical_note_id,
            );
            const available = page?.items.find(
              (source) => source.canonical_note_id === choice.canonical_note_id,
            );
            return (
              <li
                key={choice.canonical_note_id}
                className="flex items-start justify-between gap-3 rounded bg-[var(--surface)] p-2 text-xs"
              >
                <div className="min-w-0 space-y-1">
                  <p>
                    {available?.paper_title ??
                      frozen?.paper_title ??
                      "已选精读笔记"}
                  </p>
                  <p className="break-all font-mono">
                    笔记 SHA-256：{choice.expected_note_sha256}
                  </p>
                  {frozen && (
                    <p className="text-[var(--muted)]">
                      沿用本版本冻结的原笔记；不随当前笔记自动更新。
                    </p>
                  )}
                  {available &&
                    available.note_sha256 !== choice.expected_note_sha256 && (
                      <p className="text-[var(--danger)]">
                        当前笔记 SHA
                        已变化。旧快照仍保留；核对后移除此选择，再选当前笔记以保存新的来源。
                      </p>
                    )}
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  disabled={busy}
                  onClick={() =>
                    onChange(
                      selected.filter(
                        (item) =>
                          item.canonical_note_id !== choice.canonical_note_id,
                      ),
                    )
                  }
                >
                  移除精读来源
                </Button>
              </li>
            );
          })}
        </ul>
      )}
      <Button
        type="button"
        size="sm"
        variant="secondary"
        disabled={busy || loading}
        onClick={() => {
          setOpened(true);
          void load(cursors[index] ?? null, index);
        }}
      >
        {opened ? "刷新可用精读笔记" : "选择课题精读笔记"}
      </Button>
      {opened && (
        <div className="space-y-3">
          {loading && (
            <p role="status" className="text-xs">
              正在读取精读来源…
            </p>
          )}
          {error && (
            <p
              role="alert"
              aria-label="精读来源读取失败"
              className="text-xs text-[var(--danger)]"
            >
              {error}。已有选择和草稿保留，可刷新重试。
            </p>
          )}
          {!loading &&
            !error &&
            page &&
            (page.items.length ? (
              <div className="max-h-80 space-y-3 overflow-auto">
                {page.items.map((source) => {
                  const chosen = selected.some(
                    (choice) =>
                      choice.canonical_note_id === source.canonical_note_id,
                  );
                  return (
                    <div
                      key={source.canonical_note_id}
                      className="space-y-1 rounded border border-[var(--border)] p-2 text-xs"
                    >
                      <label className="flex items-start gap-2">
                        <input
                          type="checkbox"
                          aria-label={`选择精读笔记 ${source.paper_title}`}
                          checked={chosen}
                          disabled={
                            busy ||
                            loading ||
                            (!chosen &&
                              (!source.can_select || selected.length >= 20))
                          }
                          onChange={(event) =>
                            onChange(
                              event.target.checked
                                ? [
                                    ...selected,
                                    {
                                      canonical_note_id:
                                        source.canonical_note_id,
                                      expected_note_sha256: source.note_sha256,
                                    },
                                  ]
                                : selected.filter(
                                    (choice) =>
                                      choice.canonical_note_id !==
                                      source.canonical_note_id,
                                  ),
                            )
                          }
                        />
                        <span>
                          {source.paper_title} · {source.note_characters} 字
                        </span>
                      </label>
                      <p className="break-all font-mono text-[var(--muted)]">
                        SHA-256：{source.note_sha256}
                      </p>
                      {source.gaps.length > 0 && (
                        <p className="break-words text-[var(--danger)]">
                          来源缺口：{source.gaps.join("、")}
                        </p>
                      )}
                      <Link
                        href={`/papers/${source.paper_id}`}
                        className="text-[var(--accent)] underline"
                      >
                        核对论文与精读来源
                      </Link>
                    </div>
                  );
                })}
              </div>
            ) : (
              <p className="text-xs text-[var(--muted)]">
                本课题尚无可用精读笔记。关联论文并完成 Skill
                精读后可选择；无精读来源的 Idea 草稿仍可保存。
              </p>
            ))}
          {page && (
            <div className="flex items-center justify-between gap-2 text-xs">
              <Button
                type="button"
                size="sm"
                variant="secondary"
                disabled={busy || loading || index === 0}
                onClick={() => void load(cursors[index - 1] ?? null, index - 1)}
              >
                上一页精读来源
              </Button>
              <span>第 {index + 1} 页</span>
              <Button
                type="button"
                size="sm"
                variant="secondary"
                disabled={busy || loading || !!error || !page.page.next_cursor}
                onClick={() => {
                  const next = page.page.next_cursor;
                  if (!next) return;
                  setCursors((old) => [...old.slice(0, index + 1), next]);
                  void load(next, index + 1);
                }}
              >
                下一页精读来源
              </Button>
            </div>
          )}
        </div>
      )}
      <Button
        type="button"
        size="sm"
        variant="ghost"
        disabled={busy || !selected.length}
        onClick={() => onChange([])}
      >
        清空精读来源
      </Button>
    </fieldset>
  );
}
