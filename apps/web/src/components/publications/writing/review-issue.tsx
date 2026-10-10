"use client";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";
import type { Plan } from "./types";
export function ReviewIssueForm({
  plan,
  path,
  publicationSha,
  busy,
  onSend,
}: {
  plan: Plan;
  path: string;
  publicationSha: string;
  busy: boolean;
  onSend: (
    path: string,
    body: Record<string, unknown>,
    label: string,
  ) => Promise<void>;
}) {
  const [title, setTitle] = useState(""),
    [severity, setSeverity] = useState("MAJOR"),
    [start, setStart] = useState("0"),
    [end, setEnd] = useState("0"),
    [quote, setQuote] = useState(""),
    [error, setError] = useState("");
  function submit() {
    const a = Number(start),
      b = Number(end);
    if (
      !plan.candidate ||
      !Number.isSafeInteger(a) ||
      !Number.isSafeInteger(b) ||
      a < 0 ||
      b <= a ||
      Array.from(plan.candidate.markdown).slice(a, b).join("") !== quote
    ) {
      setError("请核对预审原文 Unicode 字符位置，选段必须逐字符一致。");
      return;
    }
    setError("");
    void onSend(
      `${path}/issues`,
      {
        expected_candidate_sha256: plan.candidate.sha256,
        start_offset: a,
        end_offset: b,
        exact_quote: quote,
        expected_publication_sha256: publicationSha,
        title,
        severity,
        priority:
          severity === "CRITICAL"
            ? "urgent"
            : severity === "MINOR"
              ? "medium"
              : "high",
        category: "writing",
      },
      "加入预审修订任务",
    );
  }
  return (
    <section className="space-y-3" aria-label="预审问题任务">
      <h4 className="font-medium">将预审问题加入修订任务</h4>
      <p className="text-xs text-[var(--muted)]">
        预审报告保留为候选证据，不替换论文正文。本人选择具体问题后创建
        todo，任务保留稿件、候选 SHA 与原句段。
      </p>
      <div className="grid gap-3 md:grid-cols-2">
        <label>
          修订任务标题
          <Input
            aria-label="修订任务标题"
            value={title}
            disabled={busy}
            onChange={(e) => setTitle(e.target.value)}
          />
        </label>
        <label>
          问题严重程度
          <select
            aria-label="问题严重程度"
            className="block w-full rounded border p-2"
            disabled={busy}
            value={severity}
            onChange={(e) => setSeverity(e.target.value)}
          >
            <option value="CRITICAL">CRITICAL · 关键问题</option>
            <option value="MAJOR">MAJOR · 主要问题</option>
            <option value="MINOR">MINOR · 次要问题</option>
          </select>
        </label>
        <label>
          预审起始字符
          <Input
            aria-label="预审起始字符"
            type="number"
            min="0"
            value={start}
            disabled={busy}
            onChange={(e) => setStart(e.target.value)}
          />
        </label>
        <label>
          预审结束字符
          <Input
            aria-label="预审结束字符"
            type="number"
            min="1"
            value={end}
            disabled={busy}
            onChange={(e) => setEnd(e.target.value)}
          />
        </label>
        <label className="md:col-span-2">
          预审原句段
          <Textarea
            aria-label="预审原句段"
            rows={5}
            disabled={busy}
            value={quote}
            onChange={(e) => setQuote(e.target.value)}
          />
        </label>
      </div>
      {error && <p role="alert">{error}</p>}
      <Button disabled={busy || !title.trim() || !quote} onClick={submit}>
        将问题加入修订任务
      </Button>
    </section>
  );
}
