"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { api } from "@/lib/api";
import type { ExperimentStatusEventPage } from "@/lib/experiments";

export function RunStatusHistory({
  runId,
  status,
}: {
  runId: string;
  status: string;
}) {
  const [page, setPage] = useState<ExperimentStatusEventPage | null>(null);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const generation = useRef(0);
  const load = useCallback(async () => {
    const request = ++generation.current;
    setLoading(true);
    setError("");
    try {
      const result = await api.get<ExperimentStatusEventPage>(
        `/experiment-runs/${runId}/status-history?limit=20&offset=${offset}`,
      );
      if (request === generation.current) setPage(result);
    } catch (cause) {
      if (request === generation.current)
        setError(cause instanceof Error ? cause.message : "无法读取状态历史");
    } finally {
      if (request === generation.current) setLoading(false);
    }
  }, [runId, offset]);
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
  }, [load, status]);

  return (
    <Card>
      <CardHeader>
        <h2 className="font-semibold">状态历史</h2>
      </CardHeader>
      <CardContent className="space-y-3">
        {error && (
          <ErrorState
            message={error}
            onRetry={() => {
              void load();
            }}
          />
        )}
        {loading ? (
          <LoadingState label="正在读取状态历史…" />
        ) : page?.items.length ? (
          <ol className="space-y-3">
            {page.items.map((event) => (
              <li
                key={event.id}
                className="border-l-2 border-[var(--border)] pl-3"
              >
                <p className="text-xs font-medium">
                  {event.from_status ?? "创建"} → {event.to_status}
                </p>
                <p className="mt-1 text-xs text-[var(--muted)]">
                  {new Date(event.changed_at).toLocaleString("zh-CN")}
                </p>
                {event.reason && (
                  <p className="mt-1 whitespace-pre-wrap text-xs leading-5">
                    {event.reason}
                  </p>
                )}
              </li>
            ))}
          </ol>
        ) : (
          <EmptyState title="尚无状态历史" />
        )}
        {page && page.total > 20 && (
          <div className="flex items-center justify-between gap-3">
            <p className="text-xs text-[var(--muted)]">
              {offset + 1}–{Math.min(offset + page.items.length, page.total)} /{" "}
              {page.total}
            </p>
            <div className="flex gap-2">
              <Button
                variant="secondary"
                size="sm"
                disabled={loading || offset === 0}
                onClick={() => setOffset(Math.max(0, offset - 20))}
              >
                较新的记录
              </Button>
              <Button
                variant="secondary"
                size="sm"
                disabled={loading || offset + page.items.length >= page.total}
                onClick={() => setOffset(offset + 20)}
              >
                较早的记录
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
