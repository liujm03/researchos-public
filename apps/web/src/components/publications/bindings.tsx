"use client";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";
import type { Binding, Bundle, Fields } from "./types";
type SnapshotClaim = {
  id: string;
  claim_id: string;
  sha256: string;
  title: string;
  scientific_state: string;
  evidence: { paper_id?: string | null }[];
};
type Reference = { paper_id: string; title: string };
export function PublicationBindings({
  value,
  details,
  busy,
  onChange,
}: {
  value: Fields;
  details: Bundle[];
  busy: boolean;
  onChange: (rows: Binding[]) => void;
}) {
  const [section, setSection] = useState(value.sections[0]?.key ?? ""),
    [bundleId, setBundleId] = useState(""),
    [claimId, setClaimId] = useState(""),
    [paperId, setPaperId] = useState(""),
    [start, setStart] = useState("0"),
    [end, setEnd] = useState("0"),
    [quote, setQuote] = useState(""),
    [relation, setRelation] = useState<Binding["relation"]>("SUPPORTS"),
    [note, setNote] = useState(""),
    [error, setError] = useState("");
  const bundle = details.find((d) => d.id === bundleId);
  const claims = (bundle?.snapshot.claims ?? []) as SnapshotClaim[];
  const selectedClaim = claims.find((c) => c.claim_id === claimId);
  const references = (
    (bundle?.snapshot.references ?? []) as Reference[]
  ).filter((r) =>
    selectedClaim?.evidence.some((e) => e.paper_id === r.paper_id),
  );
  const checks = [
    ["format_check", "格式与引用逻辑"],
    ["metadata_check", "元数据身份"],
    ["support_check", "原文支持"],
  ] as const;
  function add() {
    const row = value.sections.find((s) => s.key === section),
      claim = claims.find((c) => c.claim_id === claimId),
      a = Number(start),
      b = Number(end);
    if (
      !row ||
      !claim ||
      !bundle ||
      !Number.isSafeInteger(a) ||
      !Number.isSafeInteger(b) ||
      a < 0 ||
      b <= a ||
      Array.from(row.markdown).slice(a, b).join("") !== quote
    ) {
      setError("请核对 Unicode 字符位置与章节 exact 原句段，必须逐字符一致。");
      return;
    }
    onChange([
      ...value.bindings,
      {
        section_key: section,
        start_offset: a,
        end_offset: b,
        exact_quote: quote,
        bundle_id: bundle.id,
        claim_id: claim.claim_id,
        claim_revision_id: claim.id,
        expected_claim_sha256: claim.sha256,
        relation,
        paper_id: paperId || null,
        format_check: "UNCHECKED",
        metadata_check: "UNCHECKED",
        support_check: "UNCHECKED",
        note,
      },
    ]);
    setError("");
    setQuote("");
  }
  return (
    <section className="space-y-3" aria-label="章节主张与引用绑定">
      <h3 className="font-medium">绑定正文原句段到固定主张</h3>
      <p className="text-xs text-[var(--muted)]">
        字符位置按 Unicode
        字符计数，结束位置不包含在内。修改正文后请重新核对绑定。三层检查分别由本人标注。
      </p>
      {error && <p role="alert">{error}</p>}
      {value.bindings.map((row, index) => (
        <div key={index} className="space-y-2 rounded border p-3 text-sm">
          <p>
            {row.section_key} · {row.relation} · 字符 {row.start_offset}–
            {row.end_offset}
          </p>
          <blockquote className="whitespace-pre-wrap border-l pl-3">
            {row.exact_quote}
          </blockquote>
          <p className="break-all text-xs">
            Claim {row.claim_id} / revision {row.claim_revision_id} ·{" "}
            {row.expected_claim_sha256}
          </p>
          {checks.map(([key, label]) => (
            <label key={key} className="block text-xs">
              {label}
              <select
                aria-label={`绑定${index + 1}${label}`}
                disabled={busy || !row.paper_id}
                value={row[key]}
                onChange={(e) =>
                  onChange(
                    value.bindings.map((b, i) =>
                      i === index ? { ...b, [key]: e.target.value } : b,
                    ),
                  )
                }
                className="ml-2 rounded border p-1"
              >
                {[
                  ["UNCHECKED", "未检查"],
                  ["OWNER_CONFIRMED", "本人确认"],
                  ["ISSUE", "存在问题"],
                ].map(([k, t]) => (
                  <option key={k} value={k}>
                    {t}
                  </option>
                ))}
              </select>
            </label>
          ))}
          <p>{row.note}</p>
          <Button
            size="sm"
            variant="ghost"
            disabled={busy}
            onClick={() =>
              onChange(value.bindings.filter((_, i) => i !== index))
            }
          >
            移除绑定
          </Button>
        </div>
      ))}
      <div className="grid gap-2 md:grid-cols-2">
        <label>
          绑定章节
          <select
            aria-label="绑定章节"
            disabled={busy}
            value={section}
            onChange={(e) => setSection(e.target.value)}
            className="block w-full rounded border p-2"
          >
            {value.sections.map((s) => (
              <option key={s.key} value={s.key}>
                {s.title}
              </option>
            ))}
          </select>
        </label>
        <label>
          绑定证据包
          <select
            aria-label="绑定证据包"
            disabled={busy}
            value={bundleId}
            onChange={(e) => {
              setBundleId(e.target.value);
              setClaimId("");
              setPaperId("");
            }}
            className="block w-full rounded border p-2"
          >
            <option value="">选择来源</option>
            {details.map((d) => (
              <option key={d.id} value={d.id}>
                {d.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          固定主张版本
          <select
            aria-label="固定主张版本"
            disabled={busy}
            value={claimId}
            onChange={(e) => {
              setClaimId(e.target.value);
              setPaperId("");
            }}
            className="block w-full rounded border p-2"
          >
            <option value="">选择主张</option>
            {claims.map((c) => (
              <option key={c.claim_id} value={c.claim_id}>
                {c.title} · {c.scientific_state}
              </option>
            ))}
          </select>
        </label>
        <label>
          相关文献
          <select
            aria-label="相关文献"
            disabled={busy}
            value={paperId}
            onChange={(e) => setPaperId(e.target.value)}
            className="block w-full rounded border p-2"
          >
            <option value="">无特定文献</option>
            {references.map((r) => (
              <option key={r.paper_id} value={r.paper_id}>
                {r.title}
              </option>
            ))}
          </select>
        </label>
        <label>
          起始字符
          <Input
            type="number"
            min="0"
            aria-label="起始字符"
            disabled={busy}
            value={start}
            onChange={(e) => setStart(e.target.value)}
          />
        </label>
        <label>
          结束字符
          <Input
            type="number"
            min="1"
            aria-label="结束字符"
            disabled={busy}
            value={end}
            onChange={(e) => setEnd(e.target.value)}
          />
        </label>
        <label className="md:col-span-2">
          正文原句段
          <Textarea
            aria-label="正文原句段"
            disabled={busy}
            value={quote}
            onChange={(e) => setQuote(e.target.value)}
          />
        </label>
        <label>
          关系
          <select
            aria-label="主张绑定关系"
            disabled={busy}
            value={relation}
            onChange={(e) => setRelation(e.target.value as Binding["relation"])}
            className="ml-2 rounded border p-1"
          >
            <option value="SUPPORTS">支持</option>
            <option value="REFUTES">反证</option>
            <option value="CONTEXT">背景</option>
          </select>
        </label>
        <label>
          绑定说明
          <Input
            aria-label="绑定说明"
            disabled={busy}
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
        </label>
      </div>
      <Button
        size="sm"
        disabled={busy || !bundle || !claimId || !quote}
        onClick={add}
      >
        添加原句段绑定
      </Button>
    </section>
  );
}
