"use client";
import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";
import { MarkdownViewer } from "@/components/markdown/markdown-viewer";
import { message, type Publication } from "../types";
import type { Plan, AdoptSelection, AdoptPreview } from "./types";
import { ReviewIssueForm } from "./review-issue";
export async function textSha(value: string) {
  return Array.from(
    new Uint8Array(
      await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value)),
    ),
    (b) => b.toString(16).padStart(2, "0"),
  ).join("");
}
export function WritingPlanDetail({
  endpoint,
  plan,
  publication,
  busy,
  onSend,
  onRefresh,
}: {
  endpoint: string;
  plan: Plan;
  publication: Publication;
  busy: boolean;
  onSend: (
    path: string,
    body: Record<string, unknown>,
    label: string,
  ) => Promise<void>;
  onRefresh: () => Promise<void>;
}) {
  const [startAck, setStartAck] = useState(false),
    [start, setStart] = useState("0"),
    [end, setEnd] = useState("0"),
    [quote, setQuote] = useState(""),
    [preview, setPreview] = useState<AdoptPreview | null>(null),
    [selection, setSelection] = useState<AdoptSelection | null>(null),
    [adoptAck, setAdoptAck] = useState(false),
    [loading, setLoading] = useState(false),
    [error, setError] = useState("");
  const path = `${endpoint}/${plan.id}`,
    task = plan.task;
  function change() {
    setPreview(null);
    setSelection(null);
    setAdoptAck(false);
  }
  async function inspect() {
    if (!plan.candidate) return;
    setError("");
    const a = Number(start),
      b = Number(end);
    if (
      !Number.isSafeInteger(a) ||
      !Number.isSafeInteger(b) ||
      a < 0 ||
      b <= a ||
      Array.from(plan.candidate.markdown).slice(a, b).join("") !== quote
    ) {
      setError("请核对候选 Unicode 字符位置，原句段必须逐字符一致。");
      return;
    }
    setLoading(true);
    try {
      const input: AdoptSelection = {
        expected_candidate_sha256: plan.candidate.sha256,
        start_offset: a,
        end_offset: b,
        exact_quote: quote,
        expected_publication_sha256: publication.current.sha256,
      };
      setPreview(await api.post<AdoptPreview>(`${path}/adopt-preview`, input));
      setSelection(input);
    } catch (cause) {
      setError(message(cause));
    } finally {
      setLoading(false);
    }
  }
  return (
    <section className="space-y-3" aria-label="写作计划详情">
      <div className="flex flex-wrap justify-between gap-2">
        <h3 className="font-medium">
          {plan.preview.skill_key} → {plan.preview.selection.target_section_key}
        </h3>
        <Button
          size="sm"
          variant="secondary"
          disabled={busy}
          onClick={() => void onRefresh()}
        >
          刷新写作状态
        </Button>
      </div>
      <p className="text-sm">
        Codex任务：{task.status} · {task.model_key} / {task.reasoning_effort} ·
        已报告输入 {task.input_tokens ?? "未知"} / 输出{" "}
        {task.output_tokens ?? "未知"} Token
      </p>
      <Link
        className="text-xs text-[var(--accent)]"
        href={`/ai-tasks/${plan.task_id}`}
      >
        查看真实 Codex 任务与执行回执 →
      </Link>
      <p className="text-xs">
        已报告 Token 不代表账户剩余额度；专业写作不会执行科研或构建命令。
      </p>
      <p className="text-xs">
        冻结正文语言：English · 写作风格：{plan.preview.selection.venue_style} ·
        科学结论、目标场所和投稿格式需本人核查。
      </p>
      {!plan.context_current && (
        <p role="alert">
          原稿或来源已变化；这个计划保留历史，请重新预览当前稿件，不覆盖本人修改。
        </p>
      )}
      {task.error && (
        <p role="alert" className="text-sm text-[var(--danger)]">
          {task.error}
        </p>
      )}
      <ul className="list-disc pl-5 text-xs">
        {plan.gaps.map((g, i) => (
          <li key={i}>{g}</li>
        ))}
      </ul>
      <details>
        <summary>核对计划冻结输入与 Skill</summary>
        <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-all text-xs">
          {JSON.stringify(plan.preview.input_snapshot, null, 2)}
        </pre>
        <p className="break-all text-xs">
          {plan.preview.preview_sha256} · {plan.preview.skill_manifest_sha256}
        </p>
      </details>
      {task.status === "DRAFT" && (
        <div className="space-y-2 rounded border p-3">
          <label className="flex gap-2 text-xs">
            <input
              type="checkbox"
              disabled={busy || !plan.context_current}
              checked={startAck}
              onChange={(e) => setStartAck(e.target.checked)}
            />
            现在启动这一份已批准写作计划，发送其冻结资料到 Codex
          </label>
          <Button
            disabled={busy || !startAck || !plan.context_current}
            onClick={() =>
              void onSend(
                `${path}/start`,
                {
                  expected_preview_sha256: plan.preview.preview_sha256,
                  approve_start: true,
                },
                "启动写作",
              )
            }
          >
            启动已批准写作
          </Button>
        </div>
      )}
      {task.final_response && (
        <details>
          <summary>查看任务实际原始返回</summary>
          <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-all text-xs">
            {task.final_response}
          </pre>
        </details>
      )}
      {!plan.candidate &&
        task.status === "COMPLETED" &&
        task.final_response && (
          <div className="space-y-2">
            <p className="text-xs text-[var(--muted)]">
              任务已完成但候选尚未归档；可用下方按钮恢复冻结实际返回，不会重新调用模型。
            </p>
            <Button
              disabled={busy}
              onClick={() =>
                void (async () => {
                  try {
                    await onSend(
                      `${path}/import-result`,
                      {
                        expected_response_sha256: await textSha(
                          task.final_response!,
                        ),
                      },
                      "冻结写作候选",
                    );
                  } catch (cause) {
                    setError(message(cause));
                  }
                })()
              }
            >
              冻结实际写作候选
            </Button>
          </div>
        )}
      {!plan.candidate && (
        <p className="text-sm text-[var(--muted)]">
          尚无可采纳候选；仅实际完成返回并冻结的 Markdown 会显示在这里。
        </p>
      )}
      {plan.candidate &&
        plan.preview.skill_key === "pre-submission-reviewer" && (
          <>
            <MarkdownViewer
              content={plan.candidate.markdown}
              label="预审候选原文"
            />
            <ReviewIssueForm
              plan={plan}
              path={path}
              publicationSha={publication.current.sha256}
              busy={busy}
              onSend={onSend}
            />
          </>
        )}
      {plan.candidate &&
        plan.preview.skill_key !== "pre-submission-reviewer" && (
          <>
            <p className="break-all text-xs">
              候选 SHA-256：{plan.candidate.sha256}
            </p>
            <MarkdownViewer
              content={plan.candidate.markdown}
              label="写作候选原文"
            />
            <h4 className="font-medium">本人选段采纳到当前稿件</h4>
            <p className="text-xs text-[var(--muted)]">
              以原候选精确选段替换目标章节。这个章节的旧证据/引用绑定将删除，须本人重建；其他章节与历史版本保持。采纳不自动确认科学结论。
            </p>
            <div className="grid gap-3 md:grid-cols-2">
              <label>
                候选起始字符
                <Input
                  aria-label="候选起始字符"
                  type="number"
                  min="0"
                  disabled={busy || loading}
                  value={start}
                  onChange={(e) => {
                    setStart(e.target.value);
                    change();
                  }}
                />
              </label>
              <label>
                候选结束字符
                <Input
                  aria-label="候选结束字符"
                  type="number"
                  min="1"
                  disabled={busy || loading}
                  value={end}
                  onChange={(e) => {
                    setEnd(e.target.value);
                    change();
                  }}
                />
              </label>
              <label className="md:col-span-2">
                候选原句段
                <Textarea
                  aria-label="候选原句段"
                  rows={7}
                  disabled={busy || loading}
                  value={quote}
                  onChange={(e) => {
                    setQuote(e.target.value);
                    change();
                  }}
                />
              </label>
            </div>
            <Button
              disabled={busy || loading || !quote}
              variant="secondary"
              onClick={() => void inspect()}
            >
              {loading ? "核查采纳中…" : "预览选段采纳"}
            </Button>
            {preview && selection && (
              <section
                className="space-y-2 rounded border p-3"
                aria-label="写作采纳预览"
              >
                <p className="break-all text-xs">
                  当前稿件 SHA：{selection.expected_publication_sha256} ·
                  采纳预览 SHA：{preview.preview_sha256}
                </p>
                <ul className="list-disc pl-5 text-xs">
                  {preview.gaps.map((g, i) => (
                    <li key={i}>{g}</li>
                  ))}
                </ul>
                <MarkdownViewer
                  content={
                    preview.fields.sections.find(
                      (s) =>
                        s.key === plan.preview.selection.target_section_key,
                    )?.markdown ?? ""
                  }
                  label="采纳目标章节预览"
                />
                <label className="flex gap-2 text-xs">
                  <input
                    type="checkbox"
                    checked={adoptAck}
                    disabled={busy}
                    onChange={(e) => setAdoptAck(e.target.checked)}
                  />
                  我已核对当前稿件、原候选选段与缺口，同意清除目标章节旧绑定并保存新版本
                </label>
                <Button
                  disabled={busy || !adoptAck}
                  onClick={() =>
                    void onSend(
                      `${path}/adopt`,
                      {
                        ...selection,
                        expected_adoption_preview_sha256:
                          preview.preview_sha256,
                        acknowledge_gaps: true,
                      },
                      "采纳写作选段",
                    )
                  }
                >
                  采纳选段为新版本
                </Button>
              </section>
            )}
          </>
        )}
      {error && <p role="alert">{error}</p>}
      {(plan.issues ?? []).length > 0 && (
        <section className="space-y-2" aria-label="预审修订任务历史">
          <h4 className="font-medium">已保存的预审修订任务</h4>
          {(plan.issues ?? []).map((issue) => (
            <div key={issue.id} className="rounded border p-3 text-xs">
              <Link
                href={`/tasks/${issue.task_id}`}
                className="text-[var(--accent)]"
              >
                {issue.severity} · 查看修订任务 →
              </Link>
              <blockquote className="mt-2 whitespace-pre-wrap">
                {issue.exact_quote}
              </blockquote>
            </div>
          ))}
        </section>
      )}
      {plan.adoptions.length > 0 && (
        <details>
          <summary>本人采纳历史 · {plan.adoptions.length} 次</summary>
          {plan.adoptions.map((a) => (
            <div key={a.id} className="my-2 border p-2 text-xs">
              <p className="break-all">
                稿件版本 {a.publication_revision_id} · {a.revision_sha256}
              </p>
              <blockquote className="whitespace-pre-wrap">
                {a.exact_quote}
              </blockquote>
            </div>
          ))}
        </details>
      )}
    </section>
  );
}
