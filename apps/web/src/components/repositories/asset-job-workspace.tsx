"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { api } from "@/lib/api";
import { AssetProjectTarget } from "./asset-project-target";
import type { components } from "@/lib/generated";
type Job = components["schemas"]["AssetJobOut"];
type Plan = components["schemas"]["AssetPlanOut"];
type FilePage = components["schemas"]["AssetFilePage"];
type Event = components["schemas"]["AssetEventOut"];
const labels: Record<Job["status"], string> = {
  QUEUED: "排队中",
  DOWNLOADING: "正在下载并核验",
  CANCEL_REQUESTED: "取消已请求，等待确认",
  COMPLETED: "下载任务技术完成",
  FAILED: "下载失败，成功文件保留",
  CANCELLED: "已取消，成功文件保留",
  NEEDS_ATTENTION: "下载状态需核查",
};
function ownerDownload(value: string | null) {
  return value &&
    /^\/api\/v1\/attachments\/[0-9a-f-]{36}\/download$/.test(value)
    ? value
    : null;
}

export function AssetJobWorkspace({ jobId }: { jobId: string }) {
  const [job, setJob] = useState<Job | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [files, setFiles] = useState<FilePage | null>(null);
  const [events, setEvents] = useState<Event[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [filesLoading, setFilesLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [filesError, setFilesError] = useState("");
  const [eventsError, setEventsError] = useState("");
  const [notice, setNotice] = useState("");
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  const [index, setIndex] = useState(0);
  const busyRef = useRef(false);
  const polling = useRef(false);
  const seq = useRef(0);
  const fileSeq = useRef(0);
  const endpoint = `/repository-asset-jobs/${encodeURIComponent(jobId)}`;

  const loadFiles = useCallback(
    async (cursor: string | null, at: number) => {
      const current = ++fileSeq.current;
      setFilesLoading(true);
      setFilesError("");
      try {
        const result = await api.get<FilePage>(
          `${endpoint}/files?limit=50${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
        );
        if (current === fileSeq.current) {
          setFiles(result);
          setIndex(at);
        }
      } catch (cause) {
        if (current === fileSeq.current)
          setFilesError(
            cause instanceof Error ? cause.message : "实际文件清单不可读",
          );
      } finally {
        if (current === fileSeq.current) setFilesLoading(false);
      }
    },
    [endpoint],
  );
  const loadEvents = useCallback(async () => {
    setEventsError("");
    try {
      setEvents(await api.get<Event[]>(`${endpoint}/events`));
    } catch (cause) {
      setEventsError(cause instanceof Error ? cause.message : "下载事件不可读");
    }
  }, [endpoint]);
  const load = useCallback(async () => {
    const current = ++seq.current;
    setError("");
    try {
      const value = await api.get<Job>(endpoint);
      const sourcePlan = await api.get<Plan>(
        `/repository-asset-plans/${value.plan_id}`,
      );
      if (current === seq.current) {
        setJob(value);
        setPlan(sourcePlan);
      }
    } catch (cause) {
      if (current === seq.current)
        setError(cause instanceof Error ? cause.message : "下载任务不可读");
    } finally {
      if (current === seq.current) setLoading(false);
    }
  }, [endpoint]);
  useEffect(() => {
    let active = true;
    void Promise.resolve().then(() => {
      if (active) {
        void load();
        void loadFiles(null, 0);
        void loadEvents();
      }
    });
    return () => {
      active = false;
      seq.current += 1;
      fileSeq.current += 1;
    };
  }, [load, loadFiles, loadEvents]);
  const active =
    !!job && ["QUEUED", "DOWNLOADING", "CANCEL_REQUESTED"].includes(job.status);
  useEffect(() => {
    if (!active) return;
    let enabled = true;
    const poll = async () => {
      if (!enabled || document.hidden || busyRef.current || polling.current)
        return;
      polling.current = true;
      try {
        await Promise.all([
          load(),
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
  }, [active, load, loadFiles, loadEvents, cursors, index]);
  async function action(kind: "cancel" | "resume") {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await api.post<Job>(`${endpoint}/${kind}`, {});
      setJob(result);
      setNotice(
        kind === "resume"
          ? "已在原批准范围恢复，仅继续未完成文件；不重复批准或启动代码。"
          : result.status === "CANCEL_REQUESTED"
            ? "已请求取消，当前下载停止需等待实际确认。"
            : "已取消任务；已核验文件与回执保留。",
      );
      await Promise.all([
        loadFiles(cursors[index] ?? null, index),
        loadEvents(),
      ]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "任务操作失败");
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }
  if (loading) return <LoadingState label="正在读取下载任务与实际资产…" />;
  if (!job || !plan)
    return (
      <ErrorState
        message={error || "下载任务不存在"}
        onRetry={() => void load()}
      />
    );
  return (
    <div className="space-y-6">
      <Link
        href={`/integrations/repositories/sources/${plan.source_snapshot_id}`}
        className="text-xs text-[var(--accent)]"
      >
        返回冻结仓库来源
      </Link>
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">仓库资产下载任务</h1>
        <p className="text-sm text-[var(--muted)]">
          实际取得的缓存文件、校验与进度独立于元数据登记；这里不执行代码、训练或认定科研基线。
        </p>
      </header>
      {error && (
        <div role="alert" aria-label="资产任务操作失败">
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
      {job.snapshot && <AssetProjectTarget snapshot={job.snapshot} />}
      <Card>
        <CardHeader>
          <h2 className="font-semibold">{labels[job.status]}</h2>
          <Button
            size="sm"
            variant="secondary"
            disabled={busy}
            onClick={() => {
              void load();
              void loadFiles(cursors[index] ?? null, index);
              void loadEvents();
            }}
          >
            刷新任务与文件回执
          </Button>
        </CardHeader>
        <CardContent className="space-y-3 text-xs">
          <dl className="grid gap-3 sm:grid-cols-2">
            {[
              ["Job ID", job.id],
              ["计划 ID", plan.id],
              [
                "固定仓库 / Provider ID",
                `${plan.provider_key}/${plan.repo_id} / ${plan.provider_id}`,
              ],
              ["Commit", plan.commit_sha],
              ["范围", plan.scope],
              [
                "实际已保存文件 / 字节",
                `${job.stored_files} / ${job.stored_bytes.toLocaleString("zh-CN")}`,
              ],
              ["计划 SHA-256", plan.plan_sha256],
              ["批准 SHA-256", plan.approved_hash || "未记录"],
            ].map(([name, value]) => (
              <div key={name}>
                <dt className="text-[var(--muted)]">{name}</dt>
                <dd className="mt-1 break-all font-mono">{value}</dd>
              </div>
            ))}
          </dl>
          {job.error_message && (
            <p className="break-words text-[var(--danger)]">
              {job.error_code || "下载错误"}：{job.error_message}
            </p>
          )}
          {job.status === "CANCEL_REQUESTED" && (
            <p>尚未确认当前下载停止，不能显示为已停止。</p>
          )}
          <div className="flex flex-wrap gap-2">
            {job.can_cancel && (
              <Button
                size="sm"
                variant="secondary"
                disabled={busy}
                onClick={() => void action("cancel")}
              >
                取消下载任务
              </Button>
            )}
            {job.can_resume && (
              <Button
                size="sm"
                disabled={busy}
                onClick={() => void action("resume")}
              >
                在原批准范围恢复未完成文件
              </Button>
            )}
          </div>
        </CardContent>
      </Card>
      {job.snapshot && (
        <Card>
          <CardHeader>
            <h2 className="font-semibold">资产快照 · {job.snapshot.status}</h2>
          </CardHeader>
          <CardContent className="space-y-2 text-xs">
            <p>
              {job.snapshot.status === "PARTIAL"
                ? "只取得部分范围、存在缺口或选择了子集，不能作为完整资产缓存。"
                : "库存范围内的实际资产已取得；不保证外部数据引用、可运行性或科学复现。"}
            </p>
            <p className="break-all font-mono">
              快照 Manifest SHA-256：{job.snapshot.manifest_sha256}
            </p>
            <p>
              实测文件 {job.snapshot.stored_files} / 实测字节{" "}
              {job.snapshot.stored_bytes.toLocaleString("zh-CN")}
            </p>
            <p className="font-medium">
              基线资格：未授予；还需独立运行、协议与科学验证。
            </p>
            <ul className="space-y-1 text-[var(--muted)]">
              {job.snapshot.gaps.map((gap, at) => (
                <li key={`${gap}:${at}`}>{gap}</li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
      <Card>
        <CardHeader>
          <h2 className="font-semibold">实际文件库存</h2>
        </CardHeader>
        <CardContent className="space-y-3">
          {filesError && (
            <ErrorState
              message={filesError}
              onRetry={() => void loadFiles(cursors[index] ?? null, index)}
            />
          )}
          {filesLoading && <LoadingState label="正在读取实际文件…" />}
          {files &&
            !filesLoading &&
            (files.items.length ? (
              <ul className="space-y-2 text-xs">
                {files.items.map((file) => {
                  const url = ownerDownload(file.download_url);
                  return (
                    <li
                      key={file.id}
                      className="space-y-1 rounded border border-[var(--border)] p-3"
                    >
                      <p className="break-all font-medium">
                        {file.path} · {file.status}
                      </p>
                      <p className="break-all font-mono">
                        实际 SHA-256：{file.actual_sha256 || "尚未取得"}
                      </p>
                      <p>
                        实际大小：
                        {file.actual_size_bytes === null
                          ? "尚未取得"
                          : `${file.actual_size_bytes.toLocaleString("zh-CN")} 字节`}{" "}
                        · 远端身份核验：
                        {file.remote_verified ? "通过" : "尚未通过"}
                      </p>
                      {file.error_code && (
                        <p className="text-[var(--muted)]">{file.error_code}</p>
                      )}
                      {url && (
                        <a
                          href={url}
                          className="inline-block text-[var(--accent)] underline"
                        >
                          {file.remote_verified
                            ? "下载已核验缓存文件"
                            : "下载保留对象用于审计"}
                        </a>
                      )}
                    </li>
                  );
                })}
              </ul>
            ) : (
              <EmptyState
                title="尚无实际取得的资产文件"
                detail="清单或排队不等于文件已下载。"
              />
            ))}
          <div className="flex items-center justify-between text-xs">
            <Button
              size="sm"
              variant="secondary"
              disabled={busy || filesLoading || index === 0}
              onClick={() =>
                void loadFiles(cursors[index - 1] ?? null, index - 1)
              }
            >
              上一页实际文件
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
              下一页实际文件
            </Button>
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <h2 className="font-semibold">原始任务事件</h2>
          <Button
            size="sm"
            variant="secondary"
            disabled={busy}
            onClick={() => void loadEvents()}
          >
            刷新原始事件
          </Button>
        </CardHeader>
        <CardContent className="space-y-2 text-xs">
          {eventsError && (
            <ErrorState
              message={eventsError}
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
                      {event.status || "状态未记录"} ·{" "}
                      {event.code || "无错误码"}
                    </p>
                  </li>
                ))}
              </ol>
            ) : (
              <EmptyState title="尚无持久事件" />
            )
          ) : (
            !eventsError && <LoadingState label="正在读取事件…" />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
