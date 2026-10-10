"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { ArrowLeft, GitCompareArrows } from "lucide-react";

import { RunProvenance } from "@/components/experiments/run-provenance";
import { RunMetrics } from "@/components/experiments/run-metrics";
import { RunArtifacts } from "@/components/experiments/run-artifacts";
import { RunStatusHistory } from "@/components/experiments/run-status-history";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input, Textarea } from "@/components/ui/input";
import { ErrorState, LoadingState } from "@/components/ui/state";
import { api } from "@/lib/api";
import type { ExperimentRun, ExperimentRunPatch } from "@/lib/experiments";

const statuses = [
  "PLANNED",
  "RUNNING",
  "COMPLETED",
  "FAILED",
  "STOPPED",
  "ARCHIVED",
] as const;

function dateText(value: string | null | undefined) {
  return value ? new Date(value).toLocaleString("zh-CN") : "未记录";
}

export default function ExperimentRunPage() {
  const { id } = useParams<{ id: string }>();
  const [run, setRun] = useState<ExperimentRun | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState("");
  const [status, setStatus] = useState<ExperimentRun["status"]>("PLANNED");
  const [notes, setNotes] = useState("");
  const [conclusion, setConclusion] = useState("");
  const [reason, setReason] = useState("");
  const requestId = useRef(0);

  const load = useCallback(() => {
    const request = ++requestId.current;
    setLoading(true);
    setError("");
    api
      .get<ExperimentRun>(`/experiment-runs/${id}`)
      .then((value) => {
        if (request !== requestId.current) return;
        setRun(value);
        setStatus(value.status);
        setNotes(value.notes ?? "");
        setConclusion(value.conclusion ?? "");
      })
      .catch((cause) => {
        if (request === requestId.current)
          setError(cause instanceof Error ? cause.message : "无法读取运行详情");
      })
      .finally(() => {
        if (request === requestId.current) setLoading(false);
      });
  }, [id]);

  useEffect(() => {
    let active = true;
    const controller = requestId;
    queueMicrotask(() => {
      if (active) load();
    });
    return () => {
      active = false;
      controller.current++;
    };
  }, [load]);

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!run) return;
    setSaving(true);
    setError("");
    setSaved("");
    const body: ExperimentRunPatch = {
      status,
      notes: notes.trim() || null,
      conclusion: conclusion.trim() || null,
      reason: reason.trim() || null,
    };
    try {
      const updated = await api.patch<ExperimentRun>(
        `/experiment-runs/${id}`,
        body,
      );
      setRun(updated);
      setStatus(updated.status);
      setNotes(updated.notes ?? "");
      setConclusion(updated.conclusion ?? "");
      setReason("");
      setSaved("运行状态与记录已保存。");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "保存运行记录失败");
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <LoadingState label="正在读取实验运行…" />;
  if (!run)
    return <ErrorState message={error || "运行不存在"} onRetry={load} />;

  return (
    <div className="space-y-6">
      <Link
        href={`/experiments/${run.experiment_id}`}
        className="inline-flex items-center gap-2 text-xs text-[var(--muted)] hover:text-[var(--accent)]"
      >
        <ArrowLeft className="h-4 w-4" />
        返回实验设计
      </Link>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="mb-1 text-xs uppercase tracking-[0.18em] text-[var(--accent)]">
            Experiment run
          </p>
          <h1 className="text-2xl font-semibold">实验运行 #{run.run_number}</h1>
          <p className="mt-2 break-all font-mono text-xs text-[var(--muted)]">
            {run.id}
          </p>
        </div>
        <Button asChild variant="secondary">
          <Link href={`/experiments/compare?run_id=${run.id}`}>
            <GitCompareArrows className="h-4 w-4" />
            比较运行
          </Link>
        </Button>
      </div>
      {error && <ErrorState message={error} />}
      {saved && (
        <p
          role="status"
          className="text-sm text-emerald-600 dark:text-emerald-400"
        >
          {saved}
        </p>
      )}
      <div className="grid gap-3 sm:grid-cols-3">
        {[
          ["当前状态", run.status],
          ["开始时间", dateText(run.started_at)],
          ["结束时间", dateText(run.ended_at)],
        ].map(([label, value]) => (
          <Card key={label}>
            <CardContent>
              <p className="text-xs text-[var(--muted)]">{label}</p>
              <p className="mt-2 text-sm font-medium">{value}</p>
            </CardContent>
          </Card>
        ))}
      </div>
      <RunProvenance run={run} />
      <Card>
        <CardHeader>
          <div>
            <h2 className="font-semibold">外部运行记录</h2>
            <p className="mt-1 text-xs text-[var(--muted)]">
              记录你在外部执行的实验；保存状态不会启动训练或运行代码。
            </p>
          </div>
        </CardHeader>
        <CardContent>
          <form onSubmit={save} className="grid gap-4 md:grid-cols-2">
            <label className="space-y-1.5 text-xs font-medium">
              运行状态
              <select
                aria-label="运行状态"
                value={status}
                onChange={(event) =>
                  setStatus(event.target.value as ExperimentRun["status"])
                }
                className="block h-9 w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-3 text-sm"
              >
                {statuses.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>
            <label className="space-y-1.5 text-xs font-medium">
              状态变更原因
              <Input
                maxLength={2000}
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                placeholder="例如：外部训练完成，测试集评估已记录"
              />
            </label>
            <label className="space-y-1.5 text-xs font-medium">
              运行备注
              <Textarea
                maxLength={20000}
                value={notes}
                onChange={(event) => setNotes(event.target.value)}
              />
            </label>
            <label className="space-y-1.5 text-xs font-medium">
              结果与结论
              <Textarea
                maxLength={20000}
                value={conclusion}
                onChange={(event) => setConclusion(event.target.value)}
              />
            </label>
            <div className="md:col-span-2">
              <Button disabled={saving} type="submit">
                {saving ? "保存中…" : "保存运行记录"}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
      <RunMetrics runId={id} archived={run.status === "ARCHIVED"} />
      <RunArtifacts runId={id} />
      <RunStatusHistory runId={id} status={run.status} />
    </div>
  );
}
