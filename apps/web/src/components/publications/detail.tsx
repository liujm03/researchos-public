"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/input";
import { MarkdownViewer } from "@/components/markdown/markdown-viewer";
import {
  message,
  type Publication,
  type Revision,
  type RevisionPage,
} from "./types";
export function PublicationDetail({
  publication,
  busy,
  onEdit,
  onReview,
}: {
  publication: Publication;
  busy: boolean;
  onEdit: () => void;
  onReview: (
    row: Revision,
    decision: string,
    conclusion: string,
    ack: boolean,
  ) => Promise<void>;
}) {
  const [history, setHistory] = useState<RevisionPage | null>(null),
    [selected, setSelected] = useState<Revision | null>(null),
    [loading, setLoading] = useState(false),
    [error, setError] = useState(""),
    [decision, setDecision] = useState("COMMENT"),
    [conclusion, setConclusion] = useState(""),
    [ack, setAck] = useState(false);
  const row = selected ?? publication.current,
    endpoint = `/projects/${publication.project_id}/publications/${publication.id}`;
  async function load(cursor?: string | null) {
    setLoading(true);
    setError("");
    try {
      setHistory(
        await api.get<RevisionPage>(
          `${endpoint}/revisions?limit=10${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
        ),
      );
    } catch (cause) {
      setError(message(cause));
    } finally {
      setLoading(false);
    }
  }
  return (
    <section aria-label="论文版本详情" className="space-y-4">
      <div className="flex flex-wrap justify-between gap-2">
        <h2 className="font-semibold">
          {row.title} · 版本 {row.revision}
        </h2>
        <Button disabled={busy || !!selected} onClick={onEdit}>
          修订论文
        </Button>
      </div>
      <p className="text-sm">
        {row.target_venue || "目标场所未确定"} · {row.stage} ·{" "}
        {row.owner_review_state === "OWNER_ACCEPTED"
          ? "本人接受"
          : row.owner_review_state === "OWNER_REJECTED"
            ? "本人拒绝"
            : "待本人审阅"}
      </p>
      <p className="text-xs text-[var(--muted)]">
        人审仅表示本人对这个版本的判断；未自动执行投稿、AI写作或 LaTeX 构建。
      </p>
      <p className="break-all text-xs">版本 SHA-256：{row.sha256}</p>
      {(!row.integrity_valid || !row.context_current) && (
        <p role="alert">
          {!row.integrity_valid ? "版本完整性异常。" : ""}
          {!row.context_current ? "来源已变化，保留历史正文，请重新核对。" : ""}
        </p>
      )}
      <ul className="list-disc pl-5 text-xs">
        {row.gaps.map((g, i) => (
          <li key={i}>{g}</li>
        ))}
      </ul>
      {row.sections.map((s) => (
        <details
          key={s.key}
          className="rounded border p-3"
          open={s.markdown ? undefined : false}
        >
          <summary>
            {s.title} · {s.kind === "SKELETON" ? "骨架" : "正文"} · {s.status}
          </summary>
          {s.markdown ? (
            <MarkdownViewer content={s.markdown} label={`${s.title}正文`} />
          ) : (
            <p className="text-xs text-[var(--muted)]">尚未填写</p>
          )}
        </details>
      ))}
      <details className="rounded border p-3">
        <summary>
          固定证据来源与正文绑定 · {(row.sources ?? []).length} 个包 /{" "}
          {(row.bindings ?? []).length} 个原句段
        </summary>
        {row.source_details.map((s) => (
          <div key={s.id} className="my-2 border p-2 text-xs">
            <p>
              {s.label} · {s.status} · 当前来源{" "}
              {s.context_current ? "未变化" : "已变化"}
            </p>
            <p className="break-all">{s.bundle_sha256}</p>
            <p>源图表字节未包含；科学主张须另行核对。</p>
            <ul>
              {s.current_gaps.map((g, i) => (
                <li key={i}>{g}</li>
              ))}
            </ul>
          </div>
        ))}
        {(row.bindings ?? []).map((b, i) => (
          <div key={i} className="my-2 border p-2 text-sm">
            <p>
              {b.section_key} · {b.relation}
            </p>
            <blockquote className="whitespace-pre-wrap">
              {b.exact_quote}
            </blockquote>
            <p className="break-all text-xs">
              固定主张 {b.claim_id} / {b.claim_revision_id}
            </p>
            <p className="text-xs">
              格式与逻辑：{b.format_check} · 元数据：{b.metadata_check} ·
              原文支持：{b.support_check}
            </p>
            {b.note && <p>{b.note}</p>}
          </div>
        ))}
      </details>
      <div className="space-y-2">
        <h3 className="font-medium">本人审阅这个版本</h3>
        <label>
          审阅决定
          <select
            aria-label="论文审阅决定"
            disabled={busy}
            value={decision}
            onChange={(e) => setDecision(e.target.value)}
            className="ml-2 rounded border p-1"
          >
            <option value="COMMENT">记录意见</option>
            <option value="ACCEPT">接受</option>
            <option value="REJECT">拒绝</option>
          </select>
        </label>
        <label className="block">
          审阅结论
          <Textarea
            aria-label="论文审阅结论"
            disabled={busy}
            value={conclusion}
            onChange={(e) => setConclusion(e.target.value)}
          />
        </label>
        <label className="flex gap-2 text-xs">
          <input
            type="checkbox"
            disabled={busy}
            checked={ack}
            onChange={(e) => setAck(e.target.checked)}
          />
          我已核对这个版本与缺口
        </label>
        <Button
          disabled={busy || !conclusion.trim() || !ack}
          onClick={() => void onReview(row, decision, conclusion, ack)}
        >
          保存论文审阅
        </Button>
        <ul className="text-xs">
          {row.reviews.map((r) => (
            <li key={r.id}>
              {r.decision} · {r.conclusion}
            </li>
          ))}
        </ul>
      </div>
      <Button
        variant="secondary"
        disabled={busy || loading}
        onClick={() => void load()}
      >
        读取论文历史
      </Button>
      {loading && <p role="status">读取历史中…</p>}
      {error && <p role="alert">{error}</p>}
      {history && (
        <div className="flex flex-wrap gap-2">
          {history.items.map((r) => (
            <Button
              key={r.id}
              size="sm"
              variant="ghost"
              disabled={busy}
              onClick={() => {
                setSelected(r);
                setAck(false);
                setConclusion("");
              }}
            >
              查看版本 {r.revision}
            </Button>
          ))}
          {history.page.next_cursor && (
            <Button
              size="sm"
              disabled={busy || loading}
              onClick={() => void load(history.page.next_cursor)}
            >
              下一页版本
            </Button>
          )}
          {selected && (
            <Button
              size="sm"
              onClick={() => {
                setSelected(null);
                setAck(false);
                setConclusion("");
              }}
            >
              返回当前版本
            </Button>
          )}
        </div>
      )}
    </section>
  );
}
