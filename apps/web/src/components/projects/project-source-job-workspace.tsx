"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { api } from "@/lib/api";
import type { components } from "@/lib/generated";
type Job = components["schemas"]["ProjectSourceJobOut"];
type Files = components["schemas"]["ProjectSourceFilePage"];
type Event = components["schemas"]["ProjectSourceEventOut"];
type Verify = components["schemas"]["ProjectSourceVerifyOut"];
type Binding = components["schemas"]["ProjectPathBindingOut"];
const labels: Record<Job["status"], string> = {
  QUEUED: "复制排队中",
  COPYING: "正在无覆盖复制与核验",
  CANCEL_REQUESTED: "取消已请求，等待复制确认",
  COMPLETED: "复制任务技术完成",
  FAILED: "复制失败，成功检查点保留",
  CANCELLED: "复制已取消，已取得文件保留",
  NEEDS_ATTENTION: "实际复制结果需核查",
};

export function ProjectSourceJobWorkspace({
  projectId,
  jobId,
}: {
  projectId: string;
  jobId: string;
}) {
  const endpoint = `/projects/${encodeURIComponent(projectId)}/source-jobs/${encodeURIComponent(jobId)}`;
  const [job, setJob] = useState<Job | null>(null);
  const [files, setFiles] = useState<Files | null>(null);
  const [events, setEvents] = useState<Event[] | null>(null);
  const [verify, setVerify] = useState<Verify | null>(null);
  const [index, setIndex] = useState(0);
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  const [loading, setLoading] = useState(true);
  const [filesLoading, setFilesLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [fileError, setFileError] = useState("");
  const [eventError, setEventError] = useState("");
  const [notice, setNotice] = useState("");
  const busyRef = useRef(false);
  const polling = useRef(false);
  const seq = useRef(0);
  const fileSeq = useRef(0);
  const loadJob = useCallback(async () => {
    const current = ++seq.current;
    try {
      const result = await api.get<Job>(endpoint);
      if (current === seq.current) setJob(result);
    } catch (cause) {
      if (current === seq.current)
        setError(cause instanceof Error ? cause.message : "源码复制任务不可读");
    } finally {
      if (current === seq.current) setLoading(false);
    }
  }, [endpoint]);
  const loadFiles = useCallback(
    async (cursor: string | null, at: number) => {
      const current = ++fileSeq.current;
      setFilesLoading(true);
      setFileError("");
      try {
        const result = await api.get<Files>(
          `${endpoint}/files?limit=50${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
        );
        if (current === fileSeq.current) {
          setFiles(result);
          setIndex(at);
        }
      } catch (cause) {
        if (current === fileSeq.current)
          setFileError(
            cause instanceof Error ? cause.message : "实际复制文件清单不可读",
          );
      } finally {
        if (current === fileSeq.current) setFilesLoading(false);
      }
    },
    [endpoint],
  );
  const loadEvents = useCallback(async () => {
    setEventError("");
    try {
      setEvents(await api.get<Event[]>(`${endpoint}/events`));
    } catch (cause) {
      setEventError(
        cause instanceof Error ? cause.message : "源码复制事件不可读",
      );
    }
  }, [endpoint]);
  useEffect(() => {
    let active = true;
    void Promise.resolve().then(() => {
      if (active) {
        void loadJob();
        void loadFiles(null, 0);
        void loadEvents();
      }
    });
    return () => {
      active = false;
      seq.current += 1;
      fileSeq.current += 1;
    };
  }, [loadJob, loadFiles, loadEvents]);
  const active =
    !!job && ["QUEUED", "COPYING", "CANCEL_REQUESTED"].includes(job.status);
  useEffect(() => {
    if (!active) return;
    let enabled = true;
    const poll = async () => {
      if (!enabled || document.hidden || busyRef.current || polling.current)
        return;
      polling.current = true;
      try {
        await Promise.all([
          loadJob(),
          loadFiles(cursors[index] ?? null, index),
          loadEvents(),
        ]);
      } finally {
        polling.current = false;
      }
    };
    const interval = window.setInterval(() => void poll(), 4000);
    const visible = () => {
      if (!document.hidden) void poll();
    };
    document.addEventListener("visibilitychange", visible);
    return () => {
      enabled = false;
      window.clearInterval(interval);
      document.removeEventListener("visibilitychange", visible);
    };
  }, [active, loadJob, loadFiles, loadEvents, cursors, index]);
  async function action(
    kind: "cancel" | "resume" | "verify" | "revoke" | "reconcile",
  ) {
    if (!job || busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      if (kind === "verify") {
        const result = await api.post<Verify>(`${endpoint}/verify`, {});
        setVerify(result);
        setNotice("已显式只读复核当前文件；旧复制回执与历史状态保持不变。");
      } else if (kind === "revoke") {
        await api.post<Binding>(
          `/projects/${projectId}/path-bindings/${job.path_binding_id}/revoke`,
          {},
        );
        await loadJob();
        setNotice(
          "路径复制授权已撤销，已有文件保留；运行中的停止需等待实际确认。",
        );
      } else {
        const result = await api.post<Job>(`${endpoint}/${kind}`, {});
        setJob(result);
        setNotice(
          kind === "reconcile"
            ? "已只读核查复制结果；未自动恢复复制，确认后的失败任务可按原范围恢复。"
            : kind === "resume"
              ? "已按原批准范围恢复，仅复用重新核验的文件，不创建或扩大授权。"
              : result.status === "CANCEL_REQUESTED"
                ? "已请求取消，实际复制停止等待确认。"
                : "复制任务已取消，已有检查点和回执保留。",
        );
        await Promise.all([
          loadFiles(cursors[index] ?? null, index),
          loadEvents(),
        ]);
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "源码任务操作失败");
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }
  if (loading) return <LoadingState label="正在读取源码复制任务与实际文件…" />;
  if (!job)
    return (
      <ErrorState
        message={error || "项目源码任务不存在"}
        onRetry={() => void loadJob()}
      />
    );
  return (
    <div className="space-y-6">
      <Link
        href={`/projects/${projectId}/sources`}
        className="text-xs text-[var(--accent)]"
      >
        返回项目源码与本地资产
      </Link>
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">项目源码复制任务</h1>
        <p className="text-sm leading-6 text-[var(--muted)]">
          本任务只复制本人已取得的缓存成员到固定项目目录，不访问远端、执行代码或训练。实际复制、现场复核、科研资格分别记录。
        </p>
      </header>
      {job.status === "COMPLETED" &&
        job.receipt_sha256 &&
        job.binding_state === "ACTIVE" && (
          <Link
            href={`/projects/${projectId}/baselines?source_job=${job.id}`}
            className="inline-block text-sm text-[var(--accent)] underline"
          >
            将此来源登记到项目基线
          </Link>
        )}
      {error && (
        <div role="alert" aria-label="源码任务操作失败">
          <ErrorState message={error} />
        </div>
      )}
      {notice && (
        <p
          role="status"
          className="rounded border border-[var(--accent)] p-3 text-sm"
        >
          {notice}
        </p>
      )}
      <Card>
        <CardHeader>
          <h2 className="font-semibold">{labels[job.status]}</h2>
          <Button
            size="sm"
            variant="secondary"
            disabled={busy}
            onClick={() => {
              void loadJob();
              void loadFiles(cursors[index] ?? null, index);
              void loadEvents();
            }}
          >
            刷新源码复制回执
          </Button>
        </CardHeader>
        <CardContent className="space-y-3 text-xs">
          <dl className="grid gap-3 sm:grid-cols-2">
            <div>
              <dt className="text-[var(--muted)]">项目目录</dt>
              <dd className="mt-1 break-all">{job.root_label}</dd>
            </div>
            <div>
              <dt className="text-[var(--muted)]">已复制</dt>
              <dd className="mt-1">
                {job.copied_files} 个文件 ·{" "}
                {job.copied_bytes.toLocaleString("zh-CN")} 字节
              </dd>
            </div>
            <div>
              <dt className="text-[var(--muted)]">路径授权</dt>
              <dd className="mt-1">{job.binding_state}</dd>
            </div>
          </dl>
          <details className="rounded border border-[var(--border)]">
            <summary className="cursor-pointer p-3">任务身份与复制回执</summary>{" "}
            <dl className="grid gap-3 sm:grid-cols-2">
              {[
                ["Job ID", job.id],
                ["复制计划 ID", job.plan_id],
                ["固定根区域", job.root_label],
                [
                  "路径绑定 ID / 状态",
                  `${job.path_binding_id} / ${job.binding_state}`,
                ],
                ["来源资产状态", job.source_status],
                [
                  "已复制文件 / 字节",
                  `${job.copied_files} / ${job.copied_bytes.toLocaleString("zh-CN")}`,
                ],
                ["完整复制回执 SHA-256", job.receipt_sha256 || "尚无完整回执"],
                ["回执记录相对路径", job.receipt_path || "尚未记录"],
                [
                  "历史完成核验时间",
                  job.verified_at
                    ? new Date(job.verified_at).toLocaleString("zh-CN")
                    : "尚未记录",
                ],
              ].map(([name, value]) => (
                <div key={name}>
                  <dt className="text-[var(--muted)]">{name}</dt>
                  <dd className="mt-1 break-all font-mono">{value}</dd>
                </div>
              ))}
            </dl>
          </details>
          {job.error_message && (
            <p className="break-words text-[var(--danger)]">
              {job.error_code || "复制错误"}：{job.error_message}
            </p>
          )}
          {job.status === "NEEDS_ATTENTION" && (
            <p>实际结果需核查，不自动重放或覆盖文件。</p>
          )}
          {job.status === "CANCEL_REQUESTED" && (
            <p>尚未确认复制停止，不能显示为已停止。</p>
          )}
          {job.source_status === "PARTIAL" && (
            <p className="text-amber-700 dark:text-amber-300">
              来源保持 PARTIAL，复制不会补齐缺口。
            </p>
          )}
          <p>
            代码执行与训练权限：未授予。基线资格：未授予。缓存不是 Git clone
            历史。
          </p>
          <ul className="space-y-1 text-[var(--muted)]">
            {job.gaps.map((gap, at) => (
              <li key={`${gap}:${at}`}>{gap}</li>
            ))}
          </ul>
          <div className="flex flex-wrap gap-2">
            {job.can_cancel && (
              <Button
                size="sm"
                variant="secondary"
                disabled={busy}
                onClick={() => void action("cancel")}
              >
                取消源码复制任务
              </Button>
            )}
            {job.can_resume && (
              <Button
                size="sm"
                disabled={busy}
                onClick={() => void action("resume")}
              >
                按原范围恢复源码复制
              </Button>
            )}
            {job.can_verify && (
              <Button
                size="sm"
                variant="secondary"
                disabled={busy}
                onClick={() => void action("verify")}
              >
                显式只读复核当前源码文件
              </Button>
            )}
            {job.binding_state === "ACTIVE" && (
              <Button
                size="sm"
                variant="secondary"
                disabled={busy}
                onClick={() => void action("revoke")}
              >
                撤销此路径复制授权
              </Button>
            )}
          </div>
        </CardContent>
      </Card>
      {verify && (
        <Card>
          <CardHeader>
            <h2 className="font-semibold">
              当前现场复核 · {verify.verified ? "通过" : "存在缺口"}
            </h2>
          </CardHeader>
          <CardContent className="space-y-2 text-xs">
            <p>
              本次时间 {new Date(verify.checked_at).toLocaleString("zh-CN")}
              ，只读检查不改写旧成功状态。
            </p>
            {verify.files.map((file) => (
              <div
                key={file.path}
                className="space-y-1 rounded border border-[var(--border)] p-2"
              >
                <p className="break-all">
                  {file.path} · {file.status}
                </p>
                <p className="break-all font-mono">
                  当前 SHA-256：{file.actual_sha256 ?? "未知"}
                </p>
                <p>当前字节：{file.actual_size_bytes ?? "未知"}</p>
              </div>
            ))}
            {verify.gaps.map((gap, at) => (
              <p key={`${gap}:${at}`} className="text-[var(--muted)]">
                {gap}
              </p>
            ))}
          </CardContent>
        </Card>
      )}
      <Card>
        <CardHeader>
          <h2 className="font-semibold">实际项目文件与检查点</h2>
        </CardHeader>
        <CardContent className="space-y-3 text-xs">
          {fileError && (
            <ErrorState
              message={fileError}
              onRetry={() => void loadFiles(cursors[index] ?? null, index)}
            />
          )}
          {job.can_reconcile && (
            <Button
              size="sm"
              variant="secondary"
              disabled={busy}
              onClick={() => void action("reconcile")}
            >
              核查复制结果
            </Button>
          )}
          {filesLoading && <LoadingState label="正在读取项目文件回执…" />}
          {files &&
            !filesLoading &&
            (files.items.length ? (
              <ul className="space-y-2">
                {files.items.map((file) => (
                  <li
                    key={file.id}
                    className="space-y-1 rounded border border-[var(--border)] p-3"
                  >
                    <p className="break-all font-medium">
                      {file.path} · {file.status}
                    </p>
                    <p>实际字节：{file.actual_size_bytes ?? "尚未取得"}</p>
                    <details>
                      <summary className="cursor-pointer py-1 text-[var(--muted)]">
                        查看文件校验与路径
                      </summary>{" "}
                      <p className="break-all font-mono">
                        实际 SHA-256：{file.actual_sha256 || "尚未取得"}
                      </p>
                      <p>实际字节：{file.actual_size_bytes ?? "尚未取得"}</p>
                      <p className="break-all font-mono">
                        固定相对路径：{file.relative_path || "尚未取得"}
                      </p>
                      <p className="text-[var(--muted)]">
                        记录核验时间：
                        {file.verified_at
                          ? new Date(file.verified_at).toLocaleString("zh-CN")
                          : "尚未记录"}
                      </p>
                    </details>
                    {file.error_code && (
                      <p className="text-[var(--danger)]">{file.error_code}</p>
                    )}
                    {file.status === "QUARANTINED" && (
                      <p>隔离保留，不计完成交付。</p>
                    )}
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState title="尚无实际复制文件回执" />
            ))}
          <div className="flex items-center justify-between">
            <Button
              size="sm"
              variant="secondary"
              disabled={busy || filesLoading || index === 0}
              onClick={() =>
                void loadFiles(cursors[index - 1] ?? null, index - 1)
              }
            >
              上一页项目文件
            </Button>
            <span>第 {index + 1} 页</span>
            <Button
              size="sm"
              variant="secondary"
              disabled={busy || filesLoading || !files?.page.next_cursor}
              onClick={() => {
                const next = files?.page.next_cursor;
                if (next) {
                  setCursors((old) => [...old.slice(0, index + 1), next]);
                  void loadFiles(next, index + 1);
                }
              }}
            >
              下一页项目文件
            </Button>
          </div>
        </CardContent>
      </Card>
      <details className="rounded border border-[var(--border)]">
        <summary className="cursor-pointer p-3 text-sm">
          复制事件与审计回执
        </summary>{" "}
        <Card>
          <CardHeader>
            <h2 className="font-semibold">源码复制原始事件</h2>
            <Button
              size="sm"
              variant="secondary"
              disabled={busy}
              onClick={() => void loadEvents()}
            >
              刷新复制原始事件
            </Button>
          </CardHeader>
          <CardContent className="space-y-2 text-xs">
            {eventError && (
              <ErrorState
                message={eventError}
                onRetry={() => void loadEvents()}
              />
            )}
            {events ? (
              events.length ? (
                <ol className="space-y-2">
                  {events.map((event) => (
                    <li
                      key={event.id}
                      className="rounded border border-[var(--border)] p-2"
                    >
                      <p>
                        {new Date(event.occurred_at).toLocaleString("zh-CN")} ·{" "}
                        {event.event_type}
                      </p>
                      <p>
                        {event.status || "未记录状态"} ·{" "}
                        {event.code || "无错误码"}
                      </p>
                      {(event.receipt_sha256 ||
                        event.receipt_path ||
                        event.disposition) && (
                        <details className="mt-2 space-y-2">
                          <summary className="cursor-pointer">
                            查看事件回执
                          </summary>
                          {event.disposition === "QUARANTINED" && (
                            <p>
                              QUARANTINED ·
                              晚到回执隔离保留，仅供审计，不计任务成功或完成交付。
                            </p>
                          )}
                          <p className="break-all font-mono">
                            事件回执 SHA-256：{event.receipt_sha256 || "未记录"}
                          </p>
                          <p className="break-all font-mono">
                            事件回执路径：{event.receipt_path || "未记录"}
                          </p>
                        </details>
                      )}
                    </li>
                  ))}
                </ol>
              ) : (
                <EmptyState title="尚无源码复制事件" />
              )
            ) : (
              !eventError && <LoadingState label="正在读取源码复制事件…" />
            )}
          </CardContent>
        </Card>
      </details>
    </div>
  );
}
