"use client";
import { useRef, useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/input";
import { IdeaSourcePicker } from "@/components/ideas/source-picker";
import type { Source } from "@/components/ideas/types";
import {
  message,
  relations,
  type Evidence,
  type ResultSources,
  type ServerResult,
} from "./types";
export function EvidencePicker({
  projectId,
  values,
  onChange,
  disabled,
}: {
  projectId: string;
  values: Evidence[];
  onChange: (v: Evidence[]) => void;
  disabled: boolean;
}) {
  const [page, setPage] = useState<ResultSources | null>(null),
    [result, setResult] = useState<ServerResult | null>(null);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [observation, setObservation] = useState(""),
    [rationale, setRationale] = useState("");
  const [relation, setRelation] = useState<Evidence["relation"]>("CONTEXT");
  const seq = useRef(0);
  function add(rows: Evidence[]) {
    if (values.length + rows.length > 40) {
      setError("每个版本最多40项证据。");
      return;
    }
    onChange([...values, ...rows]);
    setError("");
  }
  async function load(cursor?: string | null) {
    const at = ++seq.current;
    setBusy(true);
    setError("");
    try {
      const next = await api.get<ResultSources>(
        `/claims/result-sources?project_id=${projectId}&limit=20${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
      );
      if (at === seq.current) setPage(next);
    } catch (cause) {
      if (at === seq.current) setError(message(cause));
    } finally {
      if (at === seq.current) setBusy(false);
    }
  }
  async function open(id: string) {
    const at = ++seq.current;
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const next = await api.get<ServerResult>(
        `/projects/${projectId}/server-results/${id}`,
      );
      if (at === seq.current) setResult(next);
    } catch (cause) {
      if (at === seq.current) setError(message(cause));
    } finally {
      if (at === seq.current) setBusy(false);
    }
  }
  function noteChange(rows: Source[]) {
    const other = values.filter((v) => v.source_kind !== "CANONICAL_QUOTE");
    if (other.length + rows.length > 40) {
      setError("每个版本最多40项证据。");
      return;
    }
    const selected = rows.map(
      (row) =>
        values.find(
          (v) =>
            v.source_kind === "CANONICAL_QUOTE" &&
            v.canonical_note_id === row.canonical_note_id &&
            v.expected_note_sha256 === row.expected_note_sha256 &&
            v.start_offset === row.start_offset &&
            v.end_offset === row.end_offset &&
            v.exact_quote === row.exact_quote,
        ) ?? {
          source_kind: "CANONICAL_QUOTE" as const,
          relation,
          rationale,
          ...row,
        },
    );
    onChange([...other, ...selected]);
    setError("");
  }
  const notes: Source[] = values
    .filter((v) => v.source_kind === "CANONICAL_QUOTE")
    .map((v) => ({
      canonical_note_id: v.canonical_note_id!,
      expected_note_sha256: v.expected_note_sha256!,
      start_offset: v.start_offset!,
      end_offset: v.end_offset!,
      exact_quote: v.exact_quote!,
    }));
  return (
    <section className="space-y-3 rounded border p-3" aria-label="科研证据选择">
      <h3 className="font-medium">来源与关系</h3>
      <div className="grid gap-2 sm:grid-cols-2">
        <label className="text-sm">
          新增证据关系
          <select
            aria-label="新增证据关系"
            value={relation}
            disabled={disabled}
            onChange={(e) =>
              setRelation(e.target.value as Evidence["relation"])
            }
            className="block w-full rounded border bg-[var(--surface)] p-2"
          >
            {relations.map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          关系理由
          <Textarea
            value={rationale}
            disabled={disabled}
            onChange={(e) => setRationale(e.target.value)}
            maxLength={4000}
          />
        </label>
      </div>
      <details>
        <summary>选择服务器结果的真实指标或文件</summary>
        <div className="mt-2 space-y-2">
          <Button
            type="button"
            disabled={disabled || busy}
            onClick={() => void load()}
          >
            读取结果来源
          </Button>
          {busy && <p role="status">读取来源中…</p>}
          {page && !page.items.length && (
            <p>暂无可用结果。先从课题服务器结果页导入报告。</p>
          )}
          {page?.items.map((row) => (
            <div
              key={row.id}
              className="flex flex-wrap items-center gap-2 rounded border p-2 text-xs"
            >
              <span>
                {row.receipt_id} · 声明状态 {row.claimed_run_status} ·{" "}
                {row.origin_verification} · {row.validation_status}
              </span>
              <Button
                type="button"
                size="sm"
                disabled={disabled || busy || !row.integrity_valid}
                onClick={() => void open(row.id)}
              >
                查看指标与文件
              </Button>
            </div>
          ))}
          {page?.page.next_cursor && (
            <Button
              type="button"
              disabled={disabled || busy}
              onClick={() => void load(page.page.next_cursor)}
            >
              下一页结果来源
            </Button>
          )}
          {result && (
            <div className="space-y-2">
              <p className="break-all text-xs">
                结果SHA {result.result_sha256} ·{" "}
                {result.gaps.join("；") || "未报告材料缺口"}
              </p>
              <p className="text-xs">
                声明运行失败的材料也可以作为反证。文件和签名匹配不自动证明科学有效。
              </p>
              {result.metrics.map((row) => (
                <div
                  key={row.id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded border p-2 text-sm"
                >
                  <span>
                    {row.name}: {row.value} {row.unit} ·{" "}
                    {row.split || "未指定split"}
                    <br />
                    <small>{row.evaluation_protocol || "未记录评价协议"}</small>
                  </span>
                  <Button
                    type="button"
                    size="sm"
                    disabled={
                      disabled ||
                      values.some(
                        (v) =>
                          v.metric_id === row.id && v.relation === relation,
                      )
                    }
                    onClick={() =>
                      add([
                        {
                          source_kind: "RESULT_METRIC",
                          relation,
                          rationale,
                          result_id: result.id,
                          expected_result_sha256: result.result_sha256,
                          metric_id: row.id,
                        },
                      ])
                    }
                  >
                    加入指标证据
                  </Button>
                </div>
              ))}
              {result.artifacts.map((row) => (
                <div
                  key={row.id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded border p-2 text-sm"
                >
                  <span>
                    {row.path} · {row.verification}
                  </span>
                  <Button
                    type="button"
                    size="sm"
                    disabled={
                      disabled ||
                      values.some(
                        (v) =>
                          v.artifact_id === row.id && v.relation === relation,
                      )
                    }
                    onClick={() =>
                      add([
                        {
                          source_kind: "RESULT_ARTIFACT",
                          relation,
                          rationale,
                          result_id: result.id,
                          expected_result_sha256: result.result_sha256,
                          artifact_id: row.id,
                        },
                      ])
                    }
                  >
                    加入文件证据
                  </Button>
                </div>
              ))}
            </div>
          )}
        </div>
      </details>
      <IdeaSourcePicker
        projectId={projectId}
        selections={notes}
        onChange={noteChange}
        disabled={disabled || values.length >= 40}
      />
      <details>
        <summary>本人观察（尚未独立验证）</summary>
        <label className="block text-sm">
          观察原文
          <Textarea
            value={observation}
            disabled={disabled}
            onChange={(e) => setObservation(e.target.value)}
            maxLength={20000}
          />
        </label>
        <Button
          type="button"
          disabled={disabled || !observation.trim()}
          onClick={() => {
            add([
              {
                source_kind: "OWNER_OBSERVATION",
                relation,
                rationale,
                observation,
              },
            ]);
            setObservation("");
          }}
        >
          加入本人观察
        </Button>
      </details>
      {error && (
        <p role="alert" className="text-sm text-[var(--danger)]">
          {error}
        </p>
      )}
      <div className="space-y-2">
        {values.map((v, i) => (
          <div key={i} className="rounded border p-2 text-xs">
            <p>
              {relations.find(([key]) => key === v.relation)?.[1]} ·{" "}
              {v.source_kind} ·{" "}
              {v.metric_id ||
                v.artifact_id ||
                v.canonical_note_id ||
                "本人观察"}
            </p>
            <pre className="max-h-32 overflow-auto whitespace-pre-wrap">
              {v.exact_quote || v.observation || v.rationale}
            </pre>
            <div className="flex flex-wrap gap-2">
              <select
                aria-label={`证据${i + 1}关系`}
                value={v.relation}
                disabled={disabled}
                onChange={(e) =>
                  onChange(
                    values.map((row, index) =>
                      index === i
                        ? {
                            ...row,
                            relation: e.target.value as Evidence["relation"],
                          }
                        : row,
                    ),
                  )
                }
              >
                {relations.map(([key, label]) => (
                  <option key={key} value={key}>
                    {label}
                  </option>
                ))}
              </select>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                disabled={disabled}
                onClick={() =>
                  onChange(values.filter((_, index) => index !== i))
                }
              >
                移除证据 {i + 1}
              </Button>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
