"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { Download, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input, Textarea } from "@/components/ui/input";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { api } from "@/lib/api";
import type {
  ArtifactCreate,
  ArtifactPage,
  ArtifactUploadOut,
  ExperimentArtifact,
} from "@/lib/experiments";

const artifactTypes = [
  "CHECKPOINT",
  "LOG",
  "TRAINING_CURVE",
  "PR_CURVE",
  "CONFUSION_MATRIX",
  "FIGURE",
  "REPORT",
  "CONFIG",
  "OTHER",
] as const;
const apiBase = process.env.NEXT_PUBLIC_API_BASE_PATH ?? "/api/v1";

function formatBytes(value: number | null | undefined) {
  if (value === null || value === undefined) return "大小未记录";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MiB`;
}

export function RunArtifacts({ runId }: { runId: string }) {
  const [artifacts, setArtifacts] = useState<ExperimentArtifact[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [saving, setSaving] = useState(false);
  const [mode, setMode] = useState<"upload" | "attach">("upload");
  const [artifactType, setArtifactType] =
    useState<ArtifactCreate["artifact_type"]>("LOG");
  const [description, setDescription] = useState("");
  const [attachmentId, setAttachmentId] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const generation = useRef(0);

  const load = useCallback(async () => {
    const request = ++generation.current;
    setLoading(true);
    setError("");
    try {
      const first = await api.get<ArtifactPage>(
        `/experiment-runs/${runId}/artifacts?limit=100&offset=0`,
      );
      const all = [...first.items];
      for (let offset = first.items.length; offset < first.total;) {
        if (request !== generation.current) return;
        const page = await api.get<ArtifactPage>(
          `/experiment-runs/${runId}/artifacts?limit=100&offset=${offset}`,
        );
        if (!page.items.length)
          throw new Error("实验产物分页未推进，请刷新后重试。");
        all.push(...page.items);
        offset += page.items.length;
      }
      if (request === generation.current) setArtifacts(all);
    } catch (cause) {
      if (request === generation.current)
        setError(cause instanceof Error ? cause.message : "无法读取实验产物");
    } finally {
      if (request === generation.current) setLoading(false);
    }
  }, [runId]);

  useEffect(() => {
    let active = true;
    const controller = generation;
    queueMicrotask(() => {
      if (active) void load();
    });
    return () => {
      active = false;
      controller.current++;
    };
  }, [load]);

  async function save(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    setNotice("");
    try {
      if (mode === "upload") {
        if (!file || !file.size) throw new Error("请选择非空的实验产物文件。");
        const body = new FormData();
        body.set("file", file);
        const query = new URLSearchParams({ artifact_type: artifactType });
        if (description.trim()) query.set("description", description.trim());
        const receipt = await api.postForm<ArtifactUploadOut>(
          `/experiment-runs/${runId}/artifacts/upload?${query}`,
          body,
        );
        setNotice(
          `${receipt.duplicate ? "已复用相同文件并关联" : "实验产物已上传并关联"}。SHA-256：${receipt.artifact.sha256 ?? "未返回"}`,
        );
        setFile(null);
        if (fileInput.current) fileInput.current.value = "";
      } else {
        const body: ArtifactCreate = {
          attachment_id: attachmentId.trim(),
          artifact_type: artifactType,
          description: description.trim() || null,
        };
        await api.post<ExperimentArtifact>(
          `/experiment-runs/${runId}/artifacts`,
          body,
        );
        setNotice("已关联当前账户的附件，文件内容保持原样。");
        setAttachmentId("");
      }
      setDescription("");
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "实验产物保存失败");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <div>
          <h2 className="font-semibold">实验产物</h2>
          <p className="mt-1 text-xs leading-5 text-[var(--muted)]">
            保存日志、Checkpoint、配置、图表和报告。平台仅存储与校验文件，不执行模型文件。
          </p>
        </div>
      </CardHeader>
      <CardContent className="space-y-5">
        {error && (
          <ErrorState
            message={error}
            onRetry={
              !artifacts.length
                ? () => {
                    void load();
                  }
                : undefined
            }
          />
        )}
        {notice && (
          <p
            role="status"
            className="break-all text-xs leading-5 text-emerald-600 dark:text-emerald-400"
          >
            {notice}
          </p>
        )}
        <form
          onSubmit={save}
          className="grid gap-4 rounded-lg border border-[var(--border)] p-4 sm:grid-cols-2"
        >
          <label className="space-y-1.5 text-xs font-medium">
            添加方式
            <select
              aria-label="添加方式"
              value={mode}
              onChange={(event) => setMode(event.target.value as typeof mode)}
              className="block h-9 w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-3 text-sm"
            >
              <option value="upload">上传本地实验产物</option>
              <option value="attach">关联已存储附件</option>
            </select>
          </label>
          <label className="space-y-1.5 text-xs font-medium">
            产物类型
            <select
              aria-label="产物类型"
              value={artifactType}
              onChange={(event) =>
                setArtifactType(event.target.value as typeof artifactType)
              }
              className="block h-9 w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-3 text-sm"
            >
              {artifactTypes.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>
          {mode === "upload" ? (
            <label className="space-y-1.5 text-xs font-medium sm:col-span-2">
              实验产物文件
              <Input
                ref={fileInput}
                type="file"
                required
                onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              />
              <span className="block text-[var(--muted)]">
                文件保存在本机私有存储，返回真实内容哈希。上传不会启动 AI
                或训练。
              </span>
            </label>
          ) : (
            <label className="space-y-1.5 text-xs font-medium sm:col-span-2">
              附件 ID
              <Input
                required
                value={attachmentId}
                onChange={(event) => setAttachmentId(event.target.value)}
                placeholder="已保存附件的 UUID"
                pattern="[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
              />
            </label>
          )}
          <label className="space-y-1.5 text-xs font-medium sm:col-span-2">
            产物说明
            <Textarea
              maxLength={2000}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="例如：固定测试集的逐类混淆矩阵"
            />
          </label>
          <div className="sm:col-span-2">
            <Button
              type="submit"
              disabled={saving || (mode === "upload" && !file)}
            >
              <Upload className="h-4 w-4" />
              {saving
                ? "保存中…"
                : mode === "upload"
                  ? "上传并关联产物"
                  : "关联附件"}
            </Button>
          </div>
        </form>
        {loading ? (
          <LoadingState label="正在读取实验产物…" />
        ) : artifacts.length ? (
          <ul className="space-y-3">
            {artifacts.map((artifact) => (
              <li
                key={artifact.id}
                className="space-y-2 rounded-lg border border-[var(--border)] p-4"
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <h3 className="text-sm font-medium">
                      {artifact.original_filename || artifact.attachment_id}
                    </h3>
                    <p className="mt-1 text-xs text-[var(--muted)]">
                      {artifact.artifact_type} ·{" "}
                      {formatBytes(artifact.size_bytes)} ·{" "}
                      {artifact.mime_type ?? "类型未记录"}
                    </p>
                  </div>
                  <Button asChild variant="secondary" size="sm">
                    <a
                      href={`${apiBase}/attachments/${artifact.attachment_id}/download`}
                      download={artifact.original_filename}
                    >
                      <Download className="h-3.5 w-3.5" />
                      下载原文件
                    </a>
                  </Button>
                </div>
                {artifact.description && (
                  <p className="text-xs leading-5 text-[var(--muted)]">
                    {artifact.description}
                  </p>
                )}
                <dl className="space-y-1 text-[10px] leading-5">
                  <div>
                    <dt className="inline text-[var(--muted)]">SHA-256：</dt>
                    <dd className="inline break-all font-mono">
                      {artifact.sha256 ?? "未记录"}
                    </dd>
                  </div>
                  <div>
                    <dt className="inline text-[var(--muted)]">附件 ID：</dt>
                    <dd className="inline break-all font-mono">
                      {artifact.attachment_id}
                    </dd>
                  </div>
                </dl>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState
            title="尚无实验产物"
            detail="上传自己生成的日志、Checkpoint 或报告，或关联已保存附件。"
          />
        )}
      </CardContent>
    </Card>
  );
}
