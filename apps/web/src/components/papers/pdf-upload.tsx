"use client";

import { useRef, useState, type FormEvent } from "react";
import { LoaderCircle, Upload } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError, api, type PdfUpload } from "@/lib/api";

type PdfUploadProps = {
  paperId: string;
  disabled: boolean;
  onUploadingChange: (uploading: boolean) => void;
  onUploaded: (result: PdfUpload) => Promise<void>;
};

function errorMessage(cause: unknown): string {
  if (cause instanceof ApiError) {
    if (cause.code === "FILE_TOO_LARGE")
      return `PDF 超过允许的上传大小。${cause.message}`;
    if (cause.code === "INVALID_PDF")
      return `文件未通过 PDF 校验。${cause.message}`;
    return cause.message;
  }
  if (cause instanceof TypeError)
    return "无法连接到平台。请检查连接后重试；相同 PDF 再次上传会复用已有记录。";
  return cause instanceof Error ? cause.message : "PDF 上传失败，请重试。";
}

export function PdfUploadForm({
  paperId,
  disabled,
  onUploadingChange,
  onUploaded,
}: PdfUploadProps) {
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file || uploading || disabled) return;
    setError("");
    setMessage("");
    if (
      !file.name.toLowerCase().endsWith(".pdf") ||
      (file.type && file.type !== "application/pdf")
    ) {
      setError("请选择 PDF 文件（.pdf）。");
      return;
    }
    if (!file.size) {
      setError("PDF 文件为空，请选择包含内容的文件。");
      return;
    }
    setUploading(true);
    onUploadingChange(true);
    try {
      const form = new FormData();
      // Some operating systems omit MIME for a .pdf file; server signature checks remain authoritative.
      form.set(
        "file",
        file.type
          ? file
          : new File([file], file.name, { type: "application/pdf" }),
      );
      const result = await api.postForm<PdfUpload>(
        `/papers/${paperId}/pdf`,
        form,
      );
      setMessage(
        result.duplicate
          ? "相同 PDF 已保存，已复用已有附件与解析任务。下方显示该文件和任务状态。"
          : "PDF 已保存到本机，解析任务已创建。下方显示该文件和任务状态。",
      );
      setFile(null);
      if (input.current) input.current.value = "";
      await onUploaded(result);
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setUploading(false);
      onUploadingChange(false);
    }
  }

  return (
    <form
      onSubmit={submit}
      className="space-y-3 rounded-md border border-[var(--border)] p-3"
      aria-busy={uploading}
    >
      <div>
        <label htmlFor="paper-pdf-upload" className="text-sm font-medium">
          上传原始 PDF
        </label>
        <p className="mt-1 text-xs leading-5 text-[var(--muted)]">
          文件保存到本机后，可主动提交原始 PDF 精读。后台文本索引与精读独立。
        </p>
      </div>
      <Input
        ref={input}
        id="paper-pdf-upload"
        name="file"
        type="file"
        accept="application/pdf,.pdf"
        disabled={disabled || uploading}
        className="h-auto py-2 text-xs file:mr-3 file:rounded file:border-0 file:bg-[var(--surface-hover)] file:px-2 file:py-1 file:text-[var(--foreground)]"
        aria-describedby="paper-pdf-upload-feedback"
        onChange={(event) => {
          setFile(event.target.files?.[0] ?? null);
          setError("");
          setMessage("");
        }}
      />
      {file && (
        <p className="break-all text-xs text-[var(--muted)]">
          已选择：{file.name} · {(file.size / 1024 / 1024).toFixed(2)} MB
        </p>
      )}
      <Button
        type="submit"
        variant="secondary"
        size="sm"
        disabled={disabled || uploading || !file}
      >
        {uploading ? (
          <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
        ) : (
          <Upload className="h-3.5 w-3.5" />
        )}
        {uploading ? "正在上传原始 PDF…" : "上传原始 PDF"}
      </Button>
      <div id="paper-pdf-upload-feedback" aria-live="polite">
        {error && (
          <p role="alert" className="text-xs leading-5 text-[var(--danger)]">
            {error}
          </p>
        )}
        {message && (
          <p role="status" className="text-xs leading-5 text-[var(--accent)]">
            {message}
          </p>
        )}
        {!file && !message && !error && (
          <p className="text-xs text-[var(--muted)]">尚未选择 PDF 文件。</p>
        )}
      </div>
    </form>
  );
}
