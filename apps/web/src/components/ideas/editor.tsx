"use client";
import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";
import { Card, CardHeader, CardContent } from "@/components/ui/card";
import type { Project } from "@/lib/api";
import { IdeaSourcePicker } from "./source-picker";
import {
  detailFields,
  statuses,
  type Fields,
  type Create,
  type Revision,
  type Source,
} from "./types";

export function IdeaEditor({
  base,
  initial,
  projects,
  projectId,
  busy,
  onSave,
  onCancel,
}: {
  base: Revision | null;
  initial?: Create | null;
  projects: Project[];
  projectId: string;
  busy: boolean;
  onSave: (
    fields: Fields,
    projectId: string,
    sources: Source[],
  ) => Promise<void>;
  onCancel: () => void;
}) {
  const [fields, setFields] = useState<Fields>(() => ({
    title: base?.title ?? initial?.title ?? "",
    content: base?.content ?? initial?.content ?? "",
    status: base?.status ?? initial?.status ?? "INBOX",
    ...Object.fromEntries(
      detailFields.map(([key]) => [key, base?.[key] ?? initial?.[key] ?? null]),
    ),
  }));
  const [tagText, setTagText] = useState(
    (base?.tags ?? initial?.tags ?? []).join(", "),
  );
  const [target, setTarget] = useState(initial?.project_id ?? projectId);
  const [sources, setSources] = useState<Source[]>(
    () =>
      base?.sources.map((source) => ({
        canonical_note_id: source.canonical_note_id,
        expected_note_sha256: source.note_sha256,
        start_offset: source.start_offset,
        end_offset: source.end_offset,
        exact_quote: source.exact_quote,
      })) ??
      initial?.sources ??
      [],
  );
  const [localError, setLocalError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setLocalError("");
    if (!fields.title.trim()) {
      setLocalError("请输入灵感标题");
      return;
    }
    const tags = [
      ...new Set(
        tagText
          .split(/[,，]/)
          .map((value) => value.trim())
          .filter(Boolean),
      ),
    ];
    if (tags.length > 20 || tags.some((value) => value.length > 100)) {
      setLocalError("最多 20 个标签，每个最多 100 字符。");
      return;
    }
    await onSave({ ...fields, tags }, target, sources);
  }
  return (
    <Card>
      <CardHeader>
        <h2 className="font-semibold">
          {base ? `更新灵感 · 基于版本 ${base.revision}` : "记录科研灵感"}
        </h2>
      </CardHeader>
      <CardContent>
        <form className="space-y-4" onSubmit={submit}>
          <label className="block space-y-1 text-sm">
            灵感标题
            <Input
              required
              maxLength={320}
              value={fields.title}
              disabled={busy}
              onChange={(event) =>
                setFields({ ...fields, title: event.target.value })
              }
            />
          </label>
          <label className="block space-y-1 text-sm">
            灵感内容（Markdown）
            <Textarea
              maxLength={40000}
              aria-label="灵感内容（Markdown）"
              className="min-h-36"
              value={fields.content ?? ""}
              disabled={busy}
              onChange={(event) =>
                setFields({ ...fields, content: event.target.value })
              }
              placeholder="先记下来，问题、方法和依据可以稍后完善。"
            />
          </label>
          <label className="block space-y-1 text-sm">
            标签（逗号分隔）
            <Input
              value={tagText}
              disabled={busy}
              onChange={(event) => setTagText(event.target.value)}
              placeholder="Multimodal, Wildfire"
            />
          </label>
          <div className="grid gap-3 sm:grid-cols-2">
            {!base && (
              <label className="space-y-1 text-sm">
                主课题
                <select
                  aria-label="灵感主课题"
                  className="h-9 w-full rounded border bg-[var(--background)] px-2"
                  value={target}
                  disabled={busy}
                  onChange={(event) => setTarget(event.target.value)}
                >
                  <option value="">暂不指定主课题</option>
                  {projects.map((project) => (
                    <option key={project.id} value={project.id}>
                      {project.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <label className="space-y-1 text-sm">
              灵感状态
              <select
                aria-label="灵感状态"
                className="h-9 w-full rounded border bg-[var(--background)] px-2"
                value={fields.status}
                disabled={busy}
                onChange={(event) =>
                  setFields({
                    ...fields,
                    status: event.target.value as Fields["status"],
                  })
                }
              >
                {statuses.map(([key, label]) => (
                  <option key={key} value={key}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <details>
            <summary className="cursor-pointer text-sm">
              完善问题、方法、资源与决策
            </summary>
            <div className="mt-3 grid gap-3 lg:grid-cols-2">
              {detailFields.map(([key, label]) => (
                <label key={key} className="space-y-1 text-sm">
                  {label}
                  <Textarea
                    disabled={busy}
                    maxLength={
                      ["difficulty", "novelty", "feasibility"].includes(key)
                        ? 4000
                        : 12000
                    }
                    value={fields[key] ?? ""}
                    onChange={(event) =>
                      setFields({
                        ...fields,
                        [key]: event.target.value || null,
                      })
                    }
                  />
                </label>
              ))}
            </div>
          </details>
          <IdeaSourcePicker
            selections={sources}
            onChange={setSources}
            disabled={busy}
          />
          {base && (
            <p className="break-all text-xs text-[var(--muted)]">
              本次更新以原版本 SHA {base.sha256}{" "}
              为基准；并发冲突不会覆盖这里的输入。
            </p>
          )}
          <p className="text-xs text-[var(--muted)]">
            状态与新颖性为本人判断；保存只记录本地灵感与所选笔记摘录，不调用
            AI。
          </p>
          {localError && (
            <p role="alert" className="text-sm text-[var(--danger)]">
              {localError}
            </p>
          )}
          <div className="flex gap-2">
            <Button type="submit" disabled={busy}>
              {busy ? "保存中…" : base ? "保存新版本" : "保存灵感"}
            </Button>
            <Button
              type="button"
              variant="ghost"
              disabled={busy}
              onClick={onCancel}
            >
              取消编辑
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
