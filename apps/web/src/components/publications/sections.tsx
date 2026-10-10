"use client";
import { useState } from "react";
import { MarkdownViewer } from "@/components/markdown/markdown-viewer";
import { Textarea } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import type { Section } from "./types";
export function SectionEditor({
  sections,
  busy,
  onChange,
}: {
  sections: Section[];
  busy: boolean;
  onChange: (rows: Section[]) => void;
}) {
  const [selected, setSelected] = useState(sections[0]?.key ?? "");
  const row = sections.find((s) => s.key === selected) ?? sections[0];
  function patch(value: Partial<Section>) {
    onChange(sections.map((s) => (s.key === row.key ? { ...s, ...value } : s)));
  }
  return (
    <section className="space-y-3" aria-label="骨架与章节编辑">
      <div className="flex flex-wrap gap-2">
        {sections.map((s) => (
          <Button
            key={s.key}
            size="sm"
            variant={row?.key === s.key ? "secondary" : "ghost"}
            onClick={() => setSelected(s.key)}
          >
            {s.title}
            {s.kind === "SKELETON" ? " · 骨架" : ""}
          </Button>
        ))}
      </div>
      {row && (
        <>
          <label className="block text-sm">
            {row.title}状态
            <select
              className="ml-2 rounded border p-1"
              aria-label={`${row.title}状态`}
              disabled={busy}
              value={row.status}
              onChange={(e) =>
                patch({ status: e.target.value as Section["status"] })
              }
            >
              {[
                ["NOT_STARTED", "未开始"],
                ["DRAFT", "草稿"],
                ["REVISING", "修改中"],
                ["COMPLETED", "已完成"],
              ].map(([k, t]) => (
                <option key={k} value={k}>
                  {t}
                </option>
              ))}
            </select>
          </label>
          <label className="block space-y-1 text-sm">
            {row.title} Markdown
            <Textarea
              aria-label={`${row.title} Markdown`}
              value={row.markdown}
              disabled={busy}
              rows={12}
              onChange={(e) => patch({ markdown: e.target.value })}
            />
          </label>
          <MarkdownViewer content={row.markdown} label={`${row.title}预览`} />
        </>
      )}
    </section>
  );
}
