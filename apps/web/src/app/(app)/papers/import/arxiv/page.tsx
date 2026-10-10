"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { ArrowLeft, ArrowUpRight, CheckCircle2, Search } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import {
  api,
  ApiError,
  type ArxivConfirm,
  type ArxivConfirmRequest,
  type ArxivPreview,
  type ArxivPreviewRequest,
} from "@/lib/api";

type ArxivStatus = ArxivPreview["status"];

const statusLabel: Record<ArxivStatus, string> = {
  new: "新论文，确认后建立文献记录",
  existing_doi: "DOI 已收录，确认后关联这个 arXiv 版本",
  existing_arxiv: "arXiv ID 已收录，确认后关联这个来源版本",
  already_linked: "这个 arXiv 来源版本已关联，无需重复导入",
  possible_duplicate: "标题与年份可能重复，需先人工核对",
  conflict: "来源身份与已有论文冲突，需先人工核对",
  invalid: "来源元数据不足，无法导入",
};

function canConfirm(status: ArxivStatus) {
  return (
    status === "new" || status === "existing_doi" || status === "existing_arxiv"
  );
}

function sourceDate(value: string | null) {
  if (!value) return "来源未提供";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN");
}

function isArxivUrl(value: string) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && url.hostname === "arxiv.org";
  } catch {
    return false;
  }
}

export default function ArxivImportPage() {
  const [arxivId, setArxivId] = useState("");
  const [preview, setPreview] = useState<ArxivPreview | null>(null);
  const [result, setResult] = useState<ArxivConfirm | null>(null);
  const [busy, setBusy] = useState<"preview" | "confirm" | null>(null);
  const [error, setError] = useState("");
  const [notFound, setNotFound] = useState(false);

  function updateInput(value: string) {
    setArxivId(value);
    setPreview(null);
    setResult(null);
    setError("");
    setNotFound(false);
  }

  async function requestPreview(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setPreview(null);
    setResult(null);
    setError("");
    setNotFound(false);
    const input = arxivId.trim();
    if (!input) {
      setError("请输入 arXiv ID 或 arxiv.org 论文链接。");
      return;
    }
    setBusy("preview");
    try {
      const request: ArxivPreviewRequest = { arxiv_id: input };
      setPreview(
        await api.post<ArxivPreview>(
          "/literature/import/arxiv/preview",
          request,
        ),
      );
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 404) setNotFound(true);
      else
        setError(
          cause instanceof Error
            ? cause.message
            : "无法查询 arXiv，请稍后重试。",
        );
    } finally {
      setBusy(null);
    }
  }

  async function confirm() {
    if (!preview || !canConfirm(preview.status) || busy) return;
    setBusy("confirm");
    setError("");
    try {
      const request: ArxivConfirmRequest = {
        arxiv_id: preview.versioned_id,
        expected_version: preview.source_version,
        expected_hash: preview.source_hash,
        expected_status: preview.status,
        existing_paper_id: preview.existing_paper_id,
      };
      setResult(
        await api.post<ArxivConfirm>(
          "/literature/import/arxiv/confirm",
          request,
        ),
      );
      setPreview(null);
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 409) {
        setPreview(null);
        setError(
          "来源信息或文献库状态已变化。请重新点击“查询并预览”，核对新候选后再确认。",
        );
      } else {
        setError(
          cause instanceof Error
            ? cause.message
            : "确认失败，请重新查询并核对候选。",
        );
      }
    } finally {
      setBusy(null);
    }
  }

  const savedPaperId = result?.created ?? result?.linked ?? result?.skipped;

  return (
    <div className="space-y-6">
      <div>
        <Link
          href="/papers"
          className="inline-flex items-center gap-1 text-sm text-[var(--muted)] hover:text-[var(--foreground)]"
        >
          <ArrowLeft className="h-4 w-4" />
          返回文献中心
        </Link>
        <p className="mb-1 mt-5 text-xs font-medium uppercase tracking-[0.18em] text-[var(--accent)]">
          Literature hub
        </p>
        <h1 className="text-2xl font-semibold">通过 arXiv 导入</h1>
        <p className="mt-1 text-sm text-[var(--muted)]">
          核对公开元数据与来源版本，再确认建立或关联论文。你编辑过的论文信息会保留。
        </p>
      </div>

      <Card>
        <CardHeader>
          <h2 className="font-semibold">查询 arXiv ID</h2>
        </CardHeader>
        <CardContent>
          <form onSubmit={requestPreview} className="space-y-4">
            <label className="block max-w-2xl space-y-1.5 text-xs font-medium">
              arXiv ID 或论文链接
              <Input
                value={arxivId}
                onChange={(event) => updateInput(event.target.value)}
                disabled={!!busy}
                maxLength={512}
                placeholder="2401.01234v2 或 https://arxiv.org/abs/2401.01234"
                autoComplete="off"
                aria-describedby="arxiv-input-help"
              />
            </label>
            <p
              id="arxiv-input-help"
              className="text-xs leading-5 text-[var(--muted)]"
            >
              支持现代 ID（2401.01234）、带版本 ID（2401.01234v2）、旧式
              ID（cs/0701001）及 arxiv.org 的 abs / pdf
              链接。未指定版本时先查询当前版本，确认时固定预览中的版本。
            </p>
            <p className="text-xs leading-5 text-[var(--muted)]">
              点击“查询并预览”会将这个 ID 发送给 arXiv 官方
              API。确认时会再次核对同一版本的元数据；预览不会写入文献库。此操作只查询公开元数据，发送内容为
              arXiv ID，不上传或下载 PDF，也不发送你的笔记或项目。
            </p>
            <Button type="submit" disabled={!!busy || !arxivId.trim()}>
              <Search className="h-4 w-4" />
              {busy === "preview" ? "查询中…" : "查询并预览"}
            </Button>
          </form>
        </CardContent>
      </Card>

      {busy === "preview" && (
        <LoadingState label="正在查询 arXiv 公开元数据…" />
      )}
      {error && <ErrorState message={error} />}
      {notFound && (
        <Card>
          <EmptyState
            title="未找到这篇 arXiv 论文"
            detail="核对 ID 与版本号，再次查询。"
          />
        </Card>
      )}

      {result && (
        <Card>
          <CardContent className="space-y-3 py-5">
            <div role="status" className="flex items-center gap-2 font-medium">
              <CheckCircle2 className="h-5 w-5 text-[var(--accent)]" />
              {result.created
                ? "已导入论文"
                : result.linked
                  ? "已关联 arXiv 来源版本"
                  : "已收录，无需重复导入"}
            </div>
            {savedPaperId && (
              <Link
                href={`/papers/${savedPaperId}`}
                className="inline-flex items-center gap-1 text-sm text-[var(--accent)] underline"
              >
                查看论文
                <ArrowUpRight className="h-4 w-4" />
              </Link>
            )}
            <div>
              <Button
                type="button"
                variant="secondary"
                onClick={() => updateInput("")}
              >
                继续导入
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {preview && (
        <Card>
          <CardHeader>
            <div className="flex w-full flex-wrap items-start justify-between gap-3">
              <div>
                <h2 className="font-semibold">候选预览</h2>
                <p className="mt-1 text-xs text-[var(--muted)]">
                  来源：arXiv · {preview.versioned_id}
                </p>
              </div>
              {canConfirm(preview.status) && (
                <Button type="button" onClick={confirm} disabled={!!busy}>
                  {busy === "confirm" ? "确认中…" : "确认导入"}
                </Button>
              )}
            </div>
          </CardHeader>
          <CardContent className="space-y-5 text-sm">
            {preview.title ? (
              <div>
                <h3 className="text-base font-medium">{preview.title}</h3>
                <p className="mt-1 text-xs leading-5 text-[var(--muted)]">
                  {preview.authors.join(", ") || "作者未知"} ·{" "}
                  {preview.year ?? "年份未知"} ·{" "}
                  {preview.venue || "arXiv 预印本"}
                </p>
              </div>
            ) : (
              <EmptyState
                title="来源未提供标题"
                detail="这条元数据无法直接建立论文，请核对 ID。"
              />
            )}
            {preview.abstract ? (
              <div>
                <h3 className="mb-1 text-xs font-semibold">摘要</h3>
                <p className="whitespace-pre-wrap text-sm leading-6 text-[var(--muted)]">
                  {preview.abstract}
                </p>
              </div>
            ) : (
              <p className="text-xs text-[var(--muted)]">来源未提供摘要。</p>
            )}
            <dl className="grid gap-3 rounded-lg border border-[var(--border)] p-4 text-xs sm:grid-cols-2">
              <div>
                <dt className="text-[var(--muted)]">arXiv 基础 ID</dt>
                <dd className="mt-1 font-mono">{preview.arxiv_id}</dd>
              </div>
              <div>
                <dt className="text-[var(--muted)]">本次来源版本</dt>
                <dd className="mt-1 font-mono">
                  {preview.versioned_id} · v{preview.source_version}
                </dd>
              </div>
              <div>
                <dt className="text-[var(--muted)]">DOI</dt>
                <dd className="mt-1 break-all">
                  {preview.doi || "来源未提供"}
                </dd>
              </div>
              <div>
                <dt className="text-[var(--muted)]">来源更新时间</dt>
                <dd className="mt-1">
                  {sourceDate(preview.source_updated_at)}
                </dd>
              </div>
              <div className="sm:col-span-2">
                <dt className="text-[var(--muted)]">来源 SHA-256</dt>
                <dd className="mt-1 break-all font-mono">
                  {preview.source_hash}
                </dd>
              </div>
            </dl>
            <p
              role="status"
              className={
                canConfirm(preview.status) ||
                preview.status === "already_linked"
                  ? "text-xs text-[var(--accent)]"
                  : "text-xs text-amber-600"
              }
            >
              {statusLabel[preview.status]}
            </p>
            {preview.warning && (
              <p className="text-xs text-amber-600">{preview.warning}</p>
            )}
            {preview.existing_paper_id && (
              <Link
                href={`/papers/${preview.existing_paper_id}`}
                className="inline-flex items-center gap-1 text-xs text-[var(--accent)] underline"
              >
                查看已有论文
                <ArrowUpRight className="h-3 w-3" />
              </Link>
            )}
            {preview.url && isArxivUrl(preview.url) && (
              <p>
                <a
                  href={preview.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-xs text-[var(--accent)] underline"
                >
                  查看 arXiv 来源页面
                  <ArrowUpRight className="h-3 w-3" />
                </a>
              </p>
            )}
            {busy === "confirm" && (
              <LoadingState label="正在核对并保存来源版本…" />
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
