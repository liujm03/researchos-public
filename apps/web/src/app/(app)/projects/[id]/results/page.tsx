"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { MarkdownViewer } from "@/components/markdown/markdown-viewer";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Textarea } from "@/components/ui/input";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { api, ApiError } from "@/lib/api";
import type { components } from "@/lib/generated";

type Options = components["schemas"]["ServerResultOptions"];
type Result = components["schemas"]["ServerResultOut"];
type History = components["schemas"]["ServerResultPage"];
type Review = components["schemas"]["ServerResultReviewRequest"];
type NextRequest = components["schemas"]["ServerResultNextBriefRequest"];
type NextResponse = components["schemas"]["ServerResultNextBriefOut"];
type Retry = Omit<
  components["schemas"]["Body_retry_import_api_v1_projects__project_id__server_results__result_id__retry_import_post"],
  "file"
>;
type Section = components["schemas"]["ResearchBriefSectionCreate"];
type PendingImport = {
  owner: string;
  project: string;
  packageId: string;
  key: string;
  sha: string;
  size: number;
  name: string;
};
const importState = {
  IMPORTING: "正在保存",
  READY: "已保存",
  NEEDS_ATTENTION: "保存事实待核查",
  FAILED: "保存失败",
};
const origins = {
  OWNER_UPLOADED_UNVERIFIED: "本人上传 · 来源未核验",
  CONFIGURED_KEY_SIGNATURE: "配置密钥签名匹配",
  INVALID_SIGNATURE: "签名不匹配",
};
const validations = {
  MATCHED: "文件与原包匹配",
  GAPS: "有材料缺口",
  MISMATCH: "存在错配",
};
const reviews = {
  UNREVIEWED: "未审阅",
  ACCEPTED: "本人已接受",
  REJECTED: "本人已拒绝",
};
const sectionLabels: Record<Section["key"], string> = {
  intent: "研究意图",
  related_work: "文献依据",
  hypotheses: "待验证假设",
  resources: "所需资源",
  routes: "候选路线",
  protocol: "评价协议",
  stage_plan: "阶段任务",
  decision: "决策条件",
};
const note =
  "导入只保存结果材料，不执行命令、模型、仿真或 AI，也不提交服务器任务。文件匹配和密钥签名均不证明科学结论；接受报告不自动验证假设。";
function message(cause: unknown) {
  return cause instanceof Error ? cause.message : "请求失败";
}
function noCommit(cause: unknown) {
  return (
    cause instanceof ApiError &&
    cause.details !== null &&
    typeof cause.details === "object" &&
    "committed" in cause.details &&
    cause.details.committed === false
  );
}
async function fileHash(file: File) {
  if (file.size > 32 * 1024 * 1024)
    throw new Error(
      "结果 ZIP 超过浏览器侧 32 MiB 上限，请只纳入必要日志和指标，大文件保留声明。",
    );
  return Array.from(
    new Uint8Array(
      await crypto.subtle.digest("SHA-256", await file.arrayBuffer()),
    ),
  )
    .map((v) => v.toString(16).padStart(2, "0"))
    .join("");
}

export default function ServerResultsPage() {
  const { id } = useParams<{ id: string }>();
  const endpoint = `/projects/${id}/server-results`;
  const [options, setOptions] = useState<Options | null>(null);
  const [history, setHistory] = useState<History | null>(null);
  const [detail, setDetail] = useState<Result | null>(null);
  const [packageId, setPackageId] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [pending, setPending] = useState<PendingImport | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [decision, setDecision] = useState<Review["decision"]>("COMMENT");
  const [conclusion, setConclusion] = useState("");
  const [ack, setAck] = useState(false);
  const [tasks, setTasks] = useState<string[]>([]);
  const [pendingReview, setPendingReview] = useState<{
    result: string;
    body: Review;
  } | null>(null);
  const [idea, setIdea] = useState("");
  const [sections, setSections] = useState<
    Partial<Record<Section["key"], string>>
  >({});
  const [stopRules, setStopRules] = useState("");
  const [pendingNext, setPendingNext] = useState<{
    result: string;
    body: NextRequest;
  } | null>(null);
  const [nextBrief, setNextBrief] = useState<string | null>(null);
  const [retryFile, setRetryFile] = useState<File | null>(null);
  const [ackRetry, setAckRetry] = useState(false);
  const [pendingRetry, setPendingRetry] = useState<{
    result: string;
    body: Retry;
  } | null>(null);
  const storageKey = useCallback(
    (owner: string) => `researchos:server-result-import:${owner}:${id}`,
    [id],
  );

  const loadHistory = useCallback(
    async (cursor?: string) => {
      const value = await api.get<History>(
        `${endpoint}?limit=20${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
      );
      setHistory(value);
    },
    [endpoint],
  );
  const loadOptions = useCallback(
    async (cursor?: string) => {
      const value = await api.get<Options>(
        `${endpoint}/options?limit=20${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
      );
      setOptions(value);
      return value;
    },
    [endpoint],
  );
  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [value] = await Promise.all([loadOptions(), loadHistory()]);
      const raw = sessionStorage.getItem(storageKey(value.owner_id));
      if (raw) {
        const saved: PendingImport = JSON.parse(raw);
        if (
          saved.owner === value.owner_id &&
          saved.project === id &&
          typeof saved.key === "string" &&
          /^[0-9a-f]{64}$/.test(saved.sha)
        ) {
          setPending(saved);
          setPackageId(saved.packageId);
        }
      } else {
        const selected = new URLSearchParams(window.location.search).get(
          "package",
        );
        if (selected) setPackageId(selected);
      }
    } catch (cause) {
      setError(message(cause));
    } finally {
      setLoading(false);
    }
  }, [id, loadOptions, loadHistory, storageKey]);
  useEffect(() => {
    let mounted = true;
    queueMicrotask(() => {
      if (mounted) void load();
    });
    return () => {
      mounted = false;
    };
  }, [load]);

  async function openResult(resultId: string) {
    setBusy(true);
    setError("");
    try {
      setDetail(await api.get<Result>(`${endpoint}/${resultId}`));
      setTasks([]);
      setAck(false);
      setConclusion("");
      setDecision("COMMENT");
      setIdea("");
      setSections({});
      setStopRules("");
      setNextBrief(null);
      setRetryFile(null);
      setAckRetry(false);
      setPendingRetry(null);
      setPendingReview(null);
      setPendingNext(null);
      if (options) {
        const retryRaw = sessionStorage.getItem(
          `${storageKey(options.owner_id)}:retry:${resultId}`,
        );
        if (retryRaw) {
          const body: Retry = JSON.parse(retryRaw);
          setPendingRetry({ result: resultId, body });
          setAckRetry(body.acknowledge_unknown ?? false);
        }
        const reviewRaw = sessionStorage.getItem(
          `${storageKey(options.owner_id)}:review:${resultId}`,
        );
        if (reviewRaw) {
          const body: Review = JSON.parse(reviewRaw);
          setPendingReview({ result: resultId, body });
          setConclusion(body.conclusion);
          setDecision(body.decision);
          setAck(body.acknowledge_gaps ?? false);
          setTasks((body.complete_tasks ?? []).map((t) => t.task_id));
        }
        const nextRaw = sessionStorage.getItem(
          `${storageKey(options.owner_id)}:next:${resultId}`,
        );
        if (nextRaw) {
          const body: NextRequest = JSON.parse(nextRaw);
          setPendingNext({ result: resultId, body });
          setIdea(body.idea);
          setStopRules(body.stop_rules ?? "");
          setSections(
            Object.fromEntries(
              (body.sections ?? []).map((s) => [s.key, s.content ?? ""]),
            ),
          );
        }
      }
    } catch (cause) {
      setError(message(cause));
    } finally {
      setBusy(false);
    }
  }
  function clearImport(record: PendingImport) {
    sessionStorage.removeItem(storageKey(record.owner));
    setPending(null);
  }
  async function checkImport() {
    if (!pending) return;
    setBusy(true);
    setError("");
    try {
      const result = await api.get<Result>(
        `${endpoint}/lookup?idempotency_key=${encodeURIComponent(pending.key)}`,
      );
      setDetail(result);
      if (result.status === "READY" || result.status === "FAILED")
        clearImport(pending);
      setNotice(
        result.status === "IMPORTING" || result.status === "NEEDS_ATTENTION"
          ? "找到同一次导入记录，保存事实仍待核查；保留原 key，不重新上传。"
          : "找到同一次导入记录；未重新上传。",
      );
      await loadHistory();
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 404)
        setNotice(
          "暂未找到同次记录。可重新选择相同 SHA 的原 ZIP，再明确重试同一次导入；不会自动重播。",
        );
      else setError(message(cause));
    } finally {
      setBusy(false);
    }
  }
  async function importResult() {
    if (!options || !file || !packageId) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const sha = await fileHash(file);
      const record = pending ?? {
        owner: options.owner_id,
        project: id,
        packageId,
        key: crypto.randomUUID(),
        sha,
        size: file.size,
        name: file.name,
      };
      if (
        record.owner !== options.owner_id ||
        record.project !== id ||
        record.packageId !== packageId ||
        record.sha !== sha ||
        record.size !== file.size
      )
        throw new Error(
          "待核查的导入绑定原交接包与 ZIP；请选择同一文件并使用同一次幂等 key。",
        );
      sessionStorage.setItem(
        storageKey(options.owner_id),
        JSON.stringify(record),
      );
      setPending(record);
      const body = new FormData();
      body.append("package_id", record.packageId);
      body.append("idempotency_key", record.key);
      body.append("file", file);
      const result = await api.postForm<Result>(`${endpoint}/import`, body);
      setDetail(result);
      if (result.status === "READY" || result.status === "FAILED")
        clearImport(record);
      setNotice("结果材料已接收，请核对来源、缺口和报告声明。");
      await loadHistory();
    } catch (cause) {
      if (
        cause instanceof ApiError &&
        cause.details &&
        typeof cause.details === "object" &&
        "admitted" in cause.details &&
        cause.details.admitted === false
      ) {
        sessionStorage.removeItem(storageKey(options.owner_id));
        setPending(null);
        setNotice(
          "服务器已明确拒绝本次导入且未建立记录；原文件仍保留，可修正文件或选择其他交接包后重新提交。",
        );
      }
      setError(message(cause));
    } finally {
      setBusy(false);
    }
  }
  async function saveReview() {
    if (!detail || !conclusion.trim()) return;
    setBusy(true);
    setError("");
    const body: Review =
      pendingReview?.result === detail.id
        ? pendingReview.body
        : {
            expected_result_sha256: detail.result_sha256,
            decision,
            conclusion,
            acknowledge_gaps: ack,
            complete_tasks:
              decision === "ACCEPT"
                ? detail.linked_tasks
                    .filter((t) => tasks.includes(t.id))
                    .map((t) => ({
                      task_id: t.id,
                      expected_version: t.version,
                    }))
                : [],
            idempotency_key: crypto.randomUUID(),
          };
    setPendingReview({ result: detail.id, body });
    try {
      if (options)
        sessionStorage.setItem(
          `${storageKey(options.owner_id)}:review:${detail.id}`,
          JSON.stringify(body),
        );
      await api.post(`${endpoint}/${detail.id}/reviews`, body);
      if (options)
        sessionStorage.removeItem(
          `${storageKey(options.owner_id)}:review:${detail.id}`,
        );
      setPendingReview(null);
      setDetail(await api.get<Result>(`${endpoint}/${detail.id}`));
      setTasks([]);
      setConclusion("");
      setNotice("本人审阅已保存；原报告、签名和文件事实保持不变。");
      await loadHistory();
    } catch (cause) {
      if (noCommit(cause) && options) {
        sessionStorage.removeItem(
          `${storageKey(options.owner_id)}:review:${detail.id}`,
        );
        setPendingReview(null);
        setNotice(
          "服务器明确未保存本次审阅。请核对错误；任务版本变化时刷新此结果，再重新选择当前任务并提交结论。",
        );
      }
      setError(message(cause));
    } finally {
      setBusy(false);
    }
  }
  async function createNext() {
    if (!detail || !idea.trim()) return;
    setBusy(true);
    setError("");
    const body: NextRequest =
      pendingNext?.result === detail.id
        ? pendingNext.body
        : {
            expected_result_sha256: detail.result_sha256,
            idea,
            sections: Object.entries(sections)
              .filter(([, content]) => content?.trim())
              .map(([key, content]) => ({
                key: key as Section["key"],
                content,
              })),
            stop_rules: stopRules || null,
            idempotency_key: crypto.randomUUID(),
          };
    setPendingNext({ result: detail.id, body });
    try {
      if (options)
        sessionStorage.setItem(
          `${storageKey(options.owner_id)}:next:${detail.id}`,
          JSON.stringify(body),
        );
      const next = await api.post<NextResponse>(
        `${endpoint}/${detail.id}/next-brief`,
        body,
      );
      if (options)
        sessionStorage.removeItem(
          `${storageKey(options.owner_id)}:next:${detail.id}`,
        );
      setPendingNext(null);
      setNextBrief(next.brief_id);
      setDetail(await api.get<Result>(`${endpoint}/${detail.id}`));
      setNotice(
        "下一轮任务书草稿已保存，需在任务书页面审阅；没有执行或接受新方案。",
      );
    } catch (cause) {
      if (noCommit(cause) && options) {
        sessionStorage.removeItem(
          `${storageKey(options.owner_id)}:next:${detail.id}`,
        );
        setPendingNext(null);
        setNotice(
          "服务器明确未保存本次草稿。请核对结果审阅和来源状态，再修改输入并重新提交。",
        );
      }
      setError(message(cause));
    } finally {
      setBusy(false);
    }
  }
  async function retryImport() {
    if (!detail || !options || !ackRetry) return;
    setBusy(true);
    setError("");
    setNotice("");
    const body: Retry =
      pendingRetry?.result === detail.id
        ? pendingRetry.body
        : {
            expected_result_sha256: detail.result_sha256,
            input_sha256: detail.input_sha256,
            acknowledge_unknown: true,
            retry_idempotency_key: crypto.randomUUID(),
          };
    try {
      if (!detail.input_attachment_id && !retryFile)
        throw new Error("未保存可核对的原 ZIP，请重新选择同一 SHA 的原文件。");
      if (retryFile && (await fileHash(retryFile)) !== body.input_sha256)
        throw new Error("重选 ZIP 的 SHA 与原输入不一致，未调用恢复接口。");
      sessionStorage.setItem(
        `${storageKey(options.owner_id)}:retry:${detail.id}`,
        JSON.stringify(body),
      );
      setPendingRetry({ result: detail.id, body });
      const form = new FormData();
      form.append("expected_result_sha256", body.expected_result_sha256);
      form.append("input_sha256", body.input_sha256);
      form.append("acknowledge_unknown", "true");
      form.append("retry_idempotency_key", body.retry_idempotency_key);
      if (retryFile) form.append("file", retryFile);
      const restored = await api.postForm<Result>(
        `${endpoint}/${detail.id}/retry-import`,
        form,
      );
      setDetail(restored);
      if (restored.status === "READY" || restored.status === "FAILED") {
        sessionStorage.removeItem(
          `${storageKey(options.owner_id)}:retry:${detail.id}`,
        );
        setPendingRetry(null);
        if (
          pending?.packageId === restored.package_id &&
          pending.sha === restored.input_sha256
        )
          clearImport(pending);
      }
      setNotice(
        restored.status === "READY"
          ? "原结果包存储已核对并恢复；没有运行实验或修改来源签名。"
          : "本次存储恢复仍有缺口，请核查状态；不会自动继续重试。",
      );
      await loadHistory();
    } catch (cause) {
      if (noCommit(cause)) {
        sessionStorage.removeItem(
          `${storageKey(options.owner_id)}:retry:${detail.id}`,
        );
        setPendingRetry(null);
      }
      setError(message(cause));
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <LoadingState label="正在加载结果与交接记录…" />;
  if (!options)
    return (
      <ErrorState
        message={error || "无法加载结果工作区"}
        onRetry={() => void load()}
      />
    );
  const lockReview = busy || !!pendingReview || detail?.status !== "READY";
  const lockNext =
    busy ||
    !!pendingNext ||
    detail?.status !== "READY" ||
    detail?.review_status !== "ACCEPTED";
  const hasGaps =
    !!detail &&
    (detail.gaps.length > 0 ||
      detail.validation_status !== "MATCHED" ||
      detail.origin_verification !== "CONFIGURED_KEY_SIGNATURE");
  return (
    <div className="space-y-5">
      <nav className="flex flex-wrap gap-4 text-sm">
        <Link href={`/projects/${id}`} className="text-[var(--accent)]">
          ← 返回课题
        </Link>
        <Link href={`/projects/${id}/handoff`} className="text-[var(--accent)]">
          服务器交接包
        </Link>
      </nav>
      <header>
        <h1 className="text-2xl font-semibold">结果与下一轮</h1>
        <p className="mt-2 text-sm text-[var(--muted)]">
          {options.project_name} · {note}
        </p>
      </header>
      {error && <ErrorState message={error} />}
      {notice && (
        <p
          role="status"
          className="rounded border border-[var(--border)] p-3 text-sm"
        >
          {notice}
        </p>
      )}
      <Card>
        <CardHeader>
          <h2 className="font-semibold">回传服务器结果包</h2>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm">
            上传服务器侧收集工具生成的 ZIP（含
            result_manifest.json）；报告内的运行状态是声明，不自动视为服务器已执行。
          </p>
          <label className="grid gap-1 text-sm">
            原交接包
            <select
              aria-label="原交接包"
              className="h-10 rounded border border-[var(--border)] bg-[var(--surface)] px-3"
              value={packageId}
              disabled={busy || !!pending}
              onChange={(e) => setPackageId(e.target.value)}
            >
              <option value="">选择已保存交接包</option>
              {packageId &&
                !options.packages.some((p) => p.id === packageId) && (
                  <option value={packageId}>
                    已选交接包 {packageId} · 提交时由服务器核对
                  </option>
                )}
              {options.packages.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label} · {p.readiness}
                </option>
              ))}
            </select>
          </label>
          {options.packages.length === 0 && (
            <p className="text-sm text-[var(--muted)]">
              尚无可回传的已保存交接包，请先创建服务器交接。
            </p>
          )}
          {options.page.next_cursor && (
            <Button
              variant="ghost"
              disabled={busy || !!pending}
              onClick={() =>
                void loadOptions(options.page.next_cursor ?? undefined).catch(
                  (c) => setError(message(c)),
                )
              }
            >
              下一页交接包
            </Button>
          )}
          <label className="grid gap-1 text-sm">
            结果 ZIP
            <input
              aria-label="结果 ZIP"
              type="file"
              accept=".zip,application/zip"
              disabled={busy}
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </label>
          {file && (
            <p className="text-sm">
              已选：{file.name} · {file.size.toLocaleString()} 字节
            </p>
          )}
          {pending && (
            <div className="space-y-2 rounded border border-amber-500 p-3 text-sm">
              <p>
                此前导入回执尚待核查；保留原交接包、文件 SHA 与同一次
                key。刷新页面不会重新上传。
              </p>
              <p className="break-all">
                原文件：{pending.name} · SHA-256 {pending.sha}
              </p>
              <Button
                variant="secondary"
                disabled={busy}
                onClick={() => void checkImport()}
              >
                核查同一次导入
              </Button>
            </div>
          )}
          <Button
            disabled={busy || !file || !packageId}
            onClick={() => void importResult()}
          >
            {busy
              ? "正在处理…"
              : pending
                ? "明确重试同一次导入"
                : "上传并核对结果包"}
          </Button>
          <details className="text-sm">
            <summary className="cursor-pointer">来源签名与服务器侧配置</summary>
            <p className="mt-2">
              {options.signature_verification_configured
                ? `已配置签名核验：${options.configured_server_id ?? "配置服务器"}`
                : "尚未配置来源签名；可以上传明确标为来源未核验的材料。"}{" "}
              密钥只通过服务器端环境变量配置，不在浏览器输入或保存。签名仅核对配置密钥，不保证科学真实性。服务器侧收集步骤见交接包说明及使用教程。
            </p>
          </details>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <h2 className="font-semibold">回传记录</h2>
          <Button
            variant="ghost"
            disabled={busy}
            onClick={() =>
              void loadHistory().catch((c) => setError(message(c)))
            }
          >
            刷新记录
          </Button>
        </CardHeader>
        <CardContent className="space-y-3">
          {history?.items.length ? (
            <ul className="space-y-2">
              {history.items.map((r) => (
                <li key={r.id}>
                  <Button
                    variant="ghost"
                    disabled={busy}
                    onClick={() => void openResult(r.id)}
                  >
                    {r.receipt_id} · {importState[r.status]} ·{" "}
                    {reviews[r.review_status]}
                  </Button>
                  <p className="text-xs text-[var(--muted)]">
                    报告声称状态：{r.claimed_run_status} ·{" "}
                    {origins[r.origin_verification]} ·{" "}
                    {validations[r.validation_status]}
                  </p>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState
              title="尚无回传结果"
              detail="上传本人选定的结果包后，可审阅指标、原始产物及失败原因。"
            />
          )}
          {history?.page.next_cursor && (
            <Button
              variant="secondary"
              disabled={busy}
              onClick={() =>
                void loadHistory(history.page.next_cursor ?? undefined).catch(
                  (c) => setError(message(c)),
                )
              }
            >
              下一页回传记录
            </Button>
          )}
        </CardContent>
      </Card>
      {detail && (
        <section aria-label="结果详情" className="space-y-5">
          <Card>
            <CardHeader>
              <h2 className="font-semibold">
                {detail.receipt_id} · {importState[detail.status]}
              </h2>
              <Button
                variant="ghost"
                disabled={busy}
                onClick={() => void openResult(detail.id)}
              >
                刷新此结果
              </Button>
            </CardHeader>
            <CardContent className="space-y-3">
              <dl className="grid gap-3 text-sm md:grid-cols-2">
                <div>
                  <dt className="text-[var(--muted)]">来源核验</dt>
                  <dd>
                    {origins[detail.origin_verification]} ·{" "}
                    {detail.server_id ?? "未声明服务器"}
                  </dd>
                </div>
                <div>
                  <dt className="text-[var(--muted)]">程序匹配</dt>
                  <dd>{validations[detail.validation_status]}</dd>
                </div>
                <div>
                  <dt className="text-[var(--muted)]">报告声称状态</dt>
                  <dd>
                    {detail.claimed_run_status} · 作业{" "}
                    {detail.claimed_job_id ?? "未提供"}
                  </dd>
                </div>
                <div>
                  <dt className="text-[var(--muted)]">本人审阅</dt>
                  <dd>{reviews[detail.review_status]}</dd>
                </div>
              </dl>
              <p className="text-sm text-[var(--muted)]">{detail.scope_note}</p>
              {detail.error_message && (
                <p role="alert" className="text-sm text-[var(--danger)]">
                  {detail.error_code}：{detail.error_message}
                </p>
              )}
              {detail.gaps.length > 0 && (
                <div className="rounded border border-amber-500 p-3">
                  <h3 className="font-medium">缺口与错配</h3>
                  <ul className="list-inside list-disc text-sm">
                    {detail.gaps.map((g) => (
                      <li key={g}>{g}</li>
                    ))}
                  </ul>
                </div>
              )}
              {detail.input_attachment_id && (
                <a
                  className="text-sm text-[var(--accent)] underline"
                  href={`/api/v1${endpoint}/${detail.id}/download`}
                >
                  下载已接收原始 ZIP
                </a>
              )}
              {detail.status !== "READY" && (
                <section
                  aria-label="恢复结果包存储"
                  className="space-y-3 rounded border border-amber-500 p-3"
                >
                  <h3 className="font-medium">恢复原结果包存储</h3>
                  <p className="text-sm">
                    仅重试保存原始材料，保留原结果
                    SHA、文件指纹与签名事实。未知结果可能重复存储写入；本人确认后服务器会隔离旧回调。IMPORTING
                    至少等待 5
                    分钟才可申请恢复，等待本身不证明进程已停止，具体资格由服务器核对。
                  </p>
                  <p className="text-sm">
                    {detail.input_attachment_id
                      ? "已保存原 ZIP，可直接由服务器读取并重新核对；无需重传。"
                      : "尚无已核对的原 ZIP，必须重新选择原文件。"}
                  </p>
                  {!detail.input_attachment_id && (
                    <label className="grid gap-1 text-sm">
                      重选原结果 ZIP
                      <input
                        type="file"
                        aria-label="重选原结果 ZIP"
                        accept=".zip,application/zip"
                        disabled={busy}
                        onChange={(e) =>
                          setRetryFile(e.target.files?.[0] ?? null)
                        }
                      />
                    </label>
                  )}
                  {retryFile && (
                    <p className="text-sm">
                      恢复文件：{retryFile.name} ·{" "}
                      {retryFile.size.toLocaleString()} 字节
                    </p>
                  )}
                  {pendingRetry && (
                    <p className="text-sm">
                      此前恢复回执尚待核查；本次沿用原恢复 key
                      与指纹，不自动重播。刷新后若无原附件须重新选择相同文件。
                    </p>
                  )}
                  <label className="flex gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={ackRetry}
                      disabled={busy || !!pendingRetry}
                      onChange={(e) => setAckRetry(e.target.checked)}
                    />
                    我已核查未知或失败存储，明确允许重试原材料并隔离旧回调
                  </label>
                  <Button
                    disabled={
                      busy ||
                      !ackRetry ||
                      (!detail.input_attachment_id && !retryFile)
                    }
                    onClick={() => void retryImport()}
                  >
                    {pendingRetry
                      ? "明确重试同一次存储恢复"
                      : "确认并恢复原结果包存储"}
                  </Button>
                </section>
              )}
              <details className="text-xs">
                <summary className="cursor-pointer">来源指纹与运行声明</summary>
                <dl className="mt-2 space-y-1 break-all">
                  {[
                    ["结果 SHA", detail.result_sha256],
                    ["输入 ZIP SHA", detail.input_sha256],
                    ["Receipt SHA", detail.receipt_sha256],
                    ["原交接包", detail.package_id],
                    ["代码 commit", detail.git_commit],
                    ["协议 SHA", detail.protocol_sha256],
                    ["配置 SHA", detail.config_sha256],
                    ["数据 SHA", detail.dataset_sha256],
                    ["声称开始", detail.started_at],
                    ["声称结束", detail.ended_at],
                  ].map(([label, value]) => (
                    <div key={label}>
                      <dt>{label}</dt>
                      <dd>{value ?? "未声明"}</dd>
                    </div>
                  ))}
                </dl>
              </details>
              <h3 className="font-medium">报告指标（尚非科学验证）</h3>
              {detail.metrics.length ? (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm">
                    <thead>
                      <tr>
                        {["指标", "值", "单位", "Split", "评价协议"].map(
                          (h) => (
                            <th className="p-2" key={h}>
                              {h}
                            </th>
                          ),
                        )}
                      </tr>
                    </thead>
                    <tbody>
                      {detail.metrics.map((m) => (
                        <tr
                          key={m.id}
                          className="border-t border-[var(--border)]"
                        >
                          <td className="p-2">{m.name}</td>
                          <td className="p-2">{m.value}</td>
                          <td className="p-2">{m.unit ?? "未声明"}</td>
                          <td className="p-2">{m.split ?? "未声明"}</td>
                          <td className="whitespace-pre-wrap p-2">
                            {m.evaluation_protocol ?? "未声明"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="text-sm text-[var(--muted)]">
                  本报告未提供指标；失败与负结果仍可审阅并形成下一轮草稿。
                </p>
              )}
              <h3 className="font-medium">产物与实际字节</h3>
              {detail.artifacts.length ? (
                <ul className="space-y-2 text-sm">
                  {detail.artifacts.map((a) => (
                    <li
                      key={a.id}
                      className="rounded border border-[var(--border)] p-3"
                    >
                      <p>
                        {a.path} · {a.size_bytes.toLocaleString()} 字节 ·{" "}
                        {a.verification === "BYTES_VERIFIED"
                          ? "已收到并核对字节"
                          : a.verification === "DECLARED_NOT_INCLUDED"
                            ? "仅声明，未收到文件"
                            : a.verification === "MISSING"
                              ? "缺失文件"
                              : "字节错配"}
                      </p>
                      <p className="break-all text-xs text-[var(--muted)]">
                        声明 SHA：{a.sha256}
                      </p>
                      <p className="break-all text-xs text-[var(--muted)]">
                        收到字节：
                        {a.actual_size_bytes?.toLocaleString() ?? "未收到"}；
                        实际 SHA：{a.actual_sha256 ?? "未核对"}
                      </p>
                      {a.verification === "BYTES_VERIFIED" &&
                        a.attachment_id && (
                          <a
                            className="text-[var(--accent)] underline"
                            href={`/api/v1/attachments/${a.attachment_id}/file`}
                          >
                            下载已核对产物
                          </a>
                        )}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-[var(--muted)]">没有产物声明。</p>
              )}
              {detail.notes && (
                <MarkdownViewer content={detail.notes} label="报告说明" />
              )}
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <h2 className="font-semibold">本人审阅结论</h2>
            </CardHeader>
            <CardContent className="space-y-3">
              <p className="text-sm text-[var(--muted)]">
                选择接受、拒绝或追加意见；接受材料不代表系统验证科研正确。仅本人勾选的原任务会被完成，服务器核对当前任务版本。
              </p>
              <label className="grid gap-1 text-sm">
                审阅决定
                <select
                  aria-label="审阅决定"
                  value={decision}
                  disabled={lockReview}
                  onChange={(e) =>
                    setDecision(e.target.value as Review["decision"])
                  }
                  className="h-10 rounded border border-[var(--border)] bg-[var(--surface)] px-3"
                >
                  <option value="COMMENT">追加意见</option>
                  <option value="ACCEPT">接受材料</option>
                  <option value="REJECT">拒绝材料</option>
                </select>
              </label>
              <label className="grid gap-1 text-sm">
                科学结论与下一步判断
                <Textarea
                  aria-label="科学结论与下一步判断"
                  value={conclusion}
                  disabled={lockReview}
                  maxLength={10000}
                  onChange={(e) => setConclusion(e.target.value)}
                />
              </label>
              {hasGaps && (
                <label className="flex gap-2 text-sm">
                  <input
                    type="checkbox"
                    disabled={lockReview}
                    checked={ack}
                    onChange={(e) => setAck(e.target.checked)}
                  />
                  我已核对来源未验证、缺失或错配，明确保留这些限制
                </label>
              )}
              {detail.linked_tasks.length > 0 && (
                <fieldset
                  disabled={lockReview || decision !== "ACCEPT"}
                  className="space-y-2"
                >
                  <legend className="mb-2 text-sm font-medium">
                    明确完成选定原任务（可不选）
                  </legend>
                  {detail.linked_tasks.map((t) => (
                    <label key={t.id} className="flex gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={tasks.includes(t.id)}
                        disabled={!["todo", "in_progress"].includes(t.status)}
                        onChange={(e) =>
                          setTasks((current) =>
                            e.target.checked
                              ? [...current, t.id]
                              : current.filter((v) => v !== t.id),
                          )
                        }
                      />
                      {t.title} · {t.status} · 当前版本 {t.version}
                    </label>
                  ))}
                </fieldset>
              )}
              {pendingReview && (
                <p className="text-sm text-amber-600">
                  审阅回执待核查，重试沿用原结论、任务版本和同一次
                  key；不会新建第二次审阅。
                </p>
              )}
              <Button
                disabled={
                  busy ||
                  detail.status !== "READY" ||
                  !conclusion.trim() ||
                  (decision === "ACCEPT" && hasGaps && !ack)
                }
                onClick={() => void saveReview()}
              >
                {pendingReview ? "核对并重试同次审阅" : "保存本人审阅"}
              </Button>
              {detail.reviews.length > 0 && (
                <details>
                  <summary className="cursor-pointer text-sm">
                    原审阅记录（保留历史）
                  </summary>
                  <ul className="mt-2 space-y-2">
                    {detail.reviews.map((r) => (
                      <li key={r.id} className="text-sm">
                        <p>
                          {r.decision} · {r.reviewed_at} · 完成{" "}
                          {r.completed_task_ids.length} 项任务
                        </p>
                        <p className="whitespace-pre-wrap">{r.conclusion}</p>
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <h2 className="font-semibold">从结果创建下一轮草稿</h2>
            </CardHeader>
            <CardContent className="space-y-3">
              <p className="text-sm text-[var(--muted)]">
                先明确接受本报告作为下一轮依据，再由本人给出下一研究方向；机械保存来源链。声称
                FAILED、STOPPED
                或负结果也可作为接受的材料，接受不等于实验成功。未审阅或已拒绝材料不能生成草稿。不运行
                AI、不自动接受新任务书。
              </p>
              <label className="grid gap-1 text-sm">
                下一轮研究 Idea
                <Textarea
                  aria-label="下一轮研究 Idea"
                  value={idea}
                  disabled={lockNext}
                  maxLength={12000}
                  onChange={(e) => setIdea(e.target.value)}
                />
              </label>
              <details>
                <summary className="cursor-pointer text-sm">
                  补充任务书章节与停止规则（可选）
                </summary>
                <div className="mt-3 grid gap-3 md:grid-cols-2">
                  {Object.entries(sectionLabels).map(([key, label]) => (
                    <label key={key} className="grid gap-1 text-sm">
                      {label}
                      <Textarea
                        value={sections[key as Section["key"]] ?? ""}
                        disabled={lockNext}
                        maxLength={40000}
                        onChange={(e) =>
                          setSections((current) => ({
                            ...current,
                            [key]: e.target.value,
                          }))
                        }
                      />
                    </label>
                  ))}
                  <label className="grid gap-1 text-sm md:col-span-2">
                    停止规则
                    <Textarea
                      value={stopRules}
                      disabled={lockNext}
                      maxLength={40000}
                      onChange={(e) => setStopRules(e.target.value)}
                    />
                  </label>
                </div>
              </details>
              {pendingNext && (
                <p className="text-sm text-amber-600">
                  草稿回执待核查，沿用同一次 key 与原输入重试。
                </p>
              )}
              <Button
                disabled={
                  busy ||
                  detail.status !== "READY" ||
                  detail.review_status !== "ACCEPTED" ||
                  !idea.trim()
                }
                onClick={() => void createNext()}
              >
                {pendingNext ? "核对并重试同次草稿" : "保存下一轮任务书草稿"}
              </Button>
              {(nextBrief || detail.next_brief_ids.length > 0) && (
                <div className="text-sm">
                  <Link
                    className="text-[var(--accent)] underline"
                    href={`/projects/${id}/brief`}
                  >
                    打开任务书并选择草稿 →
                  </Link>
                  <p className="mt-1 break-all text-xs text-[var(--muted)]">
                    来源关联草稿：
                    {[
                      ...new Set([
                        ...(nextBrief ? [nextBrief] : []),
                        ...detail.next_brief_ids,
                      ]),
                    ].join("、")}
                  </p>
                </div>
              )}
            </CardContent>
          </Card>
        </section>
      )}
    </div>
  );
}
