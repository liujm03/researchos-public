"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { message, type Publication } from "../types";
import { requestHash } from "../request-hash";
import { BuildForm } from "./form";
import { BuildDetail } from "./detail";
import { useBuildPending, type BuildPending } from "./use-pending";
import type { Build, BuildPage, Options } from "./types";
export function PublicationBuilds({
  publication,
  disabled,
  onLock,
}: {
  publication: Publication;
  disabled: boolean;
  onLock: (value: boolean) => void;
}) {
  const endpoint = `/projects/${publication.project_id}/publications/${publication.id}/builds`,
    recovery = useBuildPending(publication.project_id, publication.id);
  const [options, setOptions] = useState<Options | null>(null),
    [page, setPage] = useState<BuildPage | null>(null),
    [build, setBuild] = useState<Build | null>(null),
    [loading, setLoading] = useState(true),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [pollError, setPollError] = useState(""),
    [showForm, setShowForm] = useState(false),
    [canAbandon, setCanAbandon] = useState(false),
    [abandonAck, setAbandonAck] = useState(false);
  const operating = useRef(false),
    seq = useRef(0),
    listSeq = useRef(0);
  useEffect(() => {
    onLock(busy || !!recovery.pending);
    return () => onLock(false);
  }, [busy, recovery.pending, onLock]);
  const load = useCallback(
    async (cursor?: string | null) => {
      const at = ++listSeq.current;
      try {
        const value = await api.get<BuildPage>(
          `${endpoint}?limit=10${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
        );
        if (at === listSeq.current) setPage(value);
      } catch (cause) {
        if (at === listSeq.current) setError(message(cause));
      } finally {
        if (at === listSeq.current) setLoading(false);
      }
    },
    [endpoint],
  );
  const loadOptions = useCallback(async () => {
    try {
      setOptions(await api.get<Options>(`${endpoint}/options`));
    } catch (cause) {
      setError(message(cause));
    }
  }, [endpoint]);
  useEffect(() => {
    void Promise.resolve().then(() => load());
    void Promise.resolve().then(() => loadOptions());
  }, [load, loadOptions]);
  const activeId = build?.id,
    activeStatus = build?.status;
  useEffect(() => {
    if (
      !activeId ||
      !activeStatus ||
      !["SAVING", "QUEUED", "RUNNING", "CANCEL_REQUESTED"].includes(
        activeStatus,
      ) ||
      busy ||
      disabled ||
      recovery.pending
    )
      return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const value = await api.get<Build>(`${endpoint}/${activeId}`);
        if (!active) return;
        if (
          value.project_id !== publication.project_id ||
          value.publication_id !== publication.id
        )
          throw new Error("构建状态不属于当前论文。");
        setBuild((previous) => (previous?.id === activeId ? value : previous));
        setPollError("");
        if (
          ["SAVING", "QUEUED", "RUNNING", "CANCEL_REQUESTED"].includes(
            value.status,
          )
        )
          timer = setTimeout(() => void poll(), 8000);
      } catch (cause) {
        if (active) {
          setPollError(`只读构建状态更新失败：${message(cause)}；未重启编译。`);
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
    activeId,
    activeStatus,
    busy,
    disabled,
    recovery.pending,
    endpoint,
    publication.id,
    publication.project_id,
  ]);
  function valid(value: Build) {
    if (
      value.project_id !== publication.project_id ||
      value.publication_id !== publication.id
    )
      throw new Error("构建回执不属于当前论文。");
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
      const at = ++seq.current,
        value = await api.get<Build>(`${endpoint}/${id}`);
      valid(value);
      if (at === seq.current) setBuild(value);
    });
  }
  async function after(value: Build) {
    valid(value);
    setBuild(value);
    recovery.clear();
    setShowForm(false);
    setNotice("文档构建操作已保存；仅实际字节及编译回执作为完成依据。");
    await load();
  }
  async function transmit(record: BuildPending) {
    await after(await api.post<Build>(record.path, record.body));
  }
  async function send(
    path: string,
    body: Record<string, unknown>,
    label: string,
  ) {
    await action(async () => {
      setCanAbandon(false);
      setAbandonAck(false);
      await transmit(recovery.freeze(path, body, label));
    });
  }
  async function lookup() {
    if (!recovery.pending) return;
    await action(async () => {
      const record = recovery.pending!,
        kind =
          record.path === endpoint
            ? "create"
            : record.path.endsWith("/cancel")
              ? "cancel"
              : "retry",
        parent =
          record.path === endpoint
            ? endpoint
            : record.path.replace(/\/(cancel|retry)$/, ""),
        path =
          parent === endpoint
            ? `${endpoint}/lookup`
            : `${parent}/operations/lookup`;
      try {
        const value = await api.get<Build>(
          `${path}?key=${encodeURIComponent(record.body.idempotency_key)}${kind === "create" ? "" : `&kind=${kind}`}`,
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
            "构建回执类型、键或输入 SHA 与原请求不一致，保留冻结请求。",
          );
        await after(value);
        setNotice("已只读核查原构建请求，没有重复编译或重发。");
      } catch (cause) {
        if (cause instanceof ApiError && cause.status === 404) {
          setCanAbandon(true);
          setNotice("未找到原构建请求；未自动重发，可继续同内容与原键。");
        } else throw cause;
      }
    });
  }
  const blocked = disabled || busy || !recovery.ready || !!recovery.pending;
  return (
    <section
      className="space-y-4 border-t pt-5"
      aria-label="源码与PDF构建工作区"
    >
      <div className="flex flex-wrap justify-between gap-2">
        <div>
          <h2 className="font-semibold">可编辑源码与 PDF 构建</h2>
          <p className="text-xs text-[var(--muted)]">
            本人选定模板、图表与源码后批准一次，队列自动进行受限文档编译；不启动科研实验。
          </p>
        </div>
        <Button
          disabled={blocked || !options?.enabled}
          onClick={() => setShowForm((value) => !value)}
        >
          {showForm ? "收起构建设置" : "准备稿件构建"}
        </Button>
      </div>
      {loading && <LoadingState label="读取文档构建记录…" />}
      {error && (
        <ErrorState
          message={error}
          onRetry={() => {
            setError("");
            void load();
            void loadOptions();
          }}
        />
      )}
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
      {recovery.warning && <p role="alert">{recovery.warning}</p>}
      {options && !options.enabled && (
        <p role="alert">文档构建尚未启用，请查看服务端配置。</p>
      )}
      {options && !options.compiler.available && (
        <p role="alert">
          受限编译器当前不可用：{options.compiler.reason}；未生成替代 PDF。
        </p>
      )}
      {recovery.pending && (
        <section
          aria-label="待核查构建请求"
          className="space-y-2 rounded border p-3"
        >
          <p>待核查原构建请求：{recovery.pending.label}</p>
          <p className="text-xs">
            冻结输入与幂等键保持；刷新不会重新入队或重复编译。
          </p>
          <details>
            <summary>查看冻结构建输入</summary>
            <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-all text-xs">
              {JSON.stringify(recovery.pending.body, null, 2)}
            </pre>
          </details>
          <div className="flex gap-2">
            <Button
              disabled={busy || disabled}
              variant="secondary"
              onClick={() => void lookup()}
            >
              只读核查构建原请求
            </Button>
            <Button
              disabled={busy || disabled}
              onClick={() => void action(() => transmit(recovery.pending!))}
            >
              继续构建原请求
            </Button>
          </div>
          {canAbandon && (
            <>
              <label className="flex gap-2 text-xs">
                <input
                  type="checkbox"
                  checked={abandonAck}
                  disabled={busy}
                  onChange={(e) => setAbandonAck(e.target.checked)}
                />
                已核对构建记录及附件，核查未发现原请求，放弃冻结输入后修正
              </label>
              <Button
                size="sm"
                disabled={busy || !abandonAck}
                onClick={() => {
                  recovery.clear();
                  setCanAbandon(false);
                }}
              >
                放弃构建原请求并修正
              </Button>
            </>
          )}
        </section>
      )}
      {showForm && options && (
        <BuildForm
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
                approve_build: true,
                acknowledge_gaps: true,
              },
              "批准稿件构建",
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
          刷新构建历史
        </Button>
        {page?.items.map((b) => (
          <Button
            key={b.id}
            size="sm"
            variant={build?.id === b.id ? "secondary" : "ghost"}
            disabled={busy || disabled}
            onClick={() => void open(b.id)}
          >
            查看构建 {b.id.slice(0, 8)} · {b.status}
          </Button>
        ))}
        {page?.page.next_cursor && (
          <Button
            size="sm"
            disabled={busy || disabled}
            onClick={() => void load(page.page.next_cursor)}
          >
            下一页构建历史
          </Button>
        )}
      </div>
      {page && !page.items.length && (
        <EmptyState
          title="尚无文档构建"
          detail="预览源码不编译；只有批准保存后才进入文档队列。"
        />
      )}
      {build && (
        <BuildDetail
          key={`${build.id}:${build.status}:${build.attempts.length}`}
          endpoint={endpoint}
          build={build}
          busy={blocked}
          onSend={send}
          onRefresh={() => open(build.id)}
        />
      )}
    </section>
  );
}
