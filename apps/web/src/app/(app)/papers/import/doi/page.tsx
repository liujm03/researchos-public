"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { ArrowLeft, ArrowUpRight, CheckCircle2, Search } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { api } from "@/lib/api";
import type { components } from "@/lib/generated";

type DoiPreviewRequest = components["schemas"]["DoiPreviewRequest"];
type DoiPreview = components["schemas"]["DoiPreviewOut"];
type DoiConfirmRequest = components["schemas"]["DoiConfirmRequest"];
type DoiConfirm = components["schemas"]["DoiConfirmOut"];
type DoiStatus = DoiPreview["status"];

const statusLabel: Record<DoiStatus, string> = {
  new: "新论文，确认后建立文献记录",
  existing_doi: "DOI 已收录，确认后关联 Crossref 来源",
  already_linked: "这条 Crossref 来源已关联",
  possible_duplicate: "可能重复，需先人工核对",
  conflict: "来源身份与已有论文冲突，需先人工核对",
  invalid: "来源元数据不足，无法导入",
};

function canConfirm(status: DoiStatus) {
  return status === "new" || status === "existing_doi";
}

export default function DoiImportPage() {
  const [doi, setDoi] = useState("");
  const [preview, setPreview] = useState<DoiPreview | null>(null);
  const [result, setResult] = useState<DoiConfirm | null>(null);
  const [busy, setBusy] = useState<"preview" | "confirm" | null>(null);
  const [error, setError] = useState("");

  function updateDoi(value: string) {
    setDoi(value);
    setPreview(null);
    setResult(null);
    setError("");
  }

  async function requestPreview(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setPreview(null);
    setResult(null);
    setError("");
    const normalizedInput = doi.trim();
    if (!normalizedInput) {
      setError("请输入 DOI，例如 10.1109/TPAMI.2023.1234567。");
      return;
    }
    setBusy("preview");
    try {
      const request: DoiPreviewRequest = { doi: normalizedInput };
      const data = await api.post<DoiPreview>("/literature/import/doi/preview", request);
      setPreview(data);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "无法查询 DOI，请稍后重试。");
    } finally {
      setBusy(null);
    }
  }

  async function confirm() {
    if (!preview || !canConfirm(preview.status) || busy) return;
    setBusy("confirm");
    setError("");
    try {
      const request: DoiConfirmRequest = {
        doi: preview.doi,
        expected_hash: preview.source_hash,
        expected_status: preview.status,
        existing_paper_id: preview.existing_paper_id,
      };
      const data = await api.post<DoiConfirm>("/literature/import/doi/confirm", request);
      setResult(data);
      setPreview(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "确认失败；请重新查询并核对候选。");
      setPreview(null);
    } finally {
      setBusy(null);
    }
  }

  const savedPaperId = result?.created ?? result?.linked ?? result?.skipped;

  return (
    <div className="space-y-6">
      <div>
        <Link href="/papers" className="inline-flex items-center gap-1 text-sm text-[var(--muted)] hover:text-[var(--foreground)]"><ArrowLeft className="h-4 w-4" />返回文献中心</Link>
        <p className="mb-1 mt-5 text-xs font-medium uppercase tracking-[0.18em] text-[var(--accent)]">Literature hub</p>
        <h1 className="text-2xl font-semibold">通过 DOI 导入</h1>
        <p className="mt-1 text-sm text-[var(--muted)]">先查询开放元数据并核对候选，再决定是否写入文献库。来源资料不会覆盖你编辑过的论文信息。</p>
      </div>

      <Card>
        <CardHeader><h2 className="font-semibold">查询 DOI</h2></CardHeader>
        <CardContent>
          <form onSubmit={requestPreview} className="space-y-4">
            <label className="block max-w-2xl space-y-1.5 text-xs font-medium">DOI
              <Input value={doi} onChange={(event) => updateDoi(event.target.value)} disabled={!!busy} placeholder="10.xxxx/xxxxx 或 https://doi.org/10.xxxx/xxxxx" autoComplete="off" />
            </label>
            <p className="text-xs text-[var(--muted)]">点击“查询并预览”后，系统会将输入的 DOI 发送给 Crossref 查询公开元数据；确认导入时会再次核对来源是否变化。预览不会写入文献库；不会发送你的 PDF、笔记或项目内容。</p>
            <Button type="submit" disabled={!!busy || !doi.trim()}><Search className="h-4 w-4" />{busy === "preview" ? "查询中…" : "查询并预览"}</Button>
          </form>
        </CardContent>
      </Card>

      {busy === "preview" && <LoadingState label="正在查询 Crossref 公开元数据…" />}
      {error && <ErrorState message={error} />}

      {result && <Card><CardContent className="space-y-3 py-5">
        <div className="flex items-center gap-2 font-medium"><CheckCircle2 className="h-5 w-5 text-[var(--accent)]" />{result.created ? "已导入论文" : result.linked ? "已关联来源" : "已收录，无需重复导入"}</div>
        {savedPaperId && <Link href={`/papers/${savedPaperId}`} className="inline-flex items-center gap-1 text-sm text-[var(--accent)] underline">查看论文<ArrowUpRight className="h-4 w-4" /></Link>}
        <div><Button type="button" variant="secondary" onClick={() => updateDoi("")}>继续导入</Button></div>
      </CardContent></Card>}

      {preview && <Card>
        <CardHeader><div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="font-semibold">候选预览</h2><p className="mt-1 text-xs text-[var(--muted)]">来源：Crossref · DOI {preview.doi}</p></div>{canConfirm(preview.status) && <Button type="button" onClick={confirm} disabled={!!busy}>{busy === "confirm" ? "确认中…" : "确认导入"}</Button>}</div></CardHeader>
        <CardContent className="space-y-4 text-sm">
          {preview.title ? <div><h3 className="text-base font-medium">{preview.title}</h3><p className="mt-1 text-xs text-[var(--muted)]">{preview.authors.join(", ") || "作者未知"} · {preview.year ?? "年份未知"} · {preview.venue || "来源未知"}</p></div> : <EmptyState title="来源未提供标题" detail="这条元数据无法直接建立论文，请核对 DOI。" />}
          {preview.abstract && <div><h3 className="mb-1 text-xs font-semibold">摘要</h3><p className="whitespace-pre-wrap text-sm leading-6 text-[var(--muted)]">{preview.abstract}</p></div>}
          <p className={canConfirm(preview.status) ? "text-xs text-[var(--accent)]" : "text-xs text-amber-600"}>{statusLabel[preview.status]}</p>
          {preview.warning && <p className="text-xs text-amber-600">{preview.warning}</p>}
          {preview.existing_paper_id && <Link href={`/papers/${preview.existing_paper_id}`} className="inline-flex items-center gap-1 text-xs text-[var(--accent)] underline">查看已有论文<ArrowUpRight className="h-3 w-3" /></Link>}
          {preview.url && /^https?:\/\//i.test(preview.url) && <p><a href={preview.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-xs text-[var(--accent)] underline">查看来源页面<ArrowUpRight className="h-3 w-3" /></a></p>}
          {busy === "confirm" && <LoadingState label="正在保存论文来源…" />}
        </CardContent>
      </Card>}
    </div>
  );
}
