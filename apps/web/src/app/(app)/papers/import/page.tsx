"use client";

import Link from "next/link";
import { useState, type ChangeEvent, type FormEvent } from "react";
import { ArrowLeft, CheckCircle2, FileUp } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Textarea } from "@/components/ui/input";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { api } from "@/lib/api";
import type { components } from "@/lib/generated";

type PreviewRequest = components["schemas"]["ImportPreviewRequest"];
type ConfirmRequest = components["schemas"]["ImportConfirmRequest"];
type BibliographyFormat = PreviewRequest["format"];
type CandidateStatus = components["schemas"]["ImportRecordOut"]["status"];
type PreviewResult = components["schemas"]["ImportPreviewOut"];
type ConfirmResult = components["schemas"]["ImportConfirmOut"];

const statusLabel: Record<CandidateStatus, string> = {
  new: "新论文",
  existing_doi: "DOI 已收录，将关联现有论文",
  existing_arxiv: "arXiv ID 已收录，将关联现有论文",
  already_linked: "已经导入",
  possible_duplicate: "可能重复，需人工核对",
  duplicate_in_batch: "本批次中重复",
  conflict: "元数据冲突，需人工核对",
  invalid: "记录无效",
};
const MAX_FILE_BYTES = 1024 * 1024;

function isSelectable(status: CandidateStatus) {
  return status === "new" || status === "existing_doi" || status === "existing_arxiv";
}

export default function BibliographyImportPage() {
  const [format, setFormat] = useState<BibliographyFormat>("bibtex");
  const [content, setContent] = useState("");
  const [fileName, setFileName] = useState("");
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [result, setResult] = useState<ConfirmResult | null>(null);
  const [busy, setBusy] = useState<"file" | "preview" | "confirm" | null>(null);
  const [error, setError] = useState("");

  function updateInput(nextContent: string, nextFormat = format, nextFileName = "") {
    setContent(nextContent);
    setFormat(nextFormat);
    setFileName(nextFileName);
    setPreview(null);
    setSelected([]);
    setResult(null);
    setError("");
  }

  async function readFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setPreview(null);
    setSelected([]);
    setResult(null);
    const extension = file.name.toLowerCase().split(".").pop();
    if (extension !== "bib" && extension !== "ris") {
      setError("请选择 .bib 或 .ris 文本文件。");
      return;
    }
    if (file.size > MAX_FILE_BYTES) {
      setError("文件超过 1 MB。请分成较小的批次再导入。");
      return;
    }
    setBusy("file");
    setError("");
    try {
      const text = new TextDecoder("utf-8", { fatal: true }).decode(await file.arrayBuffer());
      updateInput(text.replace(/^\uFEFF/, ""), extension === "bib" ? "bibtex" : "ris", file.name);
    } catch {
      setError("无法读取所选文件，请确认它是 UTF-8 编码的文本文件。");
    } finally {
      setBusy(null);
    }
  }

  async function requestPreview(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPreview(null);
    setSelected([]);
    setResult(null);
    setError("");
    if (!content.trim()) {
      setError("请粘贴文献记录或选择文件。");
      return;
    }
    if (new TextEncoder().encode(content).byteLength > MAX_FILE_BYTES) {
      setError("内容超过 1 MB。请分成较小的批次再导入。");
      return;
    }
    setBusy("preview");
    try {
      const request: PreviewRequest = { format, content };
      const data = await api.post<PreviewResult>("/bibliography-imports/preview", request);
      setPreview(data);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "预览失败，请检查文件格式后重试。");
    } finally {
      setBusy(null);
    }
  }

  function toggle(sourceKey: string) {
    setSelected((previous) => previous.includes(sourceKey)
      ? previous.filter((key) => key !== sourceKey)
      : [...previous, sourceKey]);
  }

  async function confirm() {
    if (!preview || !selected.length || busy) return;
    setBusy("confirm");
    setError("");
    try {
      const request: ConfirmRequest = {
        format,
        content,
        input_sha256: preview.input_sha256,
        selections: preview.records.filter((record) => isSelectable(record.status) && selected.includes(record.source_key)).map((record) => ({
          source_key: record.source_key,
          expected_status: record.status,
          existing_paper_id: record.existing_paper_id,
        })),
      };
      const data = await api.post<ConfirmResult>("/bibliography-imports/confirm", request);
      setResult(data);
      setSelected([]);
      setPreview(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "导入失败，请重新预览后重试。");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <Link href="/papers" className="inline-flex items-center gap-1 text-sm text-[var(--muted)] hover:text-[var(--foreground)]"><ArrowLeft className="h-4 w-4" />返回文献中心</Link>
        <p className="mb-1 mt-5 text-xs font-medium uppercase tracking-[0.18em] text-[var(--accent)]">Literature hub</p>
        <h1 className="text-2xl font-semibold">导入 BibTeX / RIS</h1>
        <p className="mt-1 text-sm text-[var(--muted)]">先预览与核对候选，再选择要写入的记录。可能重复的条目需要单独核对。</p>
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-2 text-xs text-[var(--accent)]"><Link href="/papers/import/doi" className="underline">通过 DOI 查询 Crossref 元数据</Link><Link href="/papers/import/arxiv" className="underline">通过 arXiv ID 查询预印本元数据</Link></div>
      </div>

      <Card>
        <CardHeader><h2 className="font-semibold">导入内容</h2></CardHeader>
        <CardContent>
          <form onSubmit={requestPreview} className="space-y-4">
            <div className="flex flex-wrap items-end gap-4">
              <label className="space-y-1.5 text-xs font-medium">格式
                <select value={format} onChange={(event) => updateInput(content, event.target.value as BibliographyFormat)} disabled={!!busy} className="block h-9 min-w-36 rounded-md border border-[var(--border)] bg-[var(--background)] px-3 text-sm">
                  <option value="bibtex">BibTeX (.bib)</option><option value="ris">RIS (.ris)</option>
                </select>
              </label>
              <label className="inline-flex h-9 cursor-pointer items-center gap-2 rounded-md border border-[var(--border)] bg-[var(--surface)] px-3.5 text-sm hover:bg-[var(--surface-hover)]">
                <FileUp className="h-4 w-4" />选择本地文件
                <input type="file" accept=".bib,.ris,text/plain" onChange={readFile} disabled={!!busy} className="sr-only" />
              </label>
              {fileName && <span className="text-xs text-[var(--muted)]">已读取：{fileName}</span>}
            </div>
            <label className="block space-y-1.5 text-xs font-medium">BibTeX 或 RIS 文本
              <Textarea value={content} onChange={(event) => updateInput(event.target.value, format)} disabled={!!busy} rows={10} className="font-mono text-xs" placeholder={format === "bibtex" ? "@article{key,\n  title = {Paper title},\n  author = {Author A and Author B}\n}" : "TY  - JOUR\nTI  - Paper title\nAU  - Author A\nER  -"} />
            </label>
            <div className="flex items-center gap-3"><Button type="submit" disabled={!!busy || !content.trim()}>{busy === "preview" ? "解析中…" : "预览候选"}</Button><span className="text-xs text-[var(--muted)]">每批最多 1 MB；预览不会写入文献库。</span></div>
          </form>
        </CardContent>
      </Card>

      {busy === "file" && <LoadingState label="正在读取本地文件…" />}
      {error && <ErrorState message={error} />}
      {result && <Card><CardContent className="space-y-3 py-5"><div className="flex items-center gap-2 font-medium"><CheckCircle2 className="h-5 w-5 text-[var(--accent)]" />导入完成</div><p className="text-sm text-[var(--muted)]">新建 {result.created.length} 篇，关联已收录论文 {result.linked.length} 篇，跳过 {result.skipped.length} 篇。</p><div className="flex flex-wrap gap-2">{[...new Set([...result.created, ...result.linked])].map((id) => <Link key={id} href={`/papers/${id}`} className="text-sm text-[var(--accent)] underline">查看论文 {id.slice(0, 8)}</Link>)}</div><Button variant="secondary" onClick={() => updateInput("", format)} type="button">继续导入</Button></CardContent></Card>}

      {preview && <Card>
        <CardHeader><div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="font-semibold">预览结果</h2><p className="mt-1 text-xs text-[var(--muted)]">共 {preview.records.length} 条；勾选后才会写入。修改输入会清除本次预览。</p></div><Button type="button" disabled={!selected.length || !!busy} onClick={confirm}>{busy === "confirm" ? "导入中…" : `确认导入 ${selected.length} 条`}</Button></div></CardHeader>
        <CardContent>
          {preview.records.length === 0 ? <EmptyState title="未识别到记录" detail="检查格式与文本内容，再次预览。" /> : <div className="divide-y divide-[var(--border)]">
            {preview.records.map((record, index) => {
              const selectable = isSelectable(record.status);
              return <div key={`${record.source_key}-${index}`} className="flex gap-3 py-4">
                <input type="checkbox" checked={selected.includes(record.source_key)} disabled={!selectable || !!busy} onChange={() => toggle(record.source_key)} aria-label={`导入 ${record.title || record.source_key}`} className="mt-1 h-4 w-4 accent-[var(--accent)]" />
                <div className="min-w-0 space-y-1 text-sm">
                  <div className="font-medium">{record.title || "标题缺失"}</div>
                  <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-[var(--muted)]"><span>键：{record.key || `${record.source_key.slice(0, 16)}…`}</span><span>{record.authors.join(", ") || "作者未知"}</span><span>{record.year ?? "年份未知"}</span><span>{record.venue || "来源未知"}</span>{record.doi && <span>DOI: {record.doi}</span>}{record.arxiv_id && <span>arXiv: {record.arxiv_id}</span>}</div>
                  <p className={selectable ? "text-xs text-[var(--accent)]" : "text-xs text-amber-600"}>{statusLabel[record.status]}</p>
                  {record.warning && <p className="text-xs text-amber-600">{record.warning}</p>}
                  {record.existing_paper_id && <Link href={`/papers/${record.existing_paper_id}`} className="inline-block text-xs text-[var(--accent)] underline">查看已有论文</Link>}
                </div>
              </div>;
            })}
          </div>}
        </CardContent>
      </Card>}
    </div>
  );
}
