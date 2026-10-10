"use client";
import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import { MarkdownViewer } from "@/components/markdown/markdown-viewer";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/input";
import {
  message,
  relations,
  type Claim,
  type Revision,
  type RevisionPage,
} from "./types";
export function ClaimDetail({
  claim,
  busy,
  onEdit,
  onReview,
}: {
  claim: Claim;
  busy: boolean;
  onEdit: () => void;
  onReview: (
    rev: Revision,
    decision: string,
    conclusion: string,
    ack: boolean,
  ) => Promise<void>;
}) {
  const [history, setHistory] = useState<RevisionPage | null>(null),
    [selected, setSelected] = useState<Revision | null>(null),
    [loading, setLoading] = useState(false),
    [error, setError] = useState("");
  const [decision, setDecision] = useState("COMMENT"),
    [conclusion, setConclusion] = useState(""),
    [ack, setAck] = useState(false);
  const rev = selected ?? claim.current;
  async function load(cursor?: string | null) {
    setLoading(true);
    setError("");
    try {
      setHistory(
        await api.get<RevisionPage>(
          `/claims/${claim.id}/revisions?limit=10${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
        ),
      );
    } catch (cause) {
      setError(message(cause));
    } finally {
      setLoading(false);
    }
  }
  return (
    <section className="space-y-4" aria-label="科研主张详情">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold">
          {rev.title} · 版本 {rev.revision}
        </h2>
        <Button disabled={busy || !!selected} onClick={onEdit}>
          修订主张
        </Button>
      </div>
      <p className="text-sm">
        {rev.scientific_state === "OWNER_ACCEPTED"
          ? "本人接受"
          : rev.scientific_state === "OWNER_REJECTED"
            ? "本人拒绝"
            : "待本人审阅"}{" "}
        · 科学有效性未被系统自动验证
      </p>
      {(!rev.integrity_valid || !rev.context_current) && (
        <p role="alert" className="text-sm text-[var(--danger)]">
          {!rev.integrity_valid ? "版本完整性异常。" : ""}
          {!rev.context_current
            ? "来源已变化：保留历史内容，请重新核对当前来源。"
            : ""}
        </p>
      )}
      {rev.gaps.length > 0 && (
        <ul className="list-disc pl-5 text-xs">
          {rev.gaps.map((gap, i) => (
            <li key={i}>{gap}</li>
          ))}
        </ul>
      )}
      <MarkdownViewer content={rev.text} label="科研主张" />
      {(
        [
          ["conditions", "适用条件"],
          ["limitations", "结论局限"],
          ["evaluation_criteria", "判定标准"],
        ] as const
      ).map(([key, label]) => (
        <div key={key}>
          <h3 className="text-sm font-medium">{label}</h3>
          {rev[key] ? (
            <MarkdownViewer content={rev[key]!} label={label} />
          ) : (
            <p className="text-xs text-[var(--muted)]">尚未记录</p>
          )}
        </div>
      ))}
      <h3 className="font-medium">证据链</h3>
      {!rev.evidence.length && (
        <p className="text-sm">暂无证据；不能将候选主张视作已证实结果。</p>
      )}
      {rev.evidence.map((row) => (
        <div key={row.id} className="space-y-2 rounded border p-3 text-xs">
          <strong>
            {relations.find(([key]) => key === row.relation)?.[1]} ·{" "}
            {row.source_kind}
          </strong>
          <p>
            {row.origin} · {row.context_current ? "当前来源一致" : "来源已变化"}
          </p>
          {row.metric_name && (
            <p>
              {row.metric_name}: {row.metric_value} {row.metric_unit} ·{" "}
              {row.metric_split || "未指定split"} ·{" "}
              {row.evaluation_protocol || "未记录评价协议"}
            </p>
          )}
          {row.artifact_path && (
            <p>
              {row.artifact_path} · {row.artifact_verification} ·{" "}
              {row.artifact_sha256}
            </p>
          )}
          {(row.exact_quote || row.observation) && (
            <pre className="max-h-44 overflow-auto whitespace-pre-wrap">
              {row.exact_quote || row.observation}
            </pre>
          )}
          {row.paper_id && (
            <Link
              className="text-[var(--accent)]"
              href={`/papers/${row.paper_id}`}
            >
              {row.paper_title || "查看源论文"} →
            </Link>
          )}
          {row.result_id && (
            <Link
              className="ml-2 text-[var(--accent)]"
              href={`/projects/${claim.project_id}/results`}
            >
              查看服务器结果 →
            </Link>
          )}
          <p>{row.rationale}</p>
          <details>
            <summary>来源版本与原始事实</summary>
            <p className="break-all">
              来源SHA {row.source_sha256} · 结果 {row.result_sha256} · 笔记{" "}
              {row.note_sha256} · 协议 {row.protocol_sha256} · 数据{" "}
              {row.dataset_sha256}
            </p>
            <pre className="overflow-auto whitespace-pre-wrap break-all">
              {JSON.stringify(row.source_facts, null, 2)}
            </pre>
          </details>
        </div>
      ))}
      <details>
        <summary>本人科学审阅</summary>
        <form
          className="mt-3 space-y-3"
          onSubmit={async (e) => {
            e.preventDefault();
            await onReview(rev, decision, conclusion, ack);
          }}
        >
          <p className="text-xs">
            审阅绑定本次主张与全部证据SHA；接受只表示本人判断，不自动验证实验或论文。
          </p>
          <label className="block text-sm">
            审阅决定
            <select
              aria-label="审阅决定"
              className="block rounded border bg-[var(--surface)] p-2"
              value={decision}
              disabled={busy}
              onChange={(e) => setDecision(e.target.value)}
            >
              <option value="COMMENT">记录意见</option>
              <option value="ACCEPT">本人接受</option>
              <option value="REJECT">本人拒绝</option>
            </select>
          </label>
          <label className="block text-sm">
            本人结论与理由
            <Textarea
              aria-label="本人结论与理由"
              required
              maxLength={10000}
              value={conclusion}
              disabled={busy}
              onChange={(e) => setConclusion(e.target.value)}
            />
          </label>
          <label className="flex gap-2 text-sm">
            <input
              type="checkbox"
              checked={ack}
              disabled={busy}
              onChange={(e) => setAck(e.target.checked)}
            />
            已核查适用条件、局限和所有来源缺口
          </label>
          <Button
            disabled={
              busy ||
              !conclusion.trim() ||
              !rev.integrity_valid ||
              !rev.context_current ||
              (decision === "ACCEPT" && !ack)
            }
            type="submit"
          >
            保存本人审阅
          </Button>
        </form>
      </details>
      {rev.reviews.length > 0 && (
        <section className="space-y-2" aria-label="主张审阅历史">
          <h3 className="text-sm font-medium">审阅历史</h3>
          {rev.reviews.map((row) => (
            <div key={row.id} className="rounded border p-2 text-xs">
              <p>
                {row.decision} · {row.reviewed_at}
              </p>
              <MarkdownViewer content={row.conclusion} label="审阅意见" />
            </div>
          ))}
        </section>
      )}
      <details>
        <summary>版本历史与哈希</summary>
        <p className="break-all text-xs">
          主张 {rev.sha256}
          <br />
          证据 {rev.evidence_sha256}
        </p>
        <Button
          size="sm"
          variant="ghost"
          disabled={busy || loading}
          onClick={() => void load()}
        >
          读取主张历史
        </Button>
        {loading && <p role="status">读取历史中…</p>}
        {error && <p role="alert">{error}</p>}
        {history?.items.map((row) => (
          <Button
            key={row.id}
            size="sm"
            variant="ghost"
            disabled={busy}
            onClick={() => setSelected(row)}
          >
            查看主张版本 {row.revision}
          </Button>
        ))}
        {history?.page.next_cursor && (
          <Button
            size="sm"
            disabled={loading || busy}
            onClick={() => void load(history.page.next_cursor)}
          >
            下一页主张历史
          </Button>
        )}
        {selected && (
          <Button size="sm" onClick={() => setSelected(null)}>
            返回当前主张
          </Button>
        )}
      </details>
    </section>
  );
}
