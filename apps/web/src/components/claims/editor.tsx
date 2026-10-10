"use client";
import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";
import type { ProjectQuestion } from "@/lib/api";
import { EvidencePicker } from "./evidence-picker";
import {
  kinds,
  inherited,
  type Fields,
  type Evidence,
  type Revision,
} from "./types";
export function ClaimEditor({
  projectId,
  base,
  questions,
  busy,
  onSave,
  onCancel,
}: {
  projectId: string;
  base: Revision | null;
  questions: ProjectQuestion[];
  busy: boolean;
  onSave: (fields: Fields, evidence: Evidence[]) => Promise<void>;
  onCancel: () => void;
}) {
  const [fields, setFields] = useState<Fields>({
    title: base?.title ?? "",
    text: base?.text ?? "",
    kind: base?.kind ?? "HYPOTHESIS",
    conditions: base?.conditions ?? "",
    limitations: base?.limitations ?? "",
    evaluation_criteria: base?.evaluation_criteria ?? "",
    research_question_id: base?.research_question_id ?? null,
  });
  const [evidence, setEvidence] = useState<Evidence[]>(
      () => base?.evidence.map(inherited) ?? [],
    ),
    [error, setError] = useState("");
  async function save(e: FormEvent) {
    e.preventDefault();
    if (!fields.title.trim() || !fields.text.trim()) {
      setError("请输入标题与主张原文");
      return;
    }
    setError("");
    await onSave(fields, evidence);
  }
  return (
    <form className="space-y-4" onSubmit={save} aria-label="科研主张编辑">
      <h2 className="font-semibold">
        {base ? `修订主张 · 基于版本 ${base.revision}` : "创建科研主张"}
      </h2>
      <label className="block text-sm">
        主张标题
        <Input
          aria-label="主张标题"
          required
          maxLength={320}
          value={fields.title}
          disabled={busy}
          onChange={(e) => setFields({ ...fields, title: e.target.value })}
        />
      </label>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-sm">
          主张类型
          <select
            aria-label="主张类型"
            className="block w-full rounded border p-2 bg-[var(--surface)]"
            disabled={busy}
            value={fields.kind}
            onChange={(e) =>
              setFields({ ...fields, kind: e.target.value as Fields["kind"] })
            }
          >
            {kinds.map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          关联研究问题
          <select
            aria-label="关联研究问题"
            className="block w-full rounded border p-2 bg-[var(--surface)]"
            disabled={busy}
            value={fields.research_question_id ?? ""}
            onChange={(e) =>
              setFields({
                ...fields,
                research_question_id: e.target.value || null,
              })
            }
          >
            <option value="">不指定问题</option>
            {questions.map((row) => (
              <option key={row.id} value={row.id}>
                {row.question}
              </option>
            ))}
          </select>
        </label>
      </div>
      <label className="block text-sm">
        主张原文（Markdown）
        <Textarea
          aria-label="主张原文（Markdown）"
          required
          maxLength={20000}
          className="min-h-28"
          value={fields.text}
          disabled={busy}
          onChange={(e) => setFields({ ...fields, text: e.target.value })}
        />
      </label>
      {(
        [
          ["conditions", "适用条件"],
          ["limitations", "结论局限"],
          ["evaluation_criteria", "判定标准"],
        ] as const
      ).map(([key, label]) => (
        <label key={key} className="block text-sm">
          {label}
          <Textarea
            aria-label={label}
            maxLength={12000}
            value={fields[key] ?? ""}
            disabled={busy}
            onChange={(e) => setFields({ ...fields, [key]: e.target.value })}
          />
        </label>
      ))}
      <EvidencePicker
        projectId={projectId}
        values={evidence}
        onChange={setEvidence}
        disabled={busy}
      />
      {error && <p role="alert">{error}</p>}
      <p className="text-xs text-[var(--muted)]">
        保存仅创建不可变候选版本；不调用AI，不运行科研代码。科学判断须本人在详情中独立审阅。
      </p>
      <div className="flex gap-2">
        <Button type="submit" disabled={busy}>
          {busy ? "保存中…" : base ? "保存主张新版本" : "保存科研主张"}
        </Button>
        <Button
          type="button"
          variant="ghost"
          disabled={busy}
          onClick={onCancel}
        >
          收起编辑
        </Button>
      </div>
    </form>
  );
}
