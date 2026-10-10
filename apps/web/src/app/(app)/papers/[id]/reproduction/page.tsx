"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { ReproductionSourceView } from "@/components/papers/reproduction-source";
import { ReproductionExcerptPicker } from "@/components/papers/reproduction-excerpts";
import {
  ReproductionContextPanel,
  reproductionStageLabels,
} from "@/components/papers/reproduction-context";
import {
  api,
  ApiError,
  type Paper,
  type ReproductionSource,
  type ReproductionSourceContent,
  type ReproductionSourcePage,
  type ReproductionExcerptRange,
  type PaperReproductionPreviewRequest,
  type PaperReproductionCreateRequest,
  type PaperReproductionPreview,
} from "@/lib/api";
import {
  codexModeLabels,
  codexStatusLabels,
  formatCodexTime,
  type CodexTask,
  type CodexTaskSummary,
  type CodexWorkspace,
  type CodexCapabilities,
} from "@/lib/codex";
const selectClass =
  "h-10 w-full rounded border border-[var(--border)] bg-[var(--background)] px-3 text-sm";
async function requestSignature(body: PaperReproductionCreateRequest) {
  const hash = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(JSON.stringify(body)),
  );
  return Array.from(new Uint8Array(hash), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
}
export default function PaperReproductionPage() {
  const { id } = useParams<{ id: string }>();
  return <ReproductionView key={id} paperId={id} />;
}

function ReproductionView({ paperId }: { paperId: string }) {
  const base = "/papers/" + encodeURIComponent(paperId) + "/reproduction-tasks",
    sourcesBase =
      "/papers/" + encodeURIComponent(paperId) + "/reproduction-sources",
    storageKey = "researchos.paper-reproduction." + paperId + ".pending-create";
  const [paper, setPaper] = useState<Paper | null>(null),
    [sources, setSources] = useState<ReproductionSource[]>([]),
    [cursor, setCursor] = useState<string | null>(null),
    [source, setSource] = useState<ReproductionSourceContent | null>(null),
    [sourceId, setSourceId] = useState("");
  const [workspaces, setWorkspaces] = useState<CodexWorkspace[]>([]),
    [caps, setCaps] = useState<CodexCapabilities | null>(null),
    [history, setHistory] = useState<CodexTaskSummary[]>([]);
  const [loading, setLoading] = useState(true),
    [sourceLoading, setSourceLoading] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [sourceError, setSourceError] = useState(""),
    [historyError, setHistoryError] = useState("");
  const [title, setTitle] = useState(""),
    [goal, setGoal] = useState(
      "制定可核查的复现方案，识别论文方法、实验设置与缺失资料。",
    ),
    [instructions, setInstructions] = useState(""),
    [stage, setStage] = useState<"PLAN" | "IMPLEMENT_CODE">("PLAN"),
    [selectionMode, setSelectionMode] = useState<"FULL" | "EXCERPTS">("FULL"),
    [ranges, setRanges] = useState<ReproductionExcerptRange[]>([]),
    [workspaceId, setWorkspaceId] = useState(""),
    [preview, setPreview] = useState<PaperReproductionPreview | null>(null),
    [approved, setApproved] = useState(false);
  const mode = "read_only" as const;
  const [createdTask, setCreatedTask] = useState<CodexTask | null>(null),
    [message, setMessage] = useState(""),
    [startUnknown, setStartUnknown] = useState(false);
  const seq = useRef(0),
    sourceSeq = useRef(0),
    busyRef = useRef(false),
    pending = useRef<{ signature: string; key: string } | null>(null),
    known = useRef<{ signature: string; task: CodexTask } | null>(null);
  const invalidate = () => {
    setPreview(null);
    setApproved(false);
  };
  const load = useCallback(async () => {
    const token = ++seq.current;
    const results = await Promise.allSettled([
      api.get<Paper>("/papers/" + paperId),
      api.get<ReproductionSourcePage>(sourcesBase + "?limit=20"),
      api.get<CodexWorkspace[]>("/codex/workspaces"),
      api.get<CodexCapabilities>("/codex/capabilities"),
      api.get<CodexTaskSummary[]>(base),
    ]);
    if (token !== seq.current) return;
    const [a, b, c, d, e] = results;
    if (a.status === "fulfilled") {
      setPaper(a.value);
      setTitle((old) => old || ("复现准备：" + a.value.title).slice(0, 240));
    }
    if (b.status === "fulfilled") {
      setSources(b.value.items);
      setCursor(b.value.page.next_cursor);
    }
    if (c.status === "fulfilled") {
      setWorkspaces(c.value);
      setWorkspaceId(
        (old) =>
          old ||
          c.value.find(
            (item) =>
              item.available && item.allowed_modes.includes("read_only"),
          )?.id ||
          "",
      );
    }
    if (d.status === "fulfilled") setCaps(d.value);
    if (e.status === "fulfilled") {
      setHistory(e.value);
      setHistoryError("");
    } else
      setHistoryError(
        e.reason instanceof Error ? e.reason.message : "任务历史暂不可读",
      );
    setError(
      results
        .slice(0, 4)
        .filter(
          (item): item is PromiseRejectedResult => item.status === "rejected",
        )
        .map((item) =>
          item.reason instanceof Error
            ? item.reason.message
            : "来源或工作区暂不可读",
        )
        .join("；"),
    );
    setLoading(false);
  }, [base, paperId, sourcesBase]);
  useEffect(() => {
    queueMicrotask(() => void load());
    return () => {
      seq.current += 1;
      sourceSeq.current += 1;
    };
  }, [load]);
  async function more() {
    if (!cursor) return;
    setSourceLoading(true);
    try {
      const page = await api.get<ReproductionSourcePage>(
        sourcesBase + "?limit=20&cursor=" + encodeURIComponent(cursor),
      );
      setSources((old) => [
        ...old,
        ...page.items.filter((item) => !old.some((row) => row.id === item.id)),
      ]);
      setCursor(page.page.next_cursor);
      setSourceError("");
    } catch (cause) {
      setSourceError(
        cause instanceof Error ? cause.message : "来源分页读取失败",
      );
    } finally {
      setSourceLoading(false);
    }
  }
  async function choose(id: string) {
    const token = ++sourceSeq.current;
    setSourceId(id);
    setSource(null);
    setRanges([]);
    setSelectionMode("FULL");
    invalidate();
    setSourceError("");
    if (!id) {
      setSourceLoading(false);
      return;
    }
    setSourceLoading(true);
    try {
      const value = await api.get<ReproductionSourceContent>(
        sourcesBase + "/" + encodeURIComponent(id),
      );
      if (value.paper_id !== paperId || value.id !== id)
        throw new Error("精读来源不属于当前论文。");
      if (token === sourceSeq.current) setSource(value);
    } catch (cause) {
      if (token === sourceSeq.current)
        setSourceError(
          cause instanceof Error ? cause.message : "精读笔记原文暂不可读",
        );
    } finally {
      if (token === sourceSeq.current) setSourceLoading(false);
    }
  }
  function sourceRequest(): PaperReproductionPreviewRequest {
    if (!source) throw new Error("请先选择实际精读笔记。");
    return {
      canonical_note_id: source.id,
      expected_note_sha256: source.note_sha256,
      selection_mode: selectionMode,
      excerpt_ranges: selectionMode === "EXCERPTS" ? ranges : [],
      stage,
      goal: goal.trim(),
    };
  }
  async function previewSource(event: FormEvent) {
    event.preventDefault();
    if (
      busyRef.current ||
      !source?.can_prepare ||
      (selectionMode === "EXCERPTS" && !ranges.length)
    )
      return;
    busyRef.current = true;
    setBusy(true);
    setError("");
    invalidate();
    try {
      setPreview(
        await api.post<PaperReproductionPreview>(
          base + "/preview",
          sourceRequest(),
        ),
      );
    } catch (cause) {
      setError(
        (cause instanceof Error ? cause.message : "来源预览失败") +
          "。原目标与选段保留；没有调用AI，也没有更换为新来源。",
      );
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }
  function clearPending() {
    pending.current = null;
    try {
      sessionStorage.removeItem(storageKey);
    } catch {
      /* in-memory nonce remains usable */
    }
  }
  async function inspectCreated() {
    if (!createdTask || busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    try {
      const value = await api.get<CodexTask>("/codex/tasks/" + createdTask.id);
      setCreatedTask(value);
      if (known.current) known.current = { ...known.current, task: value };
      setStartUnknown(false);
      setMessage(
        "已读取任务实际状态：" +
          codexStatusLabels[value.status] +
          "；未重复启动。",
      );
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "已创建任务的状态仍未确认",
      );
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }
  async function submit(start: boolean) {
    if (
      busyRef.current ||
      !preview ||
      !source ||
      !workspaceId ||
      (start && (!approved || startUnknown || !caps?.available))
    )
      return;
    busyRef.current = true;
    setBusy(true);
    setError("");
    setMessage("");
    let task: CodexTask | null = null;
    try {
      const body: PaperReproductionCreateRequest = {
        ...sourceRequest(),
        title: title.trim(),
        instructions: instructions.trim(),
        workspace_id: workspaceId,
        mode,
        expected_context_sha256: preview.context_sha256,
      };
      const signature = await requestSignature(body);
      if (known.current?.signature === signature) {
        task = await api.get<CodexTask>(
          "/codex/tasks/" + known.current.task.id,
        );
      } else {
        if (pending.current?.signature !== signature) {
          let saved: { signature?: unknown; key?: unknown } | null = null;
          try {
            saved = JSON.parse(sessionStorage.getItem(storageKey) ?? "null");
          } catch {
            /* optional browser storage */
          }
          pending.current = {
            signature,
            key:
              saved?.signature === signature &&
              typeof saved.key === "string" &&
              /^[0-9a-f-]{36}$/.test(saved.key)
                ? saved.key
                : crypto.randomUUID(),
          };
        }
        try {
          sessionStorage.setItem(storageKey, JSON.stringify(pending.current));
        } catch {
          /* same-page retry keeps nonce */
        }
        task = await api.post<CodexTask>(base, {
          ...body,
          idempotency_key: pending.current!.key,
        });
        clearPending();
      }
      known.current = { signature, task };
      setCreatedTask(task);
      if (!start) {
        setMessage("已保存冻结草稿，未调用AI。可在任务详情明确启动。");
        await load();
        return;
      }
      if (task.status !== "DRAFT") {
        setMessage(
          "任务已存在，实际状态：" +
            codexStatusLabels[task.status] +
            "；没有再次启动模型。",
        );
        return;
      }
      const frozen = await api.get<PaperReproductionPreview>(
        "/codex/tasks/" + task.id + "/paper-context",
      );
      if (
        frozen.context_sha256 !== preview.context_sha256 ||
        frozen.canonical_note_id !== source.id
      )
        throw new Error("已创建任务的冻结来源与此次预览不一致，尚未启动。");
      try {
        const result = await api.post<CodexTask>(
          "/codex/tasks/" + task.id + "/start",
          {},
        );
        setCreatedTask(result);
        known.current = { signature, task: result };
        setMessage(
          "已按本次明确批准启动：" +
            codexStatusLabels[result.status] +
            "。准备结果仍需实际复现与科学核验。",
        );
      } catch (cause) {
        try {
          const actual = await api.get<CodexTask>("/codex/tasks/" + task.id);
          setCreatedTask(actual);
          known.current = { signature, task: actual };
          setMessage(
            actual.status === "DRAFT"
              ? "冻结草稿已保留，实际状态仍为DRAFT，尚未启动。"
              : "启动回执未完整取得，任务实际状态：" +
                  codexStatusLabels[actual.status] +
                  "；未重复执行。",
          );
        } catch {
          setStartUnknown(true);
          setMessage(
            "启动结果尚未确认，已创建任务保留。请只读核对实际任务，不自动重发启动。",
          );
        }
        throw cause;
      }
      await load();
    } catch (cause) {
      if (
        cause instanceof ApiError &&
        cause.code === "REPRODUCTION_SOURCE_CHANGED"
      ) {
        clearPending();
        invalidate();
        setError(
          "来源已变化，冻结预览已失效。目标、说明及旧选段保留；重新载入会清空范围，请明确核对后再选。尚未替你接受新来源。",
        );
      } else
        setError(
          (cause instanceof Error ? cause.message : "保存或启动请求未确认") +
            "。已有任务与输入保留；相同草稿输入可复用请求编号，不会自动另开任务。",
        );
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }
  const workspace = workspaces.find((item) => item.id === workspaceId);
  const canPreview =
    !!source?.can_prepare &&
    !!goal.trim() &&
    (selectionMode === "FULL" || ranges.length > 0);
  const canCreate =
    !!preview &&
    !!title.trim() &&
    !!workspace?.available &&
    !!workspace.allowed_modes.includes(mode);
  const canStart = canCreate && !!caps?.available && approved && !startUnknown;
  if (loading && !paper)
    return <LoadingState label="正在读取实际精读来源和工作区…" />;
  if (!paper)
    return (
      <ErrorState
        message={error || "论文无法读取"}
        onRetry={() => void load()}
      />
    );
  return (
    <div className="space-y-5">
      <Link
        href={"/papers/" + paperId + "/analysis"}
        className="text-xs text-[var(--accent)] underline"
      >
        返回原PDF阅读工作区
      </Link>
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">科研方案与代码准备</h1>
        <p className="text-sm">{paper.title}</p>
        <p className="text-xs text-[var(--muted)]">
          选择已有原PDF精读产生的
          Markdown，不重新解析或精读。准备科研方案、代码改进和服务器交接说明；实验、模型试运行、训练、评价与仿真均只在课题组服务器进行。本机不执行科研实验，准备结果不代表复现成功。
        </p>
      </header>
      {error && <ErrorState message={error} />}
      {message && (
        <p
          role="status"
          className="rounded border border-[var(--accent)] p-3 text-sm"
        >
          {message}
        </p>
      )}
      <section className="space-y-3 rounded border border-[var(--border)] p-4">
        <h2 className="font-semibold">选择实际精读笔记</h2>
        {sourceError && <ErrorState message={sourceError} />}
        <label className="block space-y-1 text-xs">
          本论文已有原PDF精读来源
          <select
            aria-label="复现精读笔记来源"
            value={sourceId}
            disabled={busy || sourceLoading}
            className={selectClass}
            onChange={(event) => void choose(event.target.value)}
          >
            <option value="">选择一份已有完整精读笔记</option>
            {sources.map((item) => (
              <option key={item.id} value={item.id}>
                {new Date(item.created_at).toLocaleString("zh-CN")} ·{" "}
                {item.note_characters} 字符 · {item.skill_key}
                {item.can_prepare ? "" : " · 需核对来源"}
              </option>
            ))}
          </select>
        </label>
        {!sources.length && !loading && (
          <EmptyState
            title="尚无可选原PDF精读笔记"
            detail="回到原PDF阅读页主动提交精读。此页面不会自动补跑AI。"
          />
        )}
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            size="sm"
            variant="ghost"
            disabled={busy || sourceLoading}
            onClick={() => void load()}
          >
            刷新实际来源列表
          </Button>
          {cursor && (
            <Button
              type="button"
              size="sm"
              variant="secondary"
              disabled={busy || sourceLoading}
              onClick={() => void more()}
            >
              加载更多精读来源
            </Button>
          )}
          {sourceId && (
            <Button
              type="button"
              size="sm"
              variant="secondary"
              disabled={busy || sourceLoading}
              onClick={() => void choose(sourceId)}
            >
              重新载入当前来源并清空选段
            </Button>
          )}
        </div>
        {sourceLoading && <LoadingState label="正在读取已有精读Markdown…" />}
        {source && <ReproductionSourceView source={source} />}
      </section>
      {source && (
        <form
          className="space-y-4 rounded border border-[var(--border)] p-4"
          aria-label="Canonical复现准备"
          onSubmit={previewSource}
        >
          <fieldset disabled={busy} className="space-y-4">
            <div className="grid gap-3 md:grid-cols-2">
              <label className="space-y-1 text-xs">
                任务名称
                <Input
                  aria-label="复现任务名称"
                  maxLength={240}
                  required
                  value={title}
                  onChange={(event) => {
                    setTitle(event.target.value);
                    setApproved(false);
                  }}
                />
              </label>
              <label className="space-y-1 text-xs">
                准备阶段
                <select
                  aria-label="复现准备阶段"
                  className={selectClass}
                  value={stage}
                  onChange={(event) => {
                    setStage(event.target.value as typeof stage);
                    invalidate();
                  }}
                >
                  {Object.entries(reproductionStageLabels).map(
                    ([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ),
                  )}
                </select>
              </label>
              <label className="space-y-1 text-xs">
                精读笔记资料范围
                <select
                  aria-label="精读笔记资料范围"
                  className={selectClass}
                  value={selectionMode}
                  onChange={(event) => {
                    setSelectionMode(
                      event.target.value as typeof selectionMode,
                    );
                    invalidate();
                  }}
                >
                  <option value="FULL">整篇已有精读Markdown（不截断）</option>
                  <option value="EXCERPTS">本人明确的精确选段</option>
                </select>
              </label>
            </div>
            {selectionMode === "EXCERPTS" && (
              <ReproductionExcerptPicker
                source={source}
                ranges={ranges}
                disabled={busy}
                onChange={(value) => {
                  setRanges(value);
                  invalidate();
                }}
              />
            )}
            <label className="block space-y-1 text-xs">
              准备目标
              <Textarea
                aria-label="复现准备目标"
                required
                maxLength={4000}
                value={goal}
                onChange={(event) => {
                  setGoal(event.target.value);
                  invalidate();
                }}
              />
            </label>
            <label className="block space-y-1 text-xs">
              补充执行说明
              <Textarea
                aria-label="复现补充执行说明"
                maxLength={4000}
                value={instructions}
                onChange={(event) => {
                  setInstructions(event.target.value);
                  invalidate();
                }}
              />
            </label>
            <div className="grid gap-3 md:grid-cols-2">
              <label className="space-y-1 text-xs">
                科研工作区
                <select
                  aria-label="复现科研工作区"
                  className={selectClass}
                  value={workspaceId}
                  onChange={(event) => {
                    setWorkspaceId(event.target.value);
                    invalidate();
                  }}
                >
                  <option value="">选择工作区</option>
                  {workspaces.map((item) => (
                    <option
                      key={item.id}
                      value={item.id}
                      disabled={!item.available}
                    >
                      {item.name}
                      {item.available ? "" : " · 不可用"}
                    </option>
                  ))}
                </select>
              </label>
              <div className="space-y-1 text-xs">
                <p>资料处理模式</p>
                <p className="rounded border border-[var(--border)] px-3 py-2">
                  只读策划与代码建议
                </p>
              </div>
            </div>
            {workspace && (
              <p className="break-all text-xs text-[var(--muted)]">
                工作区：{workspace.path}。
                只读准备返回方案或代码建议。实际文件应用暂未支持，不修改工作区文件，不执行本机科研代码。
              </p>
            )}
            <Button type="submit" disabled={busy || !canPreview}>
              预览选定精读来源
            </Button>
          </fieldset>
        </form>
      )}
      {preview && (
        <>
          <ReproductionContextPanel
            context={preview}
            title="创建前的来源预览"
          />
          <section
            className="space-y-3 rounded border border-[var(--border)] p-4"
            aria-label="复现准备批准"
          >
            <p className="text-xs">
              本次外发：DERIVED_NOTE，发送上述明确选择的精读 Markdown
              与任务说明。原 PDF
              只绑定溯源，未发送；仍须满足全文来源资料外发权限。
            </p>
            <p className="text-xs text-[var(--muted)]">
              {caps?.budget_mode === "PROVIDER_QUOTA"
                ? "跟随 Codex 账户额度；已报告用量不是剩余额度。"
                : "本次本地软Token上限：" +
                  (caps?.max_tokens_per_task?.toLocaleString("zh-CN") ??
                    "未记录") +
                  "。"}{" "}
              执行超时、取消、未知结果核查和真实模型上下文限制仍适用。
            </p>
            <label className="flex items-start gap-2 text-xs">
              <input
                type="checkbox"
                aria-label="批准精读笔记外发并启动准备"
                checked={approved}
                disabled={busy}
                onChange={(event) => setApproved(event.target.checked)}
              />
              <span>
                我已核对实际派生笔记、目标、工作区与模式，批准此范围外发并开始准备。
              </span>
            </label>
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                disabled={busy || !canStart}
                onClick={() => void submit(true)}
              >
                批准并开始复现准备
              </Button>
              <Button
                type="button"
                variant="secondary"
                disabled={busy || !canCreate}
                onClick={() => void submit(false)}
              >
                仅保存复现准备草稿
              </Button>
            </div>
            <p className="text-xs text-[var(--muted)]">
              普通保存不调用AI。批准仅用于方案与代码准备，不批准本机实验或服务器提交；服务器执行须另有实际连接与授权。
            </p>
          </section>
        </>
      )}
      {createdTask && (
        <section
          className="space-y-2 rounded border border-[var(--border)] p-3"
          aria-label="已创建复现任务"
        >
          <p className="text-sm">
            已创建任务：{codexStatusLabels[createdTask.status]}
          </p>
          <Link
            href={"/ai-tasks/" + createdTask.id}
            className="inline-block text-sm text-[var(--accent)] underline"
          >
            查看已保存任务与真实执行记录
          </Link>
          <Button
            type="button"
            size="sm"
            variant="secondary"
            disabled={busy}
            onClick={() => void inspectCreated()}
          >
            只读核对已创建任务状态
          </Button>
        </section>
      )}
      <section className="space-y-3 rounded border border-[var(--border)] p-4">
        <h2 className="font-semibold">本论文的复现准备任务</h2>
        {historyError && (
          <ErrorState message={historyError} onRetry={() => void load()} />
        )}
        {history.length ? (
          <ul className="divide-y divide-[var(--border)]">
            {history.map((task) => (
              <li key={task.id} className="py-3 text-sm">
                <Link
                  href={"/ai-tasks/" + task.id}
                  className="text-[var(--accent)] underline"
                >
                  {task.title}
                </Link>
                <p className="mt-1 text-xs text-[var(--muted)]">
                  {formatCodexTime(task.created_at)} ·{" "}
                  {codexModeLabels[task.mode]} ·{" "}
                  {codexStatusLabels[task.status]}
                  。具体来源类型按任务详情的冻结记录显示。
                </p>
              </li>
            ))}
          </ul>
        ) : (
          !historyError && <EmptyState title="尚无复现准备草稿" />
        )}
      </section>
    </div>
  );
}
