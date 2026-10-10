"use client";

import Link from "next/link";
import type {
  ZoteroSyncJob,
  ZoteroSyncJobPage,
  ZoteroSyncItemPage,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";

const labels: Record<string, string> = {
  QUEUED: "等待执行",
  RUNNING: "正在同步",
  COMPLETED: "同步完成",
  PARTIAL: "部分完成",
  FAILED: "同步失败",
  CANCELLED: "已取消",
};

function recordLabel(job: ZoteroSyncJob) {
  const kind =
    job.job_type === "FULL_LIBRARY"
      ? "整库读取"
      : job.job_type === "SINGLE_ITEM"
        ? "单篇同步"
        : "增量同步";
  return `${kind} · ${labels[job.status]} · ${new Date(job.queued_at).toLocaleString("zh-CN")}`;
}

type Props = {
  job: ZoteroSyncJob | null;
  records: ZoteroSyncJobPage | null;
  loading: boolean;
  recordsOffset: number;
  recordsError: string;
  detailError: string;
  actionError: string;
  message: string;
  busy: boolean;
  issuesOpen: boolean;
  issues: ZoteroSyncItemPage | null;
  issuesLoading: boolean;
  issuesError: string;
  issuesOffset: number;
  onRefresh: () => void;
  onSelect: (job: ZoteroSyncJob) => void;
  onRecordsOffset: (offset: number) => void;
  onAction: (action: "retry" | "cancel") => void;
  onToggleIssues: () => void;
  onReloadIssues: () => void;
  onIssuesOffset: (offset: number) => void;
};

export function ZoteroSyncSummary(props: Props) {
  const { job, records } = props;
  const choices = records?.items ?? [];
  const options =
    job && !choices.some((record) => record.job_id === job.job_id)
      ? [job, ...choices]
      : choices;
  return (
    <Card>
      <CardHeader>
        <h2 className="font-semibold">同步状态</h2>
        <Button
          size="sm"
          variant="ghost"
          onClick={props.onRefresh}
          disabled={props.loading}
        >
          刷新状态
        </Button>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-xs text-[var(--muted)]">
          同步只更新文献信息，不会启动 AI 精读。
        </p>
        {props.message && (
          <p role="status" className="text-xs text-[var(--accent)]">
            {props.message}
          </p>
        )}
        {props.actionError && (
          <p role="alert" className="text-xs text-[var(--danger)]">
            {props.actionError}
          </p>
        )}
        {props.recordsError && (
          <ErrorState message={props.recordsError} onRetry={props.onRefresh} />
        )}
        {props.detailError && (
          <ErrorState message={props.detailError} onRetry={props.onRefresh} />
        )}
        {props.loading && !records ? (
          <LoadingState label="正在读取同步状态…" />
        ) : options.length > 0 ? (
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <label htmlFor="zotero-sync-record" className="text-[var(--muted)]">
              同步记录
            </label>
            <select
              id="zotero-sync-record"
              value={job?.job_id ?? ""}
              onChange={(event) => {
                const selected = options.find(
                  (record) => record.job_id === event.target.value,
                );
                if (selected) props.onSelect(selected);
              }}
              className="max-w-full rounded-md border border-[var(--border)] bg-[var(--surface)] px-2 py-1.5"
            >
              {options.map((record) => (
                <option key={record.job_id} value={record.job_id}>
                  {recordLabel(record)}
                </option>
              ))}
            </select>
            {records && records.total > records.limit && (
              <>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={props.loading || props.recordsOffset === 0}
                  onClick={() =>
                    props.onRecordsOffset(
                      Math.max(0, props.recordsOffset - records.limit),
                    )
                  }
                >
                  上一页记录
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={
                    props.loading ||
                    props.recordsOffset + records.limit >= records.total
                  }
                  onClick={() =>
                    props.onRecordsOffset(props.recordsOffset + records.limit)
                  }
                >
                  下一页记录
                </Button>
              </>
            )}
          </div>
        ) : (
          !props.recordsError && (
            <EmptyState
              title="尚无同步记录"
              detail="连接 Zotero 后可读取全部文献。"
            />
          )
        )}
        {job && (
          <div className="space-y-3 text-xs">
            <div className="flex items-center justify-between gap-3">
              <h3 className="font-semibold">{labels[job.status]}</h3>
              <div className="flex gap-2">
                {["PARTIAL", "FAILED", "CANCELLED"].includes(job.status) && (
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={props.busy}
                    onClick={() => props.onAction("retry")}
                  >
                    继续未完成同步
                  </Button>
                )}
                {["QUEUED", "RUNNING"].includes(job.status) && (
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={props.busy}
                    onClick={() => props.onAction("cancel")}
                  >
                    取消同步
                  </Button>
                )}
              </div>
            </div>
            <div className="grid grid-cols-3 gap-3 rounded-md bg-[var(--background)] p-3">
              <div>
                <span className="text-[var(--muted)]">已处理</span>
                <p className="mt-1 font-semibold tabular-nums">
                  {job.scanned} / {job.total_items}
                </p>
              </div>
              <div>
                <span className="text-[var(--muted)]">本次变更</span>
                <p className="mt-1 font-semibold tabular-nums">
                  新增 {job.created} · 更新 {job.updated}
                </p>
              </div>
              <div>
                <span className="text-[var(--muted)]">需处理</span>
                <p
                  className={`mt-1 font-semibold tabular-nums ${job.failed ? "text-[var(--danger)]" : ""}`}
                >
                  {job.failed}
                </p>
              </div>
            </div>
            {job.total_items > 0 && (
              <progress
                aria-label="同步条目处理进度"
                value={job.scanned}
                max={job.total_items}
                className="h-1.5 w-full accent-[var(--accent)]"
              />
            )}
            {job.status === "QUEUED" && (
              <p role="status" className="text-[var(--muted)]">
                同步已排队，完成后会自动更新。
              </p>
            )}
            {job.status === "RUNNING" && (
              <p role="status" className="text-[var(--muted)]">
                正在同步文献信息，页面会自动更新。
              </p>
            )}
            {job.error_message && (
              <p role="alert" className="text-[var(--danger)]">
                {job.error_message}
              </p>
            )}
            {job.failed > 0 && (
              <div className="space-y-2">
                <Button
                  size="sm"
                  variant="ghost"
                  aria-expanded={props.issuesOpen}
                  onClick={props.onToggleIssues}
                >
                  {props.issuesOpen
                    ? "收起同步异常"
                    : `查看同步异常（${job.failed}）`}
                </Button>
                {props.issuesOpen && (
                  <>
                    {props.issuesError ? (
                      <ErrorState
                        message={props.issuesError}
                        onRetry={props.onReloadIssues}
                      />
                    ) : props.issuesLoading && !props.issues ? (
                      <LoadingState label="正在读取同步异常…" />
                    ) : props.issues?.items.length ? (
                      <div className="space-y-2">
                        {props.issues.items.map((item, index) => (
                          <div
                            key={item.id}
                            className="rounded-md border border-[var(--border)] p-3"
                          >
                            <p className="font-medium">
                              异常 {props.issuesOffset + index + 1}
                            </p>
                            <p className="mt-1 text-[var(--danger)]">
                              {item.error_message ||
                                "该文献同步失败，可继续同步或核对 Zotero 来源。"}
                            </p>
                            {item.paper_id && (
                              <Link
                                href={`/papers/${item.paper_id}`}
                                className="mt-2 inline-block text-[var(--accent)] hover:underline"
                              >
                                查看相关论文
                              </Link>
                            )}
                            {item.candidate_paper_ids.length > 0 && (
                              <div className="mt-2 flex flex-wrap gap-2">
                                <span className="text-[var(--muted)]">
                                  可能重复的论文：
                                </span>
                                {item.candidate_paper_ids.map(
                                  (paperId, candidate) => (
                                    <Link
                                      key={paperId}
                                      href={`/papers/${paperId}`}
                                      className="text-[var(--accent)] underline"
                                    >
                                      查看候选 {candidate + 1}
                                    </Link>
                                  ),
                                )}
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="text-[var(--muted)]">
                        没有可显示的异常详情，请刷新状态。
                      </p>
                    )}
                    {props.issues &&
                      props.issues.total > props.issues.limit && (
                        <div className="flex items-center gap-2 text-[var(--muted)]">
                          <Button
                            size="sm"
                            variant="ghost"
                            disabled={
                              props.issuesLoading || props.issuesOffset === 0
                            }
                            onClick={() =>
                              props.onIssuesOffset(
                                Math.max(
                                  0,
                                  props.issuesOffset - props.issues!.limit,
                                ),
                              )
                            }
                          >
                            上一页异常
                          </Button>
                          <span>
                            {props.issuesOffset + 1}–
                            {Math.min(
                              props.issuesOffset + props.issues.items.length,
                              props.issues.total,
                            )}{" "}
                            / {props.issues.total}
                          </span>
                          <Button
                            size="sm"
                            variant="ghost"
                            disabled={
                              props.issuesLoading ||
                              props.issuesOffset + props.issues.limit >=
                                props.issues.total
                            }
                            onClick={() =>
                              props.onIssuesOffset(
                                props.issuesOffset + props.issues!.limit,
                              )
                            }
                          >
                            下一页异常
                          </Button>
                        </div>
                      )}
                  </>
                )}
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
