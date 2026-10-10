"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { components } from "@/lib/generated";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardHeader, CardContent } from "@/components/ui/card";
import { MarkdownViewer } from "@/components/markdown/markdown-viewer";
import { message, type Claim, type ClaimPage } from "./types";
import { useClaimPending, type ClaimPending } from "./use-pending";
type Selection = components["schemas"]["EvidenceBundleSelection"];
type Preview = components["schemas"]["EvidenceBundlePreview"];
type Bundle = components["schemas"]["EvidenceBundleOut"];
type BundlePage = components["schemas"]["EvidenceBundlePage"];
export function EvidenceBundles({ projectId }: { projectId: string }) {
  const endpoint = `/projects/${projectId}/evidence-bundles`,
    recovery = useClaimPending(projectId, "evidence-bundles");
  const [claims, setClaims] = useState<ClaimPage | null>(null),
    [selection, setSelection] = useState<Selection>({
      label: "科研证据与写作资料",
      claims: [],
    }),
    [preview, setPreview] = useState<Preview | null>(null),
    [page, setPage] = useState<BundlePage | null>(null),
    [detail, setDetail] = useState<Bundle | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [ack, setAck] = useState(false),
    [approve, setApprove] = useState(false),
    [retryAck, setRetryAck] = useState(false);
  const operating = useRef(false);
  const loadHistory = useCallback(
    async (cursor?: string | null) => {
      setPage(
        await api.get<BundlePage>(
          `${endpoint}?limit=10${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
        ),
      );
    },
    [endpoint],
  );
  async function action(fn: () => Promise<void>) {
    if (operating.current) return;
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
  useEffect(() => {
    void Promise.resolve()
      .then(() => loadHistory())
      .catch((cause) => setError(message(cause)));
  }, [loadHistory]);
  async function listClaims(cursor?: string | null) {
    await action(async () => {
      setClaims(
        await api.get<ClaimPage>(
          `/claims?project_id=${projectId}&limit=20${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
        ),
      );
    });
  }
  function changed(value: Selection) {
    setSelection(value);
    setPreview(null);
    setAck(false);
    setApprove(false);
  }
  async function add(id: string) {
    await action(async () => {
      const value = await api.get<Claim>(`/claims/${id}`);
      if (value.project_id !== projectId)
        throw new Error("所选主张不属于本课题");
      if (selection.claims.length >= 20)
        throw new Error("最多选择20个不同主张");
      changed({
        ...selection,
        claims: [
          ...selection.claims,
          {
            claim_id: value.id,
            revision_id: value.current.id,
            expected_revision_sha256: value.current.sha256,
          },
        ],
      });
    });
  }
  async function transmit(record: ClaimPending) {
    const value = await api.post<Bundle>(record.path, record.body);
    if (value.project_id !== projectId)
      throw new Error("资料包回执不属于本课题");
    recovery.clear();
    setDetail(value);
    setNotice("资料包保存回执已返回；仅READY且文件完整时可下载。");
    await loadHistory();
  }
  async function create() {
    if (!preview) return;
    await action(async () => {
      const request = recovery.freeze(
        endpoint,
        {
          selection: preview.selection,
          expected_preview_sha256: preview.preview_sha256,
          approve_bundle: true,
          acknowledge_gaps: ack,
        },
        "写作资料包",
      );
      await transmit(request);
    });
  }
  async function lookup() {
    if (!recovery.pending) return;
    const record = recovery.pending;
    await action(async () => {
      try {
        const path =
          record.path === endpoint
            ? `${endpoint}/lookup?key=${encodeURIComponent(record.body.idempotency_key)}`
            : `${endpoint}/${record.path.split("/").at(-2)}`;
        const value = await api.get<Bundle>(path);
        if (value.project_id !== projectId)
          throw new Error("核查回执不属于本课题");
        const key = record.body.idempotency_key;
        if (
          record.path !== endpoint &&
          !value.attempts.some((v) => v.idempotency_key === key)
        )
          throw new Error("该保存重试尚未取得回执，请继续原请求");
        recovery.clear();
        setDetail(value);
        setNotice("已核查原保存回执，没有自动重发。");
        await loadHistory();
      } catch (cause) {
        if (cause instanceof ApiError && cause.status === 404) {
          setNotice("核查尚未发现原保存，请继续原冻结请求；没有自动重发。");
          return;
        }
        throw cause;
      }
    });
  }
  async function retry() {
    if (!detail) return;
    await action(async () => {
      const req = recovery.freeze(
        `${endpoint}/${detail.id}/retry-save`,
        {
          expected_preview_sha256: detail.preview_sha256,
          acknowledge_unknown: true,
        },
        "原资料包保存重试",
      );
      await transmit(req);
    });
  }
  return (
    <Card>
      <CardHeader>
        <h2 className="font-semibold">证据与写作资料包</h2>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-xs text-[var(--muted)]">
          选定主张版本→预览真实文本文件→本人批准保存ZIP。包含候选/人工结论、支持与反证、来源哈希与参考元数据；不含PDF、权重、数据或原产物文件，不证明引用支撑或科学有效，不自动投稿。
        </p>
        {error && (
          <p role="alert" className="text-sm text-[var(--danger)]">
            {error}
          </p>
        )}
        {notice && <p role="status">{notice}</p>}
        {recovery.warning && <p role="alert">{recovery.warning}</p>}
        {recovery.pending && (
          <div className="space-y-2 rounded border p-3">
            <p>待核查：{recovery.pending.label}</p>
            <details>
              <summary>核对冻结保存输入</summary>
              <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-all text-xs">
                {JSON.stringify(recovery.pending.body, null, 2)}
              </pre>
            </details>
            <Button disabled={busy} onClick={() => void lookup()}>
              只读核查资料包保存
            </Button>
            <Button
              disabled={busy}
              onClick={() =>
                void action(async () => transmit(recovery.pending!))
              }
            >
              继续原资料包请求
            </Button>
          </div>
        )}
        <details>
          <summary>选择主张并预览资料</summary>
          <div className="mt-3 space-y-3">
            <label className="block text-sm">
              资料包名称
              <Input
                aria-label="资料包名称"
                maxLength={240}
                value={selection.label}
                disabled={busy || !!recovery.pending}
                onChange={(e) =>
                  changed({ ...selection, label: e.target.value })
                }
              />
            </label>
            <Button
              disabled={busy || !!recovery.pending}
              onClick={() => void listClaims()}
            >
              读取可选主张
            </Button>
            {claims && !claims.items.length && (
              <p>暂无科研主张，请先创建候选与证据。</p>
            )}
            {claims?.items.map((row) => (
              <div
                className="flex flex-wrap items-center justify-between gap-2 rounded border p-2 text-xs"
                key={row.id}
              >
                <span>
                  {row.title} · 当前版本 {row.revision}
                </span>
                <Button
                  size="sm"
                  disabled={
                    busy ||
                    !!recovery.pending ||
                    selection.claims.some((c) => c.claim_id === row.id)
                  }
                  onClick={() => void add(row.id)}
                >
                  选择当前主张版本
                </Button>
              </div>
            ))}
            {claims?.page.next_cursor && (
              <Button
                size="sm"
                disabled={busy}
                onClick={() => void listClaims(claims.page.next_cursor)}
              >
                下一页可选主张
              </Button>
            )}
            {selection.claims.map((row) => (
              <div
                className="flex flex-wrap items-center gap-2 text-xs"
                key={row.claim_id}
              >
                <span className="break-all">
                  已选主张 {row.claim_id} · 版本 {row.revision_id} · SHA{" "}
                  {row.expected_revision_sha256}
                </span>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={busy || !!recovery.pending}
                  onClick={() =>
                    changed({
                      ...selection,
                      claims: selection.claims.filter(
                        (v) => v.claim_id !== row.claim_id,
                      ),
                    })
                  }
                >
                  移除资料包主张
                </Button>
              </div>
            ))}
            <Button
              disabled={
                busy ||
                !!recovery.pending ||
                !selection.claims.length ||
                !selection.label.trim()
              }
              onClick={() =>
                void action(async () => {
                  setPreview(
                    await api.post<Preview>(`${endpoint}/preview`, selection),
                  );
                  setAck(false);
                  setApprove(false);
                })
              }
            >
              预览证据资料包
            </Button>
          </div>
        </details>
        {preview && (
          <section
            className="space-y-2 rounded border p-3"
            aria-label="资料包保存预览"
          >
            <p className="break-all text-xs">
              预览SHA {preview.preview_sha256} · ZIP SHA {preview.bundle_sha256}{" "}
              · {preview.bundle_size_bytes} bytes
            </p>
            <ul className="list-disc pl-5 text-xs">
              {preview.gaps.map((g, i) => (
                <li key={i}>{g}</li>
              ))}
            </ul>
            {preview.files.map((file) => (
              <details key={file.path}>
                <summary>
                  {file.path} · {file.size_bytes} bytes
                </summary>
                <p className="break-all text-xs">SHA {file.sha256}</p>
                <MarkdownViewer
                  content={file.content}
                  label={`资料文件 ${file.path}`}
                />
              </details>
            ))}
            <label className="flex gap-2 text-sm">
              <input
                type="checkbox"
                disabled={busy || !!recovery.pending}
                checked={ack}
                onChange={(e) => setAck(e.target.checked)}
              />
              已核查证据缺口、原文及引用未核验边界
            </label>
            <label className="flex gap-2 text-sm">
              <input
                type="checkbox"
                disabled={busy || !!recovery.pending}
                checked={approve}
                onChange={(e) => setApprove(e.target.checked)}
              />
              批准将当前预览保存为本地写作资料包
            </label>
            <Button
              disabled={
                busy ||
                !!recovery.pending ||
                !recovery.ready ||
                !approve ||
                (preview.gaps.length > 0 && !ack)
              }
              onClick={() => void create()}
            >
              保存证据资料包
            </Button>
          </section>
        )}
        <section className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-medium">资料包历史</h3>
            <Button
              size="sm"
              variant="ghost"
              disabled={busy}
              onClick={() => void action(async () => loadHistory())}
            >
              刷新资料包历史
            </Button>
          </div>
          {page && !page.items.length && (
            <p className="text-xs text-[var(--muted)]">尚未保存写作资料包。</p>
          )}
          {page?.items.map((row) => (
            <Button
              key={row.id}
              size="sm"
              variant="ghost"
              disabled={busy}
              onClick={() =>
                void action(async () =>
                  setDetail(await api.get<Bundle>(`${endpoint}/${row.id}`)),
                )
              }
            >
              {row.label} · {row.status}
            </Button>
          ))}
          {page?.page.next_cursor && (
            <Button
              size="sm"
              disabled={busy}
              onClick={() =>
                void action(async () => loadHistory(page.page.next_cursor))
              }
            >
              下一页资料包历史
            </Button>
          )}
        </section>
        {detail && (
          <section
            className="space-y-3 rounded border p-3"
            aria-label="写作资料包回执"
          >
            <h3 className="font-medium">
              {detail.label} · {detail.status}
            </h3>
            {!detail.context_current && (
              <p role="alert" className="text-sm">
                原来源或审阅已变化；以下是冻结历史写作资料，不代表当前结论。
              </p>
            )}
            {detail.current_gaps.length > 0 && (
              <ul className="list-disc pl-5 text-xs">
                {detail.current_gaps.map((gap, i) => (
                  <li key={i}>{gap}</li>
                ))}
              </ul>
            )}
            <p className="break-all text-xs">
              资料包SHA {detail.bundle_sha256} · {detail.bundle_size_bytes}{" "}
              bytes ·{" "}
              {detail.integrity_valid ? "冻结文本完整" : "冻结文本需核查"}
            </p>
            {detail.status === "READY" &&
              detail.attachment_id &&
              detail.integrity_valid && (
                <a
                  className="text-sm text-[var(--accent)] underline"
                  href={`/api/v1${endpoint}/${detail.id}/download`}
                >
                  下载证据与写作ZIP
                </a>
              )}
            {detail.files.map((file) => (
              <details key={file.path}>
                <summary>查看保存文件 {file.path}</summary>
                <MarkdownViewer
                  content={file.content}
                  label={`保存文件 ${file.path}`}
                />
              </details>
            ))}
            <details>
              <summary>保存尝试与文件事实</summary>
              <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-all text-xs">
                {JSON.stringify(detail.attempts, null, 2)}
              </pre>
            </details>
            {["NEEDS_ATTENTION", "FAILED"].includes(detail.status) && (
              <div className="space-y-2">
                <label className="flex gap-2 text-sm">
                  <input
                    type="checkbox"
                    disabled={busy || !!recovery.pending}
                    checked={retryAck}
                    onChange={(e) => setRetryAck(e.target.checked)}
                  />
                  理解原保存可能已有文件，只重试同一冻结资料包的存储
                </label>
                <Button
                  disabled={
                    busy ||
                    !!recovery.pending ||
                    !retryAck ||
                    !detail.integrity_valid
                  }
                  onClick={() => void retry()}
                >
                  重试保存原资料包
                </Button>
              </div>
            )}
          </section>
        )}
      </CardContent>
    </Card>
  );
}
