"use client";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ErrorState, LoadingState } from "@/components/ui/state";
import { RegistryText } from "@/components/registries/fields";
import { api } from "@/lib/api";
import {
  nullableText,
  type Hypothesis,
  type HypothesisPatch,
} from "@/lib/experiments";
const labels = {
  UNTESTED: "尚未检验",
  SUPPORTED: "获得支持",
  REFUTED: "已反驳",
  INCONCLUSIVE: "证据不足",
  ARCHIVED: "已归档",
} as const;
export function HypothesisReview({ hypothesisId }: { hypothesisId: string }) {
  const [hypothesis, setHypothesis] = useState<Hypothesis | null>(null);
  const [status, setStatus] = useState<Hypothesis["status"]>("UNTESTED");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    try {
      const record = await api.get<Hypothesis>("/hypotheses/" + hypothesisId);
      setHypothesis(record);
      setStatus(record.status);
      setNotes(record.result_notes ?? "");
      setError("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "无法读取研究假设");
    }
  }, [hypothesisId]);
  useEffect(() => {
    queueMicrotask(() => void load());
  }, [load]);
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const patch: HypothesisPatch = {
        status,
        result_notes: nullableText(notes),
      };
      setHypothesis(
        await api.patch<Hypothesis>("/hypotheses/" + hypothesisId, patch),
      );
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "更新假设判断失败");
    } finally {
      setBusy(false);
    }
  }
  return (
    <Card>
      <CardHeader>
        <h2 className="font-semibold">假设与人工证据判断</h2>
      </CardHeader>
      <CardContent className="space-y-4">
        {error && <ErrorState message={error} onRetry={() => void load()} />}
        {!hypothesis && !error ? (
          <LoadingState />
        ) : (
          hypothesis && (
            <>
              <p className="text-sm leading-6">{hypothesis.statement}</p>
              {hypothesis.test_plan && (
                <p className="whitespace-pre-wrap text-xs leading-5 text-[var(--muted)]">
                  {hypothesis.test_plan}
                </p>
              )}
              <form onSubmit={submit} className="space-y-3">
                <label className="block space-y-1.5 text-xs font-medium">
                  假设判断
                  <select
                    aria-label="假设判断"
                    value={status}
                    onChange={(event) =>
                      setStatus(event.target.value as Hypothesis["status"])
                    }
                    disabled={busy}
                    className="h-10 w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-3 text-sm"
                  >
                    {Object.entries(labels).map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
                <RegistryText
                  label="假设证据与判断说明"
                  value={notes}
                  onChange={(event) => setNotes(event.target.value)}
                  required={["SUPPORTED", "REFUTED", "INCONCLUSIVE"].includes(
                    status,
                  )}
                  maxLength={20000}
                />
                <p className="text-xs leading-5 text-[var(--muted)]">
                  运行完成与假设获得支持分别记录。支持、反驳或证据不足时，请写明依据和结论边界。
                </p>
                <Button type="submit" disabled={busy}>
                  {busy ? "保存中…" : "更新假设判断"}
                </Button>
              </form>
            </>
          )
        )}
      </CardContent>
    </Card>
  );
}
