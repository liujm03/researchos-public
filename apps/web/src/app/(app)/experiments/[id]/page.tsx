"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { RegistryField, RegistryText } from "@/components/registries/fields";
import { ExperimentRunForm } from "@/components/experiments/run-form";
import { HypothesisReview } from "@/components/experiments/hypothesis-review";
import { api } from "@/lib/api";
import {
  experimentStatusLabels,
  experimentStatuses,
  nullableText,
  type Experiment,
  type ExperimentPatch,
  type ExperimentRunPage,
  type ExperimentStatusEventPage,
} from "@/lib/experiments";

export default function ExperimentDetailPage() {
  const { id } = useParams<{ id: string }>();
  return <ExperimentView key={id} id={id} />;
}
function ExperimentView({ id }: { id: string }) {
  const router = useRouter();
  const [experiment, setExperiment] = useState<Experiment | null>(null);
  const [runs, setRuns] = useState<ExperimentRunPage | null>(null);
  const [history, setHistory] = useState<ExperimentStatusEventPage | null>(
    null,
  );
  const [historyError, setHistoryError] = useState("");
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [name, setName] = useState("");
  const [objective, setObjective] = useState("");
  const [conclusion, setConclusion] = useState("");
  const [status, setStatus] = useState<Experiment["status"]>("PLANNED");
  const [reason, setReason] = useState("");
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [record, runPage] = await Promise.all([
        api.get<Experiment>("/experiments/" + id),
        api.get<ExperimentRunPage>(
          "/experiments/" + id + "/runs?limit=20&offset=" + offset,
        ),
      ]);
      setExperiment(record);
      setRuns(runPage);
      setName(record.name);
      setObjective(record.objective ?? "");
      setConclusion(record.conclusion ?? "");
      setStatus(record.status);
      setError("");
      try {
        setHistory(
          await api.get<ExperimentStatusEventPage>(
            "/experiments/" + id + "/status-history?limit=100&offset=0",
          ),
        );
        setHistoryError("");
      } catch (cause) {
        setHistoryError(
          cause instanceof Error ? cause.message : "状态历史暂不可用",
        );
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "无法读取实验设计");
    } finally {
      setLoading(false);
    }
  }, [id, offset]);
  useEffect(() => {
    queueMicrotask(() => void load());
  }, [load]);
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const patch: ExperimentPatch = {
        name: name.trim(),
        objective: nullableText(objective),
        status,
        conclusion: nullableText(conclusion),
        reason: nullableText(reason),
      };
      setExperiment(await api.patch<Experiment>("/experiments/" + id, patch));
      setReason("");
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "保存实验设计失败");
    } finally {
      setBusy(false);
    }
  }
  if (loading && !experiment) return <LoadingState />;
  if (!experiment)
    return (
      <ErrorState message={error || "实验不存在"} onRetry={() => void load()} />
    );
  return (
    <div className="space-y-6">
      <Link
        href="/experiments"
        className="inline-flex items-center gap-2 text-xs text-[var(--muted)] hover:text-[var(--accent)]"
      >
        <ArrowLeft className="h-4 w-4" />
        返回实验管理
      </Link>
      <div className="flex flex-wrap justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">{experiment.name}</h1>
          <p className="mt-2 text-sm text-[var(--muted)]">
            {experiment.experiment_code} ·{" "}
            {experimentStatusLabels[experiment.status]}
          </p>
          <Link
            href={"/projects/" + experiment.project_id}
            className="mt-2 inline-block text-xs text-[var(--accent)] hover:underline"
          >
            查看所属课题 →
          </Link>
          {experiment.question_id && (
            <p className="mt-1 break-all text-xs text-[var(--muted)]">
              研究问题 ID：{experiment.question_id}
            </p>
          )}
        </div>
        <Link
          href="/experiments/compare"
          className="text-sm text-[var(--accent)] hover:underline"
        >
          比较运行 →
        </Link>
      </div>
      {error && <ErrorState message={error} onRetry={() => void load()} />}
      <Card>
        <CardHeader>
          <h2 className="font-semibold">实验设计与结论</h2>
        </CardHeader>
        <CardContent>
          <form onSubmit={submit} className="space-y-4">
            <fieldset disabled={busy} className="space-y-4">
              <RegistryField
                label="实验名称"
                required
                value={name}
                onChange={(event) => setName(event.target.value)}
                maxLength={240}
              />
              <RegistryText
                label="实验目标"
                value={objective}
                onChange={(event) => setObjective(event.target.value)}
                maxLength={20000}
              />
              <label className="block space-y-1.5 text-xs font-medium">
                设计状态
                <select
                  aria-label="实验设计状态"
                  value={status}
                  onChange={(event) =>
                    setStatus(event.target.value as Experiment["status"])
                  }
                  className="h-10 w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-3 text-sm"
                >
                  {experimentStatuses.map((value) => (
                    <option key={value} value={value}>
                      {experimentStatusLabels[value]}
                    </option>
                  ))}
                </select>
              </label>
              <RegistryText
                label="实验结论与边界"
                value={conclusion}
                onChange={(event) => setConclusion(event.target.value)}
                maxLength={20000}
              />
              <RegistryField
                label="状态变更原因（可空）"
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                maxLength={2000}
              />
              <Button type="submit" disabled={busy}>
                {busy ? "保存中…" : "保存实验设计"}
              </Button>
            </fieldset>
          </form>
        </CardContent>
      </Card>
      {experiment.hypothesis_id && (
        <HypothesisReview hypothesisId={experiment.hypothesis_id} />
      )}
      <Card>
        <CardHeader>
          <h2 className="font-semibold">登记一次运行</h2>
        </CardHeader>
        <CardContent>
          <ExperimentRunForm
            experimentId={id}
            onCreated={(run) => router.push("/experiment-runs/" + run.id)}
          />
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <h2 className="font-semibold">运行记录</h2>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => void load()}
            disabled={loading}
          >
            刷新
          </Button>
        </CardHeader>
        <CardContent>
          {runs?.items.length ? (
            <div className="divide-y divide-[var(--border)]">
              {runs.items.map((run) => (
                <Link
                  key={run.id}
                  href={"/experiment-runs/" + run.id}
                  className="flex flex-wrap justify-between gap-3 py-3 text-sm hover:text-[var(--accent)]"
                >
                  <span>
                    运行 #{run.run_number}
                    <span className="ml-2 text-xs text-[var(--muted)]">
                      Seed {run.random_seed ?? "未记录"} ·{" "}
                      {run.gpu ?? "硬件未记录"}
                    </span>
                  </span>
                  <span className="text-xs text-[var(--muted)]">
                    {experimentStatusLabels[run.status]}
                  </span>
                </Link>
              ))}
            </div>
          ) : (
            !error && (
              <EmptyState
                title="尚无运行记录"
                detail="登记版本、数据用途、随机种子和环境后再维护实测结果。"
              />
            )
          )}
          {runs && (
            <div className="mt-4 flex items-center justify-between gap-3 text-xs text-[var(--muted)]">
              <Button
                size="sm"
                variant="ghost"
                disabled={loading || offset === 0}
                onClick={() => setOffset(Math.max(0, offset - runs.limit))}
              >
                上一页运行
              </Button>
              <span>共 {runs.total} 次运行</span>
              <Button
                size="sm"
                variant="ghost"
                disabled={loading || offset + runs.limit >= runs.total}
                onClick={() => setOffset(offset + runs.limit)}
              >
                下一页运行
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <h2 className="font-semibold">设计状态历史</h2>
        </CardHeader>
        <CardContent>
          {historyError ? (
            <ErrorState message={historyError} onRetry={() => void load()} />
          ) : history?.items.length ? (
            <ol className="space-y-3 text-xs">
              {history.items.map((event) => (
                <li key={event.id}>
                  <p>
                    {event.from_status
                      ? experimentStatusLabels[event.from_status] + " → "
                      : ""}
                    {experimentStatusLabels[event.to_status]} ·{" "}
                    {new Date(event.changed_at).toLocaleString("zh-CN")}
                  </p>
                  {event.reason && (
                    <p className="mt-1 text-[var(--muted)]">{event.reason}</p>
                  )}
                </li>
              ))}
            </ol>
          ) : (
            <EmptyState title="尚无状态历史" />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
