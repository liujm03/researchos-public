"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";
import { message } from "../types";
import type { Result, ResultPage, Selection, Figure, Table } from "./types";
export function BuildMaterials({
  endpoint,
  projectId,
  value,
  busy,
  onChange,
}: {
  endpoint: string;
  projectId: string;
  value: Selection;
  busy: boolean;
  onChange: (value: Selection) => void;
}) {
  const [page, setPage] = useState<ResultPage | null>(null),
    [result, setResult] = useState<Result | null>(null),
    [loading, setLoading] = useState(false),
    [error, setError] = useState(""),
    [artifact, setArtifact] = useState(""),
    [path, setPath] = useState("figures/figure1.png"),
    [caption, setCaption] = useState(""),
    [tableKey, setTableKey] = useState("results"),
    [tableTitle, setTableTitle] = useState(""),
    [metricIds, setMetricIds] = useState<string[]>([]);
  async function list(cursor?: string | null) {
    setLoading(true);
    setError("");
    try {
      setPage(
        await api.get<ResultPage>(
          `${endpoint}/result-sources?limit=20${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
        ),
      );
    } catch (cause) {
      setError(message(cause));
    } finally {
      setLoading(false);
    }
  }
  async function open(id: string) {
    setLoading(true);
    setError("");
    try {
      const value = await api.get<Result>(`${endpoint}/result-sources/${id}`);
      if (value.project_id !== projectId)
        throw new Error("服务器结果不属于当前课题。");
      setResult(value);
      setArtifact("");
      setMetricIds([]);
    } catch (cause) {
      setError(message(cause));
    } finally {
      setLoading(false);
    }
  }
  function addFigure() {
    const source = result?.artifacts.find((a) => a.id === artifact);
    if (
      !result ||
      !source ||
      source.verification !== "BYTES_VERIFIED" ||
      !source.actual_sha256
    ) {
      setError("只能选择已经校验实际附件字节的图来源。");
      return;
    }
    const figure: Figure = {
      result_id: result.id,
      artifact_id: source.id,
      expected_result_sha256: result.result_sha256,
      expected_artifact_sha256: source.actual_sha256,
      path,
      caption,
    };
    onChange({ ...value, figures: [...value.figures, figure] });
    setCaption("");
  }
  function addTable() {
    if (!result) return;
    const table: Table = {
      key: tableKey,
      title: tableTitle,
      metrics: metricIds.map((metric_id) => ({
        result_id: result.id,
        metric_id,
        expected_result_sha256: result.result_sha256,
      })),
    };
    onChange({ ...value, tables: [...value.tables, table] });
    setMetricIds([]);
    setTableTitle("");
  }
  return (
    <section className="space-y-3" aria-label="构建图表来源">
      <h3 className="font-medium">本人选择真实图附件与原指标</h3>
      <p className="text-xs text-[var(--muted)]">
        保留来源
        SHA、原单位/划分/评价协议；不计算跨协议均值，不从元数据伪造图文件。
      </p>
      <Button
        size="sm"
        variant="secondary"
        disabled={busy || loading}
        onClick={() => void list()}
      >
        读取图表结果来源
      </Button>
      {loading && <p role="status">读取结果来源中…</p>}
      {error && <p role="alert">{error}</p>}
      {page?.items.map((r) => (
        <Button
          key={r.id}
          size="sm"
          variant="ghost"
          disabled={busy || loading}
          onClick={() => void open(r.id)}
        >
          选择结果 {r.receipt_id} · {r.claimed_run_status}
        </Button>
      ))}
      {page && !page.items.length && (
        <p className="text-xs">暂无服务器结果来源，可先构建正文草稿。</p>
      )}
      {page?.page.next_cursor && (
        <Button
          size="sm"
          disabled={busy || loading}
          onClick={() => void list(page.page.next_cursor)}
        >
          下一页结果来源
        </Button>
      )}
      {result && (
        <div className="space-y-3 rounded border p-3">
          <p className="text-sm">
            {result.receipt_id} · 本人审阅 {result.review_status} · 运行状态{" "}
            {result.claimed_run_status}
          </p>
          <dl className="space-y-1 break-all text-xs">
            {[
              ["结果SHA", result.result_sha256],
              ["协议SHA", result.protocol_sha256],
              ["配置SHA", result.config_sha256],
              ["数据SHA", result.dataset_sha256],
              ["Git Commit", result.git_commit],
            ].map(([k, v]) => (
              <div key={k!}>
                <dt className="inline font-medium">{k}：</dt>
                <dd className="inline">{v ?? "未知"}</dd>
              </div>
            ))}
          </dl>
          <div className="grid gap-3 md:grid-cols-2">
            <label>
              图Artifact
              <select
                aria-label="图Artifact"
                className="block w-full rounded border p-2"
                disabled={busy}
                value={artifact}
                onChange={(e) => setArtifact(e.target.value)}
              >
                <option value="">选择实际校验的图附件</option>
                {result.artifacts.map((a) => (
                  <option
                    key={a.id}
                    value={a.id}
                    disabled={
                      a.verification !== "BYTES_VERIFIED" ||
                      !a.actual_sha256 ||
                      !["image/png", "image/jpeg", "application/pdf"].includes(
                        a.mime_type,
                      )
                    }
                  >
                    {a.path} · {a.verification} · {a.mime_type}
                  </option>
                ))}
              </select>
            </label>
            <label>
              工程图文件路径
              <Input
                aria-label="工程图文件路径"
                disabled={busy}
                value={path}
                onChange={(e) => setPath(e.target.value)}
                placeholder="figures/figure1.png"
              />
            </label>
            <label className="md:col-span-2">
              英文图Caption
              <Textarea
                aria-label="英文图Caption"
                disabled={busy}
                value={caption}
                onChange={(e) => setCaption(e.target.value)}
              />
            </label>
          </div>
          <Button
            size="sm"
            disabled={busy || !artifact || !caption.trim()}
            onClick={addFigure}
          >
            加入图附件
          </Button>
          <h4 className="text-sm font-medium">原始指标定义</h4>
          <div className="overflow-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr>
                  <th>选用</th>
                  <th>指标</th>
                  <th>值</th>
                  <th>单位</th>
                  <th>划分</th>
                  <th>评价协议</th>
                </tr>
              </thead>
              <tbody>
                {result.metrics.map((m) => (
                  <tr key={m.id} className="border-t">
                    <td>
                      <input
                        aria-label={`选用指标 ${m.name}`}
                        type="checkbox"
                        disabled={busy}
                        checked={metricIds.includes(m.id)}
                        onChange={(e) =>
                          setMetricIds(
                            e.target.checked
                              ? [...metricIds, m.id]
                              : metricIds.filter((id) => id !== m.id),
                          )
                        }
                      />
                    </td>
                    <td>{m.name}</td>
                    <td>{m.value}</td>
                    <td>{m.unit ?? "未知"}</td>
                    <td>{m.split ?? "未知"}</td>
                    <td className="whitespace-pre-wrap">
                      {m.evaluation_protocol ?? "未知"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            <label>
              表Key
              <Input
                aria-label="表Key"
                disabled={busy}
                value={tableKey}
                onChange={(e) => setTableKey(e.target.value)}
              />
            </label>
            <label>
              英文表标题
              <Input
                aria-label="英文表标题"
                disabled={busy}
                value={tableTitle}
                onChange={(e) => setTableTitle(e.target.value)}
              />
            </label>
          </div>
          <Button
            size="sm"
            disabled={busy || !metricIds.length || !tableTitle.trim()}
            onClick={addTable}
          >
            加入原指标表
          </Button>
        </div>
      )}
      {value.figures.map((f, i) => (
        <div
          key={i}
          className="flex flex-wrap justify-between gap-2 rounded border p-2 text-xs"
        >
          <span>
            {f.path} · {f.caption}
          </span>
          <Button
            size="sm"
            variant="ghost"
            disabled={busy}
            onClick={() =>
              onChange({
                ...value,
                figures: value.figures.filter((_, at) => at !== i),
              })
            }
          >
            移除图 {i + 1}
          </Button>
        </div>
      ))}
      {value.tables.map((t, i) => (
        <div
          key={i}
          className="flex justify-between gap-2 rounded border p-2 text-xs"
        >
          <span>
            {t.title} · {t.metrics.length} 个原指标
          </span>
          <Button
            size="sm"
            variant="ghost"
            disabled={busy}
            onClick={() =>
              onChange({
                ...value,
                tables: value.tables.filter((_, at) => at !== i),
              })
            }
          >
            移除表 {i + 1}
          </Button>
        </div>
      ))}
    </section>
  );
}
