"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { ExperimentDesignForm } from "@/components/experiments/experiment-form";
import { api } from "@/lib/api";
import { experimentStatusLabels, type ExperimentPage } from "@/lib/experiments";
export default function ExperimentsPage() {
  const router = useRouter();
  const [page, setPage] = useState<ExperimentPage | null>(null);
  const [offset, setOffset] = useState(0);
  const [createMounted, setCreateMounted] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    setLoading(true);
    try {
      setPage(
        await api.get<ExperimentPage>("/experiments?limit=20&offset=" + offset),
      );
      setError("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "无法读取实验设计");
    } finally {
      setLoading(false);
    }
  }, [offset]);
  useEffect(() => {
    queueMicrotask(() => void load());
  }, [load]);
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap justify-between gap-3">
        <div>
          <p className="mb-1 text-xs uppercase tracking-[0.18em] text-[var(--accent)]">
            Experiment manager
          </p>
          <h1 className="text-2xl font-semibold">实验管理</h1>
          <p className="mt-1 text-sm text-[var(--muted)]">
            从研究问题到可追溯的外部运行记录，保留版本、指标和实际产物。
          </p>
        </div>
        <Link
          href="/experiments/compare"
          className="text-sm text-[var(--accent)] hover:underline"
        >
          比较实验运行 →
        </Link>
      </div>
      {error && <ErrorState message={error} onRetry={() => void load()} />}

      <Card>
        <CardHeader>
          <h2 className="font-semibold">实验设计记录</h2>
          <Button
            size="sm"
            variant="ghost"
            disabled={loading}
            onClick={() => void load()}
          >
            刷新
          </Button>
        </CardHeader>
        <CardContent>
          {loading && !page ? (
            <LoadingState />
          ) : page?.items.length ? (
            <div className="divide-y divide-[var(--border)]">
              {page.items.map((experiment) => (
                <Link
                  key={experiment.id}
                  href={"/experiments/" + experiment.id}
                  className="flex flex-wrap justify-between gap-3 py-3 text-sm hover:text-[var(--accent)]"
                >
                  <span>
                    <span className="block font-medium">{experiment.name}</span>
                    <span className="mt-1 block text-xs text-[var(--muted)]">
                      {experiment.experiment_code}
                    </span>
                  </span>
                  <span className="text-xs text-[var(--muted)]">
                    {experimentStatusLabels[experiment.status]}
                  </span>
                </Link>
              ))}
            </div>
          ) : (
            !error && (
              <EmptyState
                title="尚无实验设计"
                detail="先选择研究课题与待验证问题，登记第一项设计。"
              />
            )
          )}
          {page && (
            <div className="mt-4 flex items-center justify-between gap-3 text-xs text-[var(--muted)]">
              <Button
                size="sm"
                variant="ghost"
                disabled={loading || offset === 0}
                onClick={() => setOffset(Math.max(0, offset - page.limit))}
              >
                上一页实验
              </Button>
              <span>共 {page.total} 项</span>
              <Button
                size="sm"
                variant="ghost"
                disabled={loading || offset + page.limit >= page.total}
                onClick={() => setOffset(offset + page.limit)}
              >
                下一页实验
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
      <details
        className="rounded-md border border-[var(--border)] bg-[var(--surface)]"
        onToggle={(event) => {
          if (event.currentTarget.open) setCreateMounted(true);
        }}
      >
        <summary className="cursor-pointer px-4 py-3 text-sm font-medium">
          新建实验设计
        </summary>
        {createMounted && (
          <>
            {" "}
            <Card>
              <CardHeader>
                <h2 className="font-semibold">新建实验设计</h2>
              </CardHeader>
              <CardContent>
                <ExperimentDesignForm
                  onCreated={(experiment) =>
                    router.push("/experiments/" + experiment.id)
                  }
                />
              </CardContent>
            </Card>
          </>
        )}
      </details>
    </div>
  );
}
