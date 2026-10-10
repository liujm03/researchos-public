"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SectionEditor } from "./sections";
import { PublicationSources } from "./sources";
import { PublicationBindings } from "./bindings";
import {
  blank,
  fields,
  message,
  type Revision,
  type Fields,
  type Preview,
  type Bundle,
} from "./types";
export function PublicationEditor({
  projectId,
  base,
  busy,
  onSave,
  onCancel,
}: {
  projectId: string;
  base: Revision | null;
  busy: boolean;
  onSave: (value: Fields, preview: Preview, ack: boolean) => Promise<void>;
  onCancel: () => void;
}) {
  const [value, setValue] = useState<Fields>(base ? fields(base) : blank()),
    [details, setDetails] = useState<Bundle[]>(base?.source_details ?? []),
    [preview, setPreview] = useState<Preview | null>(null),
    [loading, setLoading] = useState(false),
    [error, setError] = useState(""),
    [ack, setAck] = useState(false);
  function change(next: Fields) {
    const changedBundles = new Set(
      [...value.sources, ...next.sources]
        .filter((source) => {
          const before = value.sources.find(
              (s) => s.bundle_id === source.bundle_id,
            ),
            after = next.sources.find((s) => s.bundle_id === source.bundle_id);
          return (
            !before ||
            !after ||
            before.expected_bundle_sha256 !== after.expected_bundle_sha256
          );
        })
        .map((source) => source.bundle_id),
    );
    setValue({
      ...next,
      bindings: next.bindings.map((binding) => {
        const before = value.sections.find(
          (s) => s.key === binding.section_key,
        );
        const after = next.sections.find((s) => s.key === binding.section_key);
        return changedBundles.has(binding.bundle_id) ||
          before?.markdown !== after?.markdown
          ? {
              ...binding,
              format_check: "UNCHECKED",
              metadata_check: "UNCHECKED",
              support_check: "UNCHECKED",
            }
          : binding;
      }),
    });
    setPreview(null);
    setAck(false);
  }
  async function inspect() {
    setLoading(true);
    setError("");
    try {
      const checked = await api.post<Preview>(
        `/projects/${projectId}/publications/preview`,
        value,
      );
      setPreview(checked);
      setDetails(checked.source_details);
    } catch (cause) {
      setError(message(cause));
    } finally {
      setLoading(false);
    }
  }
  return (
    <section className="space-y-5" aria-label="论文版本编辑">
      <h2 className="font-semibold">
        {base ? `修订论文 · 基于版本 ${base.revision}` : "创建论文工作区"}
      </h2>
      {base && (
        <p className="text-xs text-[var(--muted)]">
          原版本与本人标注仍保留在历史。修改绑定章节正文或证据来源时，这些绑定的三层检查会重置为未检查，请重新核对原句段。
        </p>
      )}
      <div className="grid gap-3 md:grid-cols-3">
        <label>
          论文题目
          <Input
            aria-label="论文题目"
            disabled={busy || loading}
            required
            value={value.title}
            onChange={(e) => change({ ...value, title: e.target.value })}
          />
        </label>
        <label>
          目标会议或期刊
          <Input
            aria-label="目标会议或期刊"
            disabled={busy || loading}
            value={value.target_venue}
            onChange={(e) => change({ ...value, target_venue: e.target.value })}
          />
        </label>
        <label>
          写作阶段
          <select
            aria-label="写作阶段"
            className="block w-full rounded border p-2"
            disabled={busy || loading}
            value={value.stage}
            onChange={(e) =>
              change({ ...value, stage: e.target.value as Fields["stage"] })
            }
          >
            {[
              ["DRAFT", "草稿"],
              ["INTERNAL_REVIEW", "内部审阅"],
              ["REVISING", "修订"],
              ["SUBMITTED", "已提交 · 本人记录"],
              ["MAJOR_REVISION", "大修 · 本人记录"],
              ["MINOR_REVISION", "小修 · 本人记录"],
              ["ACCEPTED", "已接收 · 本人记录"],
              ["PUBLISHED", "已发表 · 本人记录"],
              ["ARCHIVED", "归档"],
            ].map(([k, t]) => (
              <option key={k} value={k}>
                {t}
              </option>
            ))}
          </select>
        </label>
      </div>
      <p className="text-xs text-[var(--muted)]">
        投稿、修回、接收和发表阶段仅记录本人报告；系统不会自动投稿或把这一记录当作出版社回执。
      </p>
      <SectionEditor
        sections={value.sections}
        busy={busy || loading}
        onChange={(sections) => change({ ...value, sections })}
      />
      <PublicationSources
        projectId={projectId}
        sources={value.sources}
        details={details}
        busy={busy || loading}
        onChange={(sources, nextDetails) => {
          setDetails(nextDetails);
          change({ ...value, sources });
        }}
      />
      <PublicationBindings
        value={value}
        details={details}
        busy={busy || loading}
        onChange={(bindings) => change({ ...value, bindings })}
      />
      {error && <p role="alert">{error}</p>}
      {preview && (
        <div className="rounded border p-3 text-sm" aria-label="论文保存预览">
          <p className="break-all">预览 SHA-256：{preview.preview_sha256}</p>
          <ul className="my-2 list-disc pl-5">
            {preview.gaps.map((g, i) => (
              <li key={i}>{g}</li>
            ))}
          </ul>
          <label className="flex gap-2">
            <input
              type="checkbox"
              checked={ack}
              disabled={busy}
              onChange={(e) => setAck(e.target.checked)}
            />
            我已核对当前缺口、全部绑定原句段与三层检查标注，保存为本人论文草稿版本
          </label>
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        <Button
          variant="secondary"
          disabled={busy || loading || !value.title.trim()}
          onClick={() => void inspect()}
        >
          {loading ? "核查中…" : "预览论文版本"}
        </Button>
        <Button
          disabled={busy || loading || !preview || !ack}
          onClick={() => preview && void onSave(value, preview, ack)}
        >
          保存论文版本
        </Button>
        <Button variant="ghost" disabled={busy || loading} onClick={onCancel}>
          取消编辑
        </Button>
      </div>
    </section>
  );
}
