"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { message, type Publication } from "../types";
import { requestHash } from "../request-hash";
import { WritingForm } from "./form";
import { WritingPlanDetail } from "./plan";
import { useWritingPending, type WritingPending } from "./use-pending";
import type { Plan, PlanPage, Options } from "./types";
export function PublicationWriting({
  publication,
  disabled,
  onAdopt,
  onLock,
}: {
  publication: Publication;
  disabled: boolean;
  onAdopt: () => Promise<void>;
  onLock: (locked: boolean) => void;
}) {
  const endpoint = `/projects/${publication.project_id}/publications/${publication.id}/writing-plans`,
    recovery = useWritingPending(publication.project_id, publication.id);
  const [options, setOptions] = useState<Options | null>(null),
    [page, setPage] = useState<PlanPage | null>(null),
    [plan, setPlan] = useState<Plan | null>(null),
    [busy, setBusy] = useState(false),
    [loading, setLoading] = useState(true),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [showForm, setShowForm] = useState(false),
    [canAbandon, setCanAbandon] = useState(false),
    [ackAbandon, setAckAbandon] = useState(false);
  const [pollError, setPollError] = useState("");
  const operating = useRef(false),
    seq = useRef(0);
  useEffect(() => {
    onLock(busy || !!recovery.pending);
    return () => onLock(false);
  }, [busy, recovery.pending, onLock]);
  const load = useCallback(
    async (cursor?: string | null) => {
      try {
        setPage(
          await api.get<PlanPage>(
            `${endpoint}?limit=10${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
          ),
        );
      } catch (cause) {
        setError(message(cause));
      } finally {
        setLoading(false);
      }
    },
    [endpoint],
  );
  useEffect(() => {
    void Promise.resolve().then(() => load());
    void api
      .get<Options>(`${endpoint}/options`)
      .then(setOptions)
      .catch((cause) => setError(message(cause)));
  }, [load, endpoint]);
  const pollingPlanId = plan?.id,
    pollingStatus = plan?.task.status;
  useEffect(() => {
    if (
      !pollingPlanId ||
      !pollingStatus ||
      !["QUEUED", "RUNNING"].includes(pollingStatus) ||
      busy ||
      disabled ||
      recovery.pending
    )
      return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const identity = pollingPlanId;
    async function poll() {
      try {
        const current = await api.get<Plan>(`${endpoint}/${identity}`);
        if (!active) return;
        if (
          current.project_id !== publication.project_id ||
          current.publication_id !== publication.id
        )
          throw new Error("写作状态回执不属于当前论文。");
        setPlan((previous) => (previous?.id === identity ? current : previous));
        setPollError("");
        if (["QUEUED", "RUNNING"].includes(current.task.status))
          timer = setTimeout(() => void poll(), 8000);
      } catch (cause) {
        if (active) {
          setPollError(`只读状态更新失败：${message(cause)}；未重新启动任务。`);
          timer = setTimeout(() => void poll(), 8000);
        }
      }
    }
    timer = setTimeout(() => void poll(), 8000);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [
    pollingPlanId,
    pollingStatus,
    busy,
    disabled,
    recovery.pending,
    endpoint,
    publication.id,
    publication.project_id,
  ]);
  function valid(value: Plan) {
    if (
      value.project_id !== publication.project_id ||
      value.publication_id !== publication.id
    )
      throw new Error("写作计划不属于当前论文，未显示结果或继续操作。");
  }
  async function action(fn: () => Promise<void>) {
    if (operating.current || disabled) return;
    operating.current = true;
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (cause) {
      setError(message(cause));
      if (
        cause instanceof ApiError &&
        cause.details &&
        typeof cause.details === "object" &&
        "committed" in cause.details &&
        cause.details.committed === false
      )
        recovery.clear();
    } finally {
      operating.current = false;
      setBusy(false);
    }
  }
  async function open(id: string) {
    await action(async () => {
      const at = ++seq.current;
      const value = await api.get<Plan>(`${endpoint}/${id}`);
      valid(value);
      if (at === seq.current) setPlan(value);
    });
  }
  async function after(value: Plan, path: string) {
    valid(value);
    setPlan(value);
    recovery.clear();
    setShowForm(false);
    setNotice("写作操作已保存；候选须本人另行采纳。");
    await load();
    if (path.endsWith("/adopt")) await onAdopt();
  }
  async function transmit(record: WritingPending) {
    const value = await api.post<Plan>(record.path, record.body);
    await after(value, record.path);
  }
  async function send(
    path: string,
    body: Record<string, unknown>,
    label: string,
  ) {
    await action(async () => {
      setCanAbandon(false);
      setAckAbandon(false);
      const record = recovery.freeze(path, body, label);
      await transmit(record);
    });
  }
  async function lookup() {
    if (!recovery.pending) return;
    await action(async () => {
      const record = recovery.pending!,
        kind =
          record.path === endpoint
            ? "create"
            : record.path.endsWith("/start")
              ? "start"
              : record.path.endsWith("/adopt")
                ? "adopt"
                : record.path.endsWith("/issues")
                  ? "issue"
                  : "import",
        parent =
          record.path === endpoint
            ? endpoint
            : record.path.replace(/\/(start|import-result|adopt|issues)$/, ""),
        path =
          parent === endpoint
            ? `${endpoint}/lookup`
            : `${parent}/operations/lookup`;
      try {
        const value = await api.get<Plan>(
          `${path}?key=${encodeURIComponent(record.body.idempotency_key)}${parent === endpoint ? "" : `&kind=${kind}`}`,
        );
        valid(value);
        if (
          !value.operation_receipt ||
          value.operation_receipt.kind !== kind ||
          value.operation_receipt.idempotency_key !==
            record.body.idempotency_key ||
          value.operation_receipt.request_sha256 !==
            (await requestHash(record.body))
        )
          throw new Error(
            "写作回执与冻结请求类型、幂等键或输入SHA不一致，保留原请求。",
          );
        await after(value, record.path);
        setNotice("已只读核查原写作请求，没有重复执行。");
      } catch (cause) {
        if (cause instanceof ApiError && cause.status === 404) {
          setCanAbandon(true);
          setNotice("未找到原写作请求，未自动重发；可继续原内容与原键。");
        } else throw cause;
      }
    });
  }
  const blocked = disabled || busy || !recovery.ready || !!recovery.pending;
  return (
    <section
      className="space-y-4 border-t pt-5"
      aria-label="专业Skill写作工作区"
    >
      <div className="flex flex-wrap justify-between gap-2">
        <div>
          <h2 className="font-semibold">专业 Skill 写作</h2>
          <p className="text-xs text-[var(--muted)]">
            原稿不会自动改变。选任务与输入 → 预览批准 → 明确启动 → 核对真实候选
            → 本人选段采纳。
          </p>
        </div>
        <Button
          disabled={blocked || !options?.enabled}
          onClick={() => setShowForm((v) => !v)}
        >
          {showForm ? "收起写作设置" : "准备专业写作"}
        </Button>
      </div>
      {loading && <LoadingState label="读取写作计划…" />}
      {error && (
        <ErrorState
          message={error}
          onRetry={() => {
            setError("");
            void load();
            void api
              .get<Options>(`${endpoint}/options`)
              .then(setOptions)
              .catch((cause) => setError(message(cause)));
          }}
        />
      )}{" "}
      {notice && (
        <p role="status" className="text-sm">
          {notice}
        </p>
      )}
      {pollError && (
        <p role="status" className="text-xs">
          {pollError}
        </p>
      )}
      {options && (
        <p
          role={!options.enabled ? "alert" : undefined}
          className="text-xs text-[var(--muted)]"
        >
          {options.detail}
        </p>
      )}
      {recovery.warning && <p role="alert">{recovery.warning}</p>}
      {recovery.pending && (
        <section
          className="space-y-2 rounded border p-3"
          aria-label="待核查写作请求"
        >
          <p>待核查原写作请求：{recovery.pending.label}</p>
          <p className="text-xs">
            原内容和幂等键已冻结；刷新不会自动调用模型或采纳正文。
          </p>
          <details>
            <summary>核对冻结原请求</summary>
            <pre className="max-h-52 overflow-auto whitespace-pre-wrap break-all text-xs">
              {JSON.stringify(recovery.pending.body, null, 2)}
            </pre>
          </details>
          <div className="flex gap-2">
            <Button
              variant="secondary"
              disabled={busy || disabled}
              onClick={() => void lookup()}
            >
              只读核查写作原请求
            </Button>
            <Button
              disabled={busy || disabled}
              onClick={() => void action(() => transmit(recovery.pending!))}
            >
              继续写作原请求
            </Button>
          </div>
          {canAbandon && (
            <>
              <label className="flex gap-2 text-xs">
                <input
                  type="checkbox"
                  checked={ackAbandon}
                  disabled={busy}
                  onChange={(e) => setAckAbandon(e.target.checked)}
                />
                我已核对计划与历史，核查未发现原请求，放弃冻结请求后修正输入
              </label>
              <Button
                size="sm"
                disabled={busy || !ackAbandon}
                onClick={() => {
                  recovery.clear();
                  setCanAbandon(false);
                }}
              >
                放弃写作原请求并修正
              </Button>
            </>
          )}
        </section>
      )}
      {showForm && options && (
        <WritingForm
          key={publication.current.sha256}
          endpoint={endpoint}
          revision={publication.current}
          options={options}
          busy={blocked}
          onCreate={(preview) =>
            send(
              endpoint,
              {
                selection: preview.selection,
                expected_preview_sha256: preview.preview_sha256,
                approve_cloud_transfer: true,
                acknowledge_gaps: true,
              },
              "保存写作计划",
            )
          }
        />
      )}
      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          variant="ghost"
          disabled={busy || disabled}
          onClick={() => void load()}
        >
          刷新写作计划
        </Button>
        {page?.items.map((p) => (
          <Button
            key={p.id}
            variant={plan?.id === p.id ? "secondary" : "ghost"}
            size="sm"
            disabled={busy || disabled}
            onClick={() => void open(p.id)}
          >
            查看写作计划 · {p.id.slice(0, 8)}
          </Button>
        ))}
        {page?.page.next_cursor && (
          <Button
            size="sm"
            disabled={busy || disabled}
            onClick={() => void load(page.page.next_cursor)}
          >
            下一页写作计划
          </Button>
        )}
      </div>
      {page && !page.items.length && (
        <EmptyState
          title="尚无专业写作计划"
          detail="先保存当前论文版本，再本人预览与批准写作任务。"
        />
      )}
      {plan && (
        <WritingPlanDetail
          key={`${plan.id}:${plan.task.status}:${plan.candidate?.sha256}:${plan.adoptions.length}:${(plan.issues ?? []).length}`}
          endpoint={endpoint}
          plan={plan}
          publication={publication}
          busy={blocked}
          onSend={send}
          onRefresh={() => open(plan.id)}
        />
      )}
    </section>
  );
}
