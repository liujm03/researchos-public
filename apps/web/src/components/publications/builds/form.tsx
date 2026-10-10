"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";
import { message, type Revision } from "../types";
import { BuildMaterials } from "./materials";
import type { Options, Selection, Preview } from "./types";
function official(value: string) {
  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) ? value : undefined;
  } catch {
    return undefined;
  }
}
export function BuildForm({
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
  const [value, setValue] = useState<Selection>({
      revision_id: revision.id,
      expected_revision_sha256: revision.sha256,
      template_key: "",
      variant: "",
      expected_template_manifest_sha256: "",
      font_profile: "ENGLISH",
      private_template_use_approved: false,
      submission_id: "",
      figures: [],
      tables: [],
      tex_overrides: [],
    }),
    [preview, setPreview] = useState<Preview | null>(null),
    [source, setSource] = useState<Preview | null>(null),
    [originalText, setOriginalText] = useState<Record<string, string>>({}),
    [file, setFile] = useState(""),
    [loading, setLoading] = useState(false),
    [error, setError] = useState(""),
    [approve, setApprove] = useState(false),
    [ack, setAck] = useState(false);
  const template = options.templates.find((t) => t.key === value.template_key),
    variant = template?.variants.find((v) => v.key === value.variant);
  const privateTemplate = template?.use_scope === "PRIVATE_AUTHOR_USE_ONLY";
  function available(t: Options["templates"][number]) {
    return (
      t.resource_status === "RESOURCE_AVAILABLE_NOT_VENUE_APPROVAL" ||
      (t.resource_status ===
        "PRIVATE_AUTHOR_RESOURCES_AVAILABLE_LICENSE_UNCONFIRMED" &&
        t.use_scope === "PRIVATE_AUTHOR_USE_ONLY")
    );
  }
  function change(next: Selection) {
    setValue(next);
    setPreview(null);
    setApprove(false);
    setAck(false);
  }
  async function inspect() {
    setLoading(true);
    setError("");
    try {
      const checked = await api.post<Preview>(`${endpoint}/preview`, value);
      setPreview(checked);
      setSource(checked);
      setOriginalText((previous) => ({
        ...previous,
        ...Object.fromEntries(
          checked.files
            .filter(
              (f) =>
                f.text_content !== null &&
                !value.tex_overrides.some((o) => o.path === f.path),
            )
            .map((f) => [f.path, f.text_content!]),
        ),
      }));
      setFile((current) =>
        checked.files.some((f) => f.path === current)
          ? current
          : (checked.files.find(
              (f) => editable(f.path) && f.text_content !== null,
            )?.path ?? ""),
      );
    } catch (cause) {
      setError(message(cause));
    } finally {
      setLoading(false);
    }
  }
  function editable(path: string) {
    return (
      path === "main.tex" ||
      /^sections\/[a-z][a-z0-9_]{0,63}\.tex$/.test(path) ||
      /^bibliography\/[a-z][a-z0-9_]{0,63}\.bib$/.test(path)
    );
  }
  const text = source?.files.find((f) => f.path === file),
    override = value.tex_overrides.find((f) => f.path === file);
  function edited(content: string) {
    const next = { path: file, content };
    change({
      ...value,
      tex_overrides: [
        ...value.tex_overrides.filter((f) => f.path !== file),
        next,
      ],
    });
  }
  return (
    <section className="space-y-4" aria-label="稿件构建设置">
      <h3 className="font-medium">选择模板与实际图表</h3>
      <p className="text-xs text-[var(--muted)]">
        English
        稿件；模板具体目标/年版本及匿名或最终模式由本人选择。构建只处理文档，不运行科研实验，不自动投稿。
      </p>
      <div className="grid gap-3 md:grid-cols-2">
        <label>
          文档模板
          <select
            aria-label="文档模板"
            className="block w-full rounded border p-2"
            disabled={busy || loading}
            value={value.template_key}
            onChange={(e) => {
              const selected = options.templates.find(
                (t) => t.key === e.target.value,
              );
              change({
                ...value,
                template_key: e.target.value,
                variant: "",
                expected_template_manifest_sha256:
                  selected?.manifest_sha256 ?? "",
                private_template_use_approved: false,
                submission_id: "",
                tex_overrides: [],
              });
              setSource(null);
              setOriginalText({});
            }}
          >
            <option value="">本人选择可用模板</option>
            {options.templates.map((t) => (
              <option key={t.key} value={t.key} disabled={!available(t)}>
                {t.family} · {t.version} ·{" "}
                {!available(t) ? "仅官方链接" : t.key}
              </option>
            ))}
          </select>
        </label>
        <label>
          模板模式
          <select
            aria-label="模板模式"
            className="block w-full rounded border p-2"
            disabled={busy || loading || !template}
            value={value.variant}
            onChange={(e) => {
              change({
                ...value,
                variant: e.target.value,
                tex_overrides: [],
                private_template_use_approved: false,
              });
              setSource(null);
              setOriginalText({});
            }}
          >
            <option value="">本人选择模式</option>
            {template?.variants.map((v) => (
              <option key={v.key} value={v.key}>
                {v.key} · {v.anonymous ? "匿名" : "非匿名"}
              </option>
            ))}
          </select>
        </label>
        <label>
          字体配置
          <select
            aria-label="字体配置"
            className="block w-full rounded border p-2"
            disabled={busy || loading}
            value={value.font_profile}
            onChange={(e) =>
              change({
                ...value,
                font_profile: e.target.value as Selection["font_profile"],
              })
            }
          >
            {(options.font_profiles ?? ["ENGLISH"]).map((f) => (
              <option key={f} value={f}>
                {f === "ENGLISH" ? "English 默认" : "兼容 CJK 字符"}
              </option>
            ))}
          </select>
        </label>
      </div>
      {template && (
        <div className="rounded border p-3 text-xs">
          <p>
            {template.family} · {template.version} · 许可 {template.license}
          </p>
          <p>{variant?.note ?? "尚未选择模式。"}</p>
          <p className="break-all">
            模板 manifest SHA：{template.manifest_sha256}
          </p>
          {official(template.official_url) && (
            <a
              className="text-[var(--accent)]"
              href={official(template.official_url)}
              target="_blank"
              rel="noopener noreferrer"
            >
              查看模板官方来源 ↗
            </a>
          )}
        </div>
      )}
      {privateTemplate && (
        <section
          className="space-y-2 rounded border p-3 text-xs"
          aria-label="私有作者模板使用"
        >
          <p>
            {template?.family} / {template?.version}
            作者资源仅用于本人私有稿件；再分发许可尚未确认。REVIEW/FINAL
            由本人选择，年份不会自动替换，构建不会公开资源或自动提交。
          </p>
          {value.variant === "REVIEW" && (
            <p>
              匿名审稿模式中的论文编号需本人核对；模板占位编号不代表实际投稿编号。
            </p>
          )}
          {value.variant === "REVIEW" && (
            <label className="block space-y-1">
              实际投稿编号（尚未投稿可留空）
              <Input
                aria-label="实际投稿编号"
                disabled={busy || loading}
                value={value.submission_id}
                onChange={(e) =>
                  change({ ...value, submission_id: e.target.value })
                }
              />
            </label>
          )}
          <label className="flex gap-2">
            <input
              type="checkbox"
              checked={value.private_template_use_approved}
              disabled={busy || loading || !value.variant}
              onChange={(e) =>
                change({
                  ...value,
                  private_template_use_approved: e.target.checked,
                })
              }
            />
            仅用于本人作者私有稿件，理解再分发许可未确认，不公开模板资源且不自动投稿
          </label>
        </section>
      )}
      <details>
        <summary className="text-sm">全部模板官方链接与可用性</summary>
        {options.templates.map((t) => (
          <p className="text-xs" key={t.key}>
            {t.family} · {t.version} · {t.resource_status}{" "}
            {official(t.official_url) && (
              <a
                href={official(t.official_url)}
                className="text-[var(--accent)]"
                target="_blank"
                rel="noopener noreferrer"
              >
                官方链接 ↗
              </a>
            )}
          </p>
        ))}
      </details>
      <p className="text-xs">
        受限编译：{options.compiler.available ? "可用" : "不可用"} ·{" "}
        {options.compiler.reason} · 固定镜像{" "}
        {options.compiler.image_id ?? "未知"}
      </p>
      <p className="text-xs">
        固定引擎：{options.compiler.engine} · 隔离合同：
        {options.compiler.isolation_contract} · 模板模式参数：
        {variant?.options.join(", ") ?? "待本人选择"}
      </p>
      <BuildMaterials
        endpoint={endpoint}
        projectId={revision.project_id}
        value={value}
        busy={busy || loading}
        onChange={change}
      />
      {source && (
        <section
          className="space-y-2 rounded border p-3"
          aria-label="可编辑构建源码"
        >
          <h4 className="font-medium">预览源码的有界修改</h4>
          <p className="text-xs">
            仅允许 main.tex、sections/*.tex 与
            bibliography/*.bib；图附件、模板与来源清单保留原始
            SHA。修改后需要重新预览。
          </p>
          <select
            aria-label="编辑源文件"
            className="block w-full rounded border p-2"
            value={file}
            disabled={busy || loading}
            onChange={(e) => setFile(e.target.value)}
          >
            {source.files
              .filter((f) => editable(f.path) && f.text_content !== null)
              .map((f) => (
                <option key={f.path} value={f.path}>
                  {f.path}
                </option>
              ))}
          </select>
          {text && (
            <Textarea
              aria-label={`源码 ${file}`}
              rows={12}
              disabled={busy || loading}
              value={
                override?.content ??
                originalText[file] ??
                text.text_content ??
                ""
              }
              onChange={(e) => edited(e.target.value)}
            />
          )}
          <Button
            size="sm"
            variant="ghost"
            disabled={busy || loading || !override}
            onClick={() =>
              change({
                ...value,
                tex_overrides: value.tex_overrides.filter(
                  (f) => f.path !== file,
                ),
              })
            }
          >
            恢复所选文件原文
          </Button>
        </section>
      )}
      <Button
        variant="secondary"
        disabled={
          busy ||
          loading ||
          !template ||
          !variant ||
          (privateTemplate && !value.private_template_use_approved) ||
          !options.enabled ||
          !options.compiler.available
        }
        onClick={() => void inspect()}
      >
        {loading ? "生成源码预览中…" : "预览源码与编译计划"}
      </Button>
      {error && <p role="alert">{error}</p>}
      {preview && (
        <section
          className="space-y-2 rounded border p-3"
          aria-label="冻结构建预览"
        >
          <p className="break-all text-xs">
            预览 SHA：{preview.preview_sha256}
            <br />
            完整源码 SHA：{preview.source_sha256}
            <br />
            实际输入 ZIP SHA：{preview.input_source_zip_sha256}
            <br />
            编译输入 SHA：{preview.compile_source_sha256}
            <br />
            编译器 manifest SHA：{preview.compiler_manifest_sha256}
          </p>
          <p className="text-xs">
            实际图附件字节包含：
            {preview.source_artifact_bytes_included ? "是" : "否"} ·
            准备编译不等于已产生 PDF 或科学结论。
          </p>
          <ul className="list-disc pl-5 text-xs">
            {preview.gaps.map((g, i) => (
              <li key={i}>{g}</li>
            ))}
          </ul>
          <details>
            <summary>核对所有冻结源文件及 SHA</summary>
            {preview.files.map((f) => (
              <details key={f.path}>
                <summary className="break-all text-xs">
                  {f.path} · {f.sha256} · {f.size_bytes} 字节
                </summary>
                {f.text_content !== null ? (
                  <pre className="max-h-72 overflow-auto whitespace-pre-wrap text-xs">
                    {f.text_content}
                  </pre>
                ) : (
                  <p className="text-xs">
                    实际二进制来源；不以文本代替附件字节。
                  </p>
                )}
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
            批准这份冻结源码进入受限文档编译队列
          </label>
          <label className="flex gap-2 text-xs">
            <input
              type="checkbox"
              disabled={busy}
              checked={ack}
              onChange={(e) => setAck(e.target.checked)}
            />
            我已核对模板模式、源文件、图表协议与当前缺口
          </label>
          <Button
            disabled={busy || !approve || !ack}
            onClick={() => void onCreate(preview)}
          >
            批准并构建文档
          </Button>
        </section>
      )}
    </section>
  );
}
