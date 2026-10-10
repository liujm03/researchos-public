"use client";

import { useState, type FormEvent } from "react";
import { MarkdownContent } from "@/components/markdown/markdown-content";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Textarea } from "@/components/ui/input";
import type { ProjectPaper } from "@/lib/api";
import type { components } from "@/lib/generated";
import { ResearchBriefNotePicker } from "./research-brief-note-picker";

type Detail = components["schemas"]["ResearchBriefDetailOut"];
type Create = components["schemas"]["ResearchBriefCreate"];
export const briefSections = [
  ["intent", "研究意图"],
  ["related_work", "相关研究"],
  ["hypotheses", "假设"],
  ["resources", "资源与约束"],
  ["routes", "候选技术路线"],
  ["protocol", "实验协议"],
  ["stage_plan", "阶段计划"],
  ["decision", "本人决策"],
] as const;
type SectionKey = (typeof briefSections)[number][0];

export function ResearchBriefEditor({
  base,
  projectId,
  papers,
  papersUnavailable = false,
  busy,
  onSave,
  onNew,
}: {
  base: Detail | null;
  projectId: string;
  papers: ProjectPaper[];
  papersUnavailable?: boolean;
  busy: boolean;
  onSave: (body: Create) => Promise<void>;
  onNew: () => void;
}) {
  const [idea, setIdea] = useState(base?.idea ?? "");
  const [sections, setSections] = useState<Record<SectionKey, string>>(
    () =>
      Object.fromEntries(
        briefSections.map(([key]) => [
          key,
          base?.sections.find((section) => section.key === key)?.content ?? "",
        ]),
      ) as Record<SectionKey, string>,
  );
  const [stopRules, setStopRules] = useState(base?.stop_rules ?? "");
  const [selected, setSelected] = useState<string[]>(
    base?.evidence.map((evidence) => evidence.paper_id) ?? [],
  );
  const [refreshEvidence, setRefreshEvidence] = useState(false);
  const [noteSources, setNoteSources] = useState<
    NonNullable<Create["canonical_note_sources"]>
  >(
    () =>
      base?.canonical_note_sources?.map((source) => ({
        canonical_note_id: source.canonical_note_id,
        expected_note_sha256: source.note_sha256,
      })) ?? [],
  );
  const [notesChanged, setNotesChanged] = useState(false);
  const originalEvidence =
    base?.evidence.map((evidence) => evidence.paper_id) ?? [];
  const evidenceChanged =
    selected.length !== originalEvidence.length ||
    selected.some((id) => !originalEvidence.includes(id));
  const inheritedUnlisted = originalEvidence.filter(
    (id) => !papers.some((paper) => paper.id === id),
  );

  async function save(event: FormEvent) {
    event.preventDefault();
    if (busy || !idea.trim()) return;
    const changes = briefSections.flatMap(([key]) => {
      const raw = sections[key];
      const value = raw.trim();
      const previous =
        base?.sections.find((section) => section.key === key)?.content ?? "";
      return base
        ? raw !== previous
          ? [{ key, content: value || null }]
          : []
        : value
          ? [{ key, content: value }]
          : [];
    });
    const body: Create = {
      idea: idea.trim(),
      sections: changes,
      ...(base
        ? { base_brief_id: base.id, expected_base_sha256: base.sha256 }
        : {}),
      ...(!base || evidenceChanged || refreshEvidence
        ? { evidence_paper_ids: selected }
        : {}),
      ...(notesChanged || (!base && noteSources.length)
        ? { canonical_note_sources: noteSources }
        : {}),
      ...(!base || stopRules !== (base.stop_rules ?? "")
        ? { stop_rules: stopRules.trim() || null }
        : {}),
    };
    await onSave(body);
  }

  return (
    <Card>
      <CardHeader>
        <h2 className="font-semibold">
          {base ? `从版本 ${base.revision} 生成修订草稿` : "新任务书草稿"}
        </h2>
        {base && (
          <Button size="sm" variant="secondary" disabled={busy} onClick={onNew}>
            改为独立新草稿
          </Button>
        )}
      </CardHeader>
      <CardContent>
        <form onSubmit={save} className="space-y-4">
          <p className="text-xs leading-5 text-[var(--muted)]">
            可以先只记录一个 Idea，逐步补齐任务书。保存不复制 PDF、不调用
            AI，也不启动模型或训练。
          </p>
          {base && (
            <p className="break-all text-xs text-[var(--muted)]">
              继承版本 ID {base.id} · SHA-256 {base.sha256}
              。修改保存为新版本，旧内容和审阅保留。
            </p>
          )}
          <label className="block space-y-1.5 text-xs font-medium">
            研究 Idea（必填）
            <Textarea
              aria-label="研究 Idea（必填）"
              required
              maxLength={12000}
              disabled={busy}
              value={idea}
              onChange={(event) => setIdea(event.target.value)}
              placeholder="希望解决什么科研问题？先记录一个想法即可。"
            />
          </label>
          <details className="rounded border border-[var(--border)]">
            <summary className="cursor-pointer px-3 py-2 text-xs">
              预览研究 Idea（只读）
            </summary>
            <MarkdownContent content={idea || "尚未填写"} className="p-3" />
          </details>
          <div className="space-y-2">
            {briefSections.map(([key, label]) => (
              <details
                key={key}
                className="rounded border border-[var(--border)]"
              >
                <summary className="cursor-pointer px-3 py-2 text-sm">
                  {label}
                  {sections[key] ? " · 已填写" : " · 可后续补充"}
                </summary>
                <div className="space-y-2 border-t border-[var(--border)] p-3">
                  {base?.sections.find((section) => section.key === key)
                    ?.origin_type === "PROJECT_CONTEXT" && (
                    <p className="text-xs text-[var(--muted)]">
                      继承自项目字段的候选内容，需要本人核对；不是论文精读事实。
                    </p>
                  )}
                  <label className="block space-y-1.5 text-xs font-medium">
                    {label}内容
                    <Textarea
                      aria-label={`${label}内容`}
                      maxLength={40000}
                      disabled={busy}
                      value={sections[key]}
                      onChange={(event) =>
                        setSections((value) => ({
                          ...value,
                          [key]: event.target.value,
                        }))
                      }
                    />
                  </label>
                  <details>
                    <summary className="cursor-pointer py-1 text-xs">
                      预览{label}（只读）
                    </summary>
                    <MarkdownContent content={sections[key] || "尚未填写"} />
                  </details>
                </div>
              </details>
            ))}
          </div>
          <details className="rounded border border-[var(--border)]">
            <summary className="cursor-pointer px-3 py-2 text-sm">
              停止规则 · 可选
            </summary>
            <label className="block space-y-1.5 border-t border-[var(--border)] p-3 text-xs font-medium">
              停止规则内容
              <Textarea
                aria-label="停止规则内容"
                maxLength={40000}
                disabled={busy}
                value={stopRules}
                onChange={(event) => setStopRules(event.target.value)}
              />
            </label>
            <details className="p-3 pt-0">
              <summary className="cursor-pointer text-xs">
                预览停止规则（只读）
              </summary>
              <MarkdownContent content={stopRules || "尚未填写"} />
            </details>
          </details>
          <fieldset className="space-y-2 rounded border border-[var(--border)] p-3">
            <legend className="px-1 text-xs font-medium">
              冻结文献来源 · {selected.length}/20
            </legend>
            <p className="text-xs leading-5 text-[var(--muted)]">
              选择本课题已关联的论文元数据作为版本来源。标题、摘要与候选来源不是已精读或已验证事实；不会复制原
              PDF。
            </p>
            {papers.length ? (
              <div className="max-h-64 space-y-2 overflow-auto">
                {papers.map((paper) => (
                  <label
                    key={paper.id}
                    className="flex items-start gap-2 text-xs"
                  >
                    <input
                      type="checkbox"
                      disabled={
                        busy ||
                        (!selected.includes(paper.id) && selected.length >= 20)
                      }
                      checked={selected.includes(paper.id)}
                      onChange={(event) =>
                        setSelected((value) =>
                          event.target.checked
                            ? [...value, paper.id]
                            : value.filter((id) => id !== paper.id),
                        )
                      }
                    />
                    <span>
                      {paper.title}
                      {paper.year ? ` · ${paper.year}` : ""}
                    </span>
                  </label>
                ))}
              </div>
            ) : (
              <p className="text-xs text-[var(--muted)]">
                {papersUnavailable
                  ? "文献列表暂不可用；可以先保存无文献草稿。"
                  : "本课题尚未关联论文，也可先保存无文献的 Idea 草稿。"}
              </p>
            )}
            {inheritedUnlisted.length > 0 && (
              <p className="break-all text-xs text-[var(--muted)]">
                旧版包含当前列表未出现的冻结来源：{inheritedUnlisted.join("、")}
                。继承保留原快照；重新捕获时服务端会核对当前归属与关联。
              </p>
            )}
            {base && (
              <label className="flex items-center gap-2 text-xs">
                <input
                  type="checkbox"
                  checked={refreshEvidence}
                  disabled={busy}
                  onChange={(event) => setRefreshEvidence(event.target.checked)}
                />
                更新为当前选中文献快照
              </label>
            )}
            <Button
              size="sm"
              variant="ghost"
              type="button"
              disabled={busy || !selected.length}
              onClick={() => {
                setSelected([]);
                setRefreshEvidence(true);
              }}
            >
              清空文献选择
            </Button>
          </fieldset>
          <ResearchBriefNotePicker
            projectId={projectId}
            base={base}
            selected={noteSources}
            busy={busy}
            onChange={(sources) => {
              setNoteSources(sources);
              setNotesChanged(true);
            }}
          />
          <Button type="submit" disabled={busy || !idea.trim()}>
            {busy ? "正在保存…" : base ? "保存为新版本" : "保存任务书草稿"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
