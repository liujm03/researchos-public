"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { EmptyState, LoadingState } from "@/components/ui/state";
import { api } from "@/lib/api";
import { BaselineInputError } from "./input-error";
import type { components } from "@/lib/generated";
type SourceJob = components["schemas"]["BaselineSourceJobChoice"];
type SourceJobs = components["schemas"]["BaselineSourceJobPage"];
type SourceFile = components["schemas"]["BaselineSourceFileChoice"];
type SourceFiles = components["schemas"]["BaselineSourceFilePage"];
const selectClass =
  "h-9 w-full rounded border border-[var(--border)] bg-[var(--background)] px-2 text-sm";

export function SourceFilePicker({
  projectId,
  initialJobId,
  onAdd,
  disabled = false,
}: {
  projectId: string;
  initialJobId?: string;
  onAdd: (file: SourceFile) => void;
  disabled?: boolean;
}) {
  const endpoint = `/projects/${encodeURIComponent(projectId)}/baseline-inputs/source-jobs`;
  const [jobs, setJobs] = useState<SourceJob[]>([]);
  const [jobId, setJobId] = useState("");
  const [nextJobCursor, setNextJobCursor] = useState<string | null>(null);
  const [files, setFiles] = useState<SourceFiles | null>(null);
  const [fileCursors, setFileCursors] = useState<(string | null)[]>([null]);
  const [filePage, setFilePage] = useState(0);
  const [loading, setLoading] = useState(true);
  const [fileLoading, setFileLoading] = useState(false);
  const [error, setError] = useState("");
  const [fileError, setFileError] = useState("");
  const seq = useRef(0),
    fileSeq = useRef(0);
  const initial = useRef(initialJobId);
  const jobRetry = useRef<string | null>(null);
  const fileRetry = useRef<{ id: string; cursor: string | null; page: number }>(
    { id: "", cursor: null, page: 0 },
  );
  const loadJobs = useCallback(
    async (cursor: string | null = null) => {
      const token = ++seq.current;
      setLoading(true);
      jobRetry.current = cursor;
      try {
        const result = await api.get<SourceJobs>(
          `${endpoint}?limit=20${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
        );
        if (token !== seq.current) return;
        setJobs((old) =>
          cursor
            ? [
                ...old,
                ...result.items.filter(
                  (item) => !old.some((row) => row.id === item.id),
                ),
              ]
            : result.items,
        );
        setNextJobCursor(result.page.next_cursor);
        setError("");
        if (
          initial.current &&
          result.items.some((item) => item.id === initial.current)
        ) {
          setJobId(initial.current);
          initial.current = undefined;
        } else if (initial.current && !cursor) {
          const linked = await api.get<SourceJobs>(
            `${endpoint}?limit=20&source_job_id=${encodeURIComponent(initial.current)}`,
          );
          if (token !== seq.current) return;
          const target = linked.items.find(
            (item) => item.id === initial.current,
          );
          if (target) {
            setJobs((old) =>
              old.some((item) => item.id === target.id)
                ? old
                : [...old, target],
            );
            setJobId(target.id);
            initial.current = undefined;
          } else
            setError(
              "指定来源不在本项目当前可登记材料范围内；可选择其他已复制来源。",
            );
        }
      } catch (cause) {
        if (token === seq.current)
          setError(
            cause instanceof Error ? cause.message : "无法读取已复制源码选项",
          );
      } finally {
        if (token === seq.current) setLoading(false);
      }
    },
    [endpoint],
  );
  const loadFiles = useCallback(
    async (id: string, cursor: string | null = null, page = 0) => {
      const token = ++fileSeq.current;
      setFileLoading(true);
      fileRetry.current = { id, cursor, page };
      try {
        const result = await api.get<SourceFiles>(
          `${endpoint}/${encodeURIComponent(id)}/files?limit=30${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
        );
        if (token !== fileSeq.current) return;
        setFiles(result);
        setFilePage(page);
        setFileError("");
      } catch (cause) {
        if (token === fileSeq.current)
          setFileError(
            cause instanceof Error ? cause.message : "无法读取实际源码文件",
          );
      } finally {
        if (token === fileSeq.current) setFileLoading(false);
      }
    },
    [endpoint],
  );
  useEffect(() => {
    queueMicrotask(() => void loadJobs());
    return () => {
      seq.current += 1;
    };
  }, [loadJobs]);
  useEffect(() => {
    if (!jobId) return;
    queueMicrotask(() => {
      setFiles(null);
      setFileCursors([null]);
      setFilePage(0);
      void loadFiles(jobId);
    });
    return () => {
      fileSeq.current += 1;
    };
  }, [jobId, loadFiles]);
  const source = jobs.find((job) => job.id === jobId);
  return (
    <section
      className="space-y-3 rounded border border-[var(--border)] p-3"
      aria-label="实际源码文件选择"
    >
      <h3 className="text-sm font-medium">选择实际保存文件</h3>
      <p className="text-xs text-[var(--muted)]">
        选项来自本项目已复制的文件回执；登记后仍需显式核查当前材料。
      </p>
      {error && (
        <BaselineInputError
          message={error}
          onRetry={() => void loadJobs(jobRetry.current)}
        />
      )}
      {loading && !jobs.length ? (
        <LoadingState label="正在读取已复制来源…" />
      ) : (
        <label className="block space-y-1 text-xs">
          选择已复制源码
          <select
            aria-label="选择已复制源码"
            value={jobId}
            disabled={disabled || loading}
            className={selectClass}
            onChange={(event) => {
              fileSeq.current += 1;
              setFiles(null);
              setFileLoading(false);
              setFileError("");
              setJobId(event.target.value);
            }}
          >
            <option value="">选择一个已保存来源</option>
            {jobs.map((job) => (
              <option key={job.id} value={job.id}>
                {job.repo_id} · {job.commit_sha.slice(0, 12)} ·{" "}
                {job.source_status} · {job.copied_files} 个文件
              </option>
            ))}
          </select>
        </label>
      )}
      {!loading && !error && !jobs.length && (
        <EmptyState
          title="本项目尚无可选择的已复制源码"
          detail="先在源码资料页核对并复制已保存的资产；缺材料也可先登记基线草稿。"
        />
      )}
      {initialJobId && !source && (
        <p className="text-xs text-[var(--muted)]">
          链接指定的来源尚未出现在当前选项页，可继续加载来源并核对。
        </p>
      )}
      {nextJobCursor && (
        <Button
          type="button"
          size="sm"
          variant="secondary"
          disabled={disabled || loading}
          onClick={() => void loadJobs(nextJobCursor)}
        >
          加载更多已复制来源
        </Button>
      )}
      {source && (
        <div className="space-y-1 text-xs">
          <p className="break-all">
            {source.repo_id} · Commit {source.commit_sha}
          </p>
          <p>
            来源状态 {source.source_status} · 复制 {source.copied_files} 文件 /{" "}
            {source.copied_bytes.toLocaleString("zh-CN")} 字节
          </p>
          {source.source_status === "PARTIAL" && (
            <p className="text-amber-700 dark:text-amber-300">
              来源仍为 PARTIAL；基线必需材料范围将在登记版本中单独核查。
            </p>
          )}
          <details>
            <summary className="cursor-pointer">来源复制回执</summary>
            <p className="mt-2 break-all font-mono">{source.receipt_sha256}</p>
            <p>
              记录核验时间：
              {new Date(source.verified_at).toLocaleString("zh-CN")}
              ；不是当前文件现场核验。
            </p>
          </details>
        </div>
      )}
      {fileError && (
        <BaselineInputError
          message={fileError}
          onRetry={() =>
            void loadFiles(
              fileRetry.current.id,
              fileRetry.current.cursor,
              fileRetry.current.page,
            )
          }
        />
      )}
      {fileLoading ? (
        <LoadingState label="正在读取实际文件分页…" />
      ) : (
        files &&
        (files.items.length ? (
          <ul className="space-y-2">
            {files.items.map((file) => (
              <li
                key={file.source_file_id}
                className="space-y-1 rounded border border-[var(--border)] p-2 text-xs"
              >
                <p className="break-all font-medium">{file.path}</p>
                <p className="break-all font-mono">SHA-256：{file.sha256}</p>
                <p>{file.size_bytes.toLocaleString("zh-CN")} 字节</p>
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  disabled={disabled}
                  aria-label={`声明文件 ${file.path}`}
                  onClick={() => onAdd(file)}
                >
                  加入必需材料声明
                </Button>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState title="此页没有实际文件选项" />
        ))
      )}
      {files && (
        <div className="flex items-center justify-between gap-2 text-xs">
          <Button
            type="button"
            size="sm"
            variant="secondary"
            disabled={disabled || fileLoading || filePage === 0}
            onClick={() =>
              void loadFiles(
                jobId,
                fileCursors[filePage - 1] ?? null,
                filePage - 1,
              )
            }
          >
            上一页源码文件
          </Button>
          <span>第 {filePage + 1} 页</span>
          <Button
            type="button"
            size="sm"
            variant="secondary"
            disabled={disabled || fileLoading || !files.page.next_cursor}
            onClick={() => {
              const next = files.page.next_cursor;
              if (next) {
                setFileCursors((old) => [...old.slice(0, filePage + 1), next]);
                void loadFiles(jobId, next, filePage + 1);
              }
            }}
          >
            下一页源码文件
          </Button>
        </div>
      )}
    </section>
  );
}
