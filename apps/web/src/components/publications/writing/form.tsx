"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/input";
import { MarkdownViewer } from "@/components/markdown/markdown-viewer";
import { message, type Revision } from "../types";
import type { Options, Selection, Preview } from "./types";
export function WritingForm({
  endpoint,
  revision,
  options,
  busy,
  onCreate,
}: {
  endpoint: string;
  revision: Revision;
  options: Options;
  busy: boolean;
  onCreate: (preview: Preview) => Promise<void>;
}) {
  const [profile, setProfile] = useState("tech-paper-template"),
    [target, setTarget] = useState(revision.sections[0]?.key ?? ""),
    [focus, setFocus] = useState(""),
    [style, setStyle] =
      useState<NonNullable<Selection["venue_style"]>>("GENERIC"),
    [bundles, setBundles] = useState<string[]>([]),
    [preview, setPreview] = useState<Preview | null>(null),
    [loading, setLoading] = useState(false),
    [error, setError] = useState(""),
    [approve, setApprove] = useState(false),
    [ack, setAck] = useState(false);
  function changed() {
    setPreview(null);
    setApprove(false);
    setAck(false);
  }
  const targetKind =
    profile === "tech-paper-template" ? "SKELETON" : "MANUSCRIPT";
  const validTargets = revision.sections.filter((s) => s.kind === targetKind);
  const actualTarget = validTargets.some((s) => s.key === target)
    ? target
    : (validTargets[0]?.key ?? "");
  async function inspect() {
    setLoading(true);
    setError("");
    try {
      const selection: Selection = {
        revision_id: revision.id,
        expected_revision_sha256: revision.sha256,
        profile: profile as Selection["profile"],
        target_section_key: actualTarget,
        focus,
        bundle_ids: bundles,
        output_language: "en",
        venue_style: style,
      };
      setPreview(await api.post<Preview>(`${endpoint}/preview`, selection));
    } catch (cause) {
      setError(message(cause));
    } finally {
      setLoading(false);
    }
  }
  return (
    <section className="space-y-3" aria-label="专业写作计划">
      <h3 className="font-medium">选择专业写作任务</h3>
      <p className="text-xs text-[var(--muted)]">
        预览冻结本版本章节、所选派生证据和真实 Skill
        资源。创建仅保存计划；本人再次启动才会发送云资料。写作不会替代科学审阅。
      </p>
      <div className="grid gap-3 md:grid-cols-2">
        <p className="text-sm">
          正文输出：<strong>English</strong> · 中文精读笔记保持本人模板
        </p>
        <label>
          目标写作风格
          <select
            aria-label="目标写作风格"
            className="block w-full rounded border p-2"
            disabled={busy || loading}
            value={style}
            onChange={(e) => {
              setStyle(e.target.value as NonNullable<Selection["venue_style"]>);
              changed();
            }}
          >
            {(options.styles ?? []).map((s) => (
              <option key={s.key} value={s.key} disabled={!s.available}>
                {s.label}
                {!s.available ? " · 暂不可用" : ""}
              </option>
            ))}
          </select>
          <span className="block text-xs text-[var(--muted)]">
            {(options.styles ?? []).find((s) => s.key === style)?.detail}
          </span>
        </label>
        <label>
          写作 Skill
          <select
            aria-label="写作 Skill"
            className="block w-full rounded border p-2"
            disabled={busy || loading}
            value={profile}
            onChange={(e) => {
              setProfile(e.target.value);
              changed();
            }}
          >
            {options.profiles.map((p) => (
              <option key={p.key} value={p.key}>
                {p.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          写作目标章节
          <select
            aria-label="写作目标章节"
            className="block w-full rounded border p-2"
            disabled={busy || loading}
            value={actualTarget}
            onChange={(e) => {
              setTarget(e.target.value);
              changed();
            }}
          >
            {validTargets.map((s) => (
              <option key={s.key} value={s.key}>
                {s.title} · {s.kind}
              </option>
            ))}
          </select>
        </label>
      </div>
      <label className="block">
        本人写作提示词
        <Textarea
          aria-label="本人写作提示词"
          disabled={busy || loading}
          rows={4}
          value={focus}
          onChange={(e) => {
            setFocus(e.target.value);
            changed();
          }}
        />
      </label>
      <fieldset className="space-y-2">
        <legend className="text-sm">明确选择可外发的证据包文本</legend>
        {!revision.source_details.length && (
          <p className="text-xs">
            这个版本没有证据包，可先编辑骨架，候选仍保留缺口。
          </p>
        )}
        {revision.source_details.map((b) => (
          <label key={b.id} className="flex gap-2 text-sm">
            <input
              type="checkbox"
              disabled={busy || loading}
              checked={bundles.includes(b.id)}
              onChange={(e) => {
                setBundles(
                  e.target.checked
                    ? [...bundles, b.id]
                    : bundles.filter((id) => id !== b.id),
                );
                changed();
              }}
            />
            {b.label} · {b.context_current ? "当前来源" : "来源变化"}
          </label>
        ))}
      </fieldset>
      <Button
        size="sm"
        variant="secondary"
        disabled={
          busy ||
          loading ||
          !actualTarget ||
          !options.enabled ||
          !(options.styles ?? []).some((s) => s.key === style && s.available)
        }
        onClick={() => void inspect()}
      >
        {loading ? "冻结预览中…" : "预览写作输入"}
      </Button>
      {error && <p role="alert">{error}</p>}
      {preview && (
        <section
          className="space-y-2 rounded border p-3"
          aria-label="冻结写作输入"
        >
          <p className="text-xs">
            Skill {preview.skill_key} / {preview.skill_version} ·{" "}
            {preview.model_key} / {preview.reasoning_effort} · 无执行工具
          </p>
          <p className="break-all text-xs">
            输入预览 SHA-256：{preview.preview_sha256}
          </p>
          <p className="text-xs">
            正文输出：English · 冻结风格：{preview.selection.venue_style}
            。写作指导不代表已满足投稿格式。
          </p>
          <p className="text-xs">
            冻结预算：
            {preview.budget_mode === "PROVIDER_QUOTA"
              ? "跟随 Codex 账户额度"
              : `本地单次上限 ${preview.max_tokens ?? "未配置"} Token`}{" "}
            · Provider {preview.provider_key}
          </p>
          <ul className="list-disc pl-5 text-xs">
            {preview.gaps.map((g, i) => (
              <li key={i}>{g}</li>
            ))}
          </ul>
          <details>
            <summary>核对将外发的完整输入</summary>
            <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-all text-xs">
              {JSON.stringify(preview.input_snapshot, null, 2)}
            </pre>
          </details>
          <details>
            <summary>
              核对实际 Skill 文件闭包 · {preview.skill_files.length} 个文件
            </summary>
            {preview.skill_files.map((f) => (
              <details key={f.path}>
                <summary className="break-all text-xs">
                  {f.path} · {f.sha256} · {f.size_bytes} 字节
                </summary>
                <MarkdownViewer content={f.content} label={`Skill ${f.path}`} />
              </details>
            ))}
          </details>
          <label className="flex gap-2 text-xs">
            <input
              type="checkbox"
              disabled={busy}
              checked={approve}
              onChange={(e) => setApprove(e.target.checked)}
            />
            批准本计划冻结资料发送到 Codex 云端
          </label>
          <label className="flex gap-2 text-xs">
            <input
              type="checkbox"
              disabled={busy}
              checked={ack}
              onChange={(e) => setAck(e.target.checked)}
            />
            我已核对写作输入、Skill 和当前缺口
          </label>
          <Button
            disabled={busy || !approve || !ack}
            onClick={() => void onCreate(preview)}
          >
            保存已批准写作计划
          </Button>
        </section>
      )}
    </section>
  );
}
