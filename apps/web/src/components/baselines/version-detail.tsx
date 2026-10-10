"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { MarkdownViewer } from "@/components/markdown/markdown-viewer";
import { api } from "@/lib/api";
import { assetLabels } from "./version-editor";
import type { components } from "@/lib/generated";
type Version = components["schemas"]["BaselineVersionOut"];
type Capability = components["schemas"]["BaselineCapabilityOut"];
type Checks = components["schemas"]["BaselineMaterialCheckPage"];
type Check = components["schemas"]["BaselineMaterialCheckOut"];
const checkLabels: Record<string, string> = {
  MATERIALIZED: "材料观察齐备",
  INCOMPLETE: "材料观察存在缺口",
  FAILED: "材料核查失败",
};

export function BaselineVersionDetail({
  version,
  capability,
  onChanged,
  onExtend,
}: {
  version: Version;
  capability: Capability | null;
  onChanged: () => Promise<void>;
  onExtend: () => void;
}) {
  const endpoint = `/baseline-versions/${encodeURIComponent(version.id)}`;
  const [checks, setChecks] = useState<Checks | null>(null);
  const [selectedCheck, setSelectedCheck] = useState<Check | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState("");
  const [historyError, setHistoryError] = useState("");
  const [detailError, setDetailError] = useState("");
  const detailTarget = useRef("");
  const [index, setIndex] = useState(0);
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  const seq = useRef(0),
    detailSeq = useRef(0),
    busyRef = useRef(false);
  const historyRetry = useRef<{ cursor: string | null; index: number }>({
    cursor: null,
    index: 0,
  });
  const loadChecks = useCallback(
    async (cursor: string | null = null, at = 0) => {
      const token = ++seq.current;
      setLoading(true);
      historyRetry.current = { cursor, index: at };
      try {
        const result = await api.get<Checks>(
          `${endpoint}/checks?limit=20${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
        );
        if (token !== seq.current) return;
        setChecks(result);
        setIndex(at);
        setHistoryError("");
      } catch (cause) {
        if (token === seq.current)
          setHistoryError(
            cause instanceof Error ? cause.message : "无法读取材料核查历史",
          );
      } finally {
        if (token === seq.current) setLoading(false);
      }
    },
    [endpoint],
  );
  useEffect(() => {
    queueMicrotask(() => void loadChecks());
    return () => {
      seq.current += 1;
    };
  }, [loadChecks]);
  async function inspect(id: string) {
    detailTarget.current = id;
    const token = ++detailSeq.current;
    setDetailLoading(true);
    setDetailError("");
    try {
      const result = await api.get<Check>(
        `${endpoint}/checks/${encodeURIComponent(id)}`,
      );
      if (token === detailSeq.current) setSelectedCheck(result);
    } catch (cause) {
      if (token === detailSeq.current)
        setDetailError(
          cause instanceof Error ? cause.message : "无法读取文件观察详情",
        );
    } finally {
      if (token === detailSeq.current) setDetailLoading(false);
    }
  }
  async function checkMaterials() {
    if (
      busyRef.current ||
      !version.can_check_materials ||
      !capability?.materials_check_available
    )
      return;
    busyRef.current = true;
    setBusy(true);
    setError("");
    try {
      const result = await api.post<Check>(`${endpoint}/check-materials`, {
        expected_sha256: version.sha256,
      });
      setSelectedCheck(result);
      await loadChecks();
      await onChanged();
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "材料核查未完成；已有版本与观察记录保留。",
      );
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }
  return (
    <section
      className="space-y-4 rounded border border-[var(--border)] p-4"
      aria-label="固定基线版本详情"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-lg font-semibold">基线版本 {version.version}</h2>
        <Button
          type="button"
          size="sm"
          variant="secondary"
          disabled={busy}
          onClick={onExtend}
        >
          基于此版本补充新版本
        </Button>
      </div>
      <Link
        href={`/projects/${version.project_id}/baselines/${version.id}/runs`}
        className="inline-block text-sm text-[var(--accent)] underline"
      >
        查看历史本机运行记录（仅审计）
      </Link>
      <div className="grid gap-3 text-sm md:grid-cols-4">
        <div className="rounded border border-[var(--border)] p-3">
          <p className="font-medium">登记：CATALOGED</p>
          <p className="mt-1 text-xs text-[var(--muted)]">
            固定身份与材料声明已保存
          </p>
        </div>
        <div className="rounded border border-[var(--border)] p-3">
          <p className="font-medium">材料资格：{version.qualification}</p>
          <p className="mt-1 text-xs text-[var(--muted)]">
            依据已记录核查与当前绑定范围派生
          </p>
        </div>
        <div className="rounded border border-[var(--border)] p-3">
          <p className="font-medium">SMOKE：未支持</p>
          <p className="mt-1 text-xs text-[var(--muted)]">
            尚无受控隔离运行证据
          </p>
        </div>
        <div className="rounded border border-[var(--border)] p-3">
          <p className="font-medium">PROTOCOL：未支持</p>
          <p className="mt-1 text-xs text-[var(--muted)]">
            固定科学协议尚未实际验证
          </p>
        </div>
      </div>
      <p className="text-xs leading-5 text-[var(--muted)]">
        本轮只登记及核查已保存材料。环境锁文件核对不证明环境已安装；文件观察不授代码执行或科学接受。
      </p>
      {!version.scope_current && (
        <p
          role="alert"
          aria-label="基线来源范围变更"
          className="rounded border border-amber-500/40 p-3 text-xs"
        >
          当前来源绑定范围已变化，旧版本和核查记录保留；请核对缺口并登记新的材料范围。
        </p>
      )}
      {version.gaps.length > 0 && (
        <div
          className="space-y-1 rounded border border-amber-500/40 p-3 text-xs"
          aria-label="基线具体缺口"
        >
          <h3 className="font-medium">仍需处理的材料缺口</h3>
          {version.gaps.map((gap, index) => (
            <p key={`${gap}:${index}`} className="break-words">
              {gap}
            </p>
          ))}
        </div>
      )}
      {version.purpose && (
        <p className="whitespace-pre-wrap text-sm">{version.purpose}</p>
      )}
      <dl className="grid gap-3 text-xs md:grid-cols-2">
        <div>
          <dt className="text-[var(--muted)]">权重模式</dt>
          <dd>
            {version.weight_mode === "PRETRAINED"
              ? "使用预训练权重"
              : "从头训练声明"}
          </dd>
        </div>
        <div>
          <dt className="text-[var(--muted)]">版本登记时间</dt>
          <dd>{new Date(version.created_at).toLocaleString("zh-CN")}</dd>
        </div>
      </dl>
      {version.model_id ? (
        <Link
          href={`/models/${version.model_id}`}
          className="inline-block text-xs text-[var(--accent)] underline"
        >
          查看关联模型登记与版本
        </Link>
      ) : (
        <p className="text-xs text-[var(--muted)]">尚未绑定模型版本。</p>
      )}
      <details className="space-y-2 rounded border border-[var(--border)] p-3 text-xs">
        <summary className="cursor-pointer">版本身份与固定哈希</summary>
        <p className="mt-2 break-all font-mono">SHA-256：{version.sha256}</p>
        <p className="break-all">版本 ID：{version.id}</p>
        <p className="break-all">
          模型版本 ID：{version.model_version_id ?? "未绑定"}
        </p>
        {version.parent_version_id && (
          <>
            <p className="break-all">父版本 ID：{version.parent_version_id}</p>
            <p className="break-all font-mono">
              父版本 SHA-256：{version.parent_sha256 ?? "未记录"}
            </p>
          </>
        )}
      </details>
      <section className="space-y-2" aria-label="版本数据与许可用途">
        <h3 className="text-sm font-medium">数据版本与使用声明</h3>
        {version.datasets.length ? (
          version.datasets.map((item) => (
            <div
              key={item.dataset_version_id}
              className="space-y-1 rounded border border-[var(--border)] p-3 text-xs"
            >
              <p className="font-medium">
                {item.dataset_name} · {item.dataset_version}
              </p>
              <p className="whitespace-pre-wrap">
                许可确认：{item.license_confirmation}
              </p>
              <p className="whitespace-pre-wrap">
                使用范围：{item.usage_scope}
              </p>
              <Link
                href={`/datasets/${item.dataset_id}`}
                className="inline-block text-[var(--accent)] underline"
              >
                查看数据版本登记
              </Link>
              <details>
                <summary className="cursor-pointer">冻结的数据声明哈希</summary>
                <p className="break-all font-mono">{item.snapshot_sha256}</p>
              </details>
            </div>
          ))
        ) : (
          <p className="text-xs text-[var(--muted)]">尚无已声明数据版本。</p>
        )}
      </section>
      <section className="space-y-2" aria-label="固定材料与源资产">
        <h3 className="text-sm font-medium">
          必需材料 · {version.assets.length} 项
        </h3>
        {version.assets.length ? (
          <ul className="space-y-2">
            {version.assets.map((asset) => (
              <li
                key={asset.id}
                className="space-y-1 rounded border border-[var(--border)] p-3 text-xs"
              >
                <p className="break-all font-medium">
                  {assetLabels[asset.role]} · {asset.path}
                </p>
                <p>
                  来源 {asset.source_status} ·{" "}
                  {asset.size_bytes.toLocaleString("zh-CN")} 字节
                </p>
                {asset.source_gaps.map((gap, index) => (
                  <p
                    key={`${gap}:${index}`}
                    className="break-all text-amber-700 dark:text-amber-300"
                  >
                    来源缺口：{gap}
                  </p>
                ))}
                <div className="flex flex-wrap gap-3">
                  <Link
                    href={`/projects/${version.project_id}/sources/jobs/${asset.source_job_id}`}
                    className="text-[var(--accent)] underline"
                  >
                    查看原复制任务
                  </Link>
                  <a
                    href={`/api/v1/attachments/${asset.attachment_id}/download`}
                    className="text-[var(--accent)] underline"
                  >
                    读取已保存源文件
                  </a>
                </div>
                <details>
                  <summary className="cursor-pointer">
                    查看确切版本及来源回执
                  </summary>
                  <div className="mt-2 space-y-1 break-all font-mono">
                    <p>文件 SHA-256：{asset.sha256}</p>
                    <p>Commit：{asset.commit_sha}</p>
                    <p>来源计划 SHA-256：{asset.source_plan_sha256}</p>
                    <p>来源复制回执 SHA-256：{asset.source_receipt_sha256}</p>
                  </div>
                </details>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState title="此版本尚无必需文件声明" />
        )}
      </section>
      {version.notes && (
        <MarkdownViewer
          content={version.notes}
          label={`基线版本 ${version.version} 本人检查说明`}
        />
      )}
      {error && (
        <ErrorState
          message={error}
          onRetry={() =>
            void onChanged().catch((cause) =>
              setError(
                cause instanceof Error ? cause.message : "版本状态仍不可读",
              ),
            )
          }
        />
      )}
      {capability?.materials_check_available && (
        <Button
          type="button"
          disabled={busy || !version.can_check_materials}
          onClick={() => void checkMaterials()}
        >
          {busy ? "正在核查固定材料…" : "显式核查固定材料"}
        </Button>
      )}
      {!capability?.materials_check_available && (
        <p className="text-xs text-[var(--muted)]">
          当前材料核查能力未开放，已有登记与历史观察仍可查阅。
        </p>
      )}
      {capability && (
        <details className="rounded border border-[var(--border)] p-3 text-xs">
          <summary className="cursor-pointer">查看当前运行能力说明</summary>
          <p className="mt-2 whitespace-pre-wrap">{capability.detail}</p>
        </details>
      )}
      <section
        className="space-y-3 border-t border-[var(--border)] pt-4"
        aria-label="材料核查历史"
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-medium">材料核查记录</h3>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            disabled={busy || loading}
            onClick={() => void loadChecks(cursors[index] ?? null, index)}
          >
            刷新核查历史
          </Button>
        </div>
        {historyError && (
          <ErrorState
            message={historyError}
            onRetry={() =>
              void loadChecks(
                historyRetry.current.cursor,
                historyRetry.current.index,
              )
            }
          />
        )}
        {loading ? (
          <LoadingState label="正在读取历史材料观察…" />
        ) : checks?.items.length ? (
          <ul className="space-y-2">
            {checks.items.map((record) => (
              <li
                key={record.id}
                className="flex flex-wrap items-center justify-between gap-2 rounded border border-[var(--border)] p-3 text-xs"
              >
                <span>
                  {checkLabels[record.outcome] ?? record.outcome} ·{" "}
                  {new Date(record.checked_at).toLocaleString("zh-CN")}
                </span>
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  disabled={busy || detailLoading}
                  onClick={() => void inspect(record.id)}
                >
                  查看逐文件观察
                </Button>
              </li>
            ))}
          </ul>
        ) : (
          !historyError && <EmptyState title="此版本尚无真实材料核查记录" />
        )}
        {checks && (
          <div className="flex items-center justify-between gap-2 text-xs">
            <Button
              type="button"
              size="sm"
              variant="secondary"
              disabled={busy || loading || index === 0}
              onClick={() =>
                void loadChecks(cursors[index - 1] ?? null, index - 1)
              }
            >
              上一页核查记录
            </Button>
            <span>第 {index + 1} 页</span>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              disabled={busy || loading || !checks.page.next_cursor}
              onClick={() => {
                const next = checks.page.next_cursor;
                if (next) {
                  setCursors((old) => [...old.slice(0, index + 1), next]);
                  void loadChecks(next, index + 1);
                }
              }}
            >
              下一页核查记录
            </Button>
          </div>
        )}
      </section>
      {detailError && (
        <ErrorState
          message={detailError}
          onRetry={() => void inspect(detailTarget.current)}
        />
      )}
      {detailLoading && <LoadingState label="正在读取逐文件实际观察…" />}
      {selectedCheck && (
        <section
          className="space-y-2 rounded border border-[var(--border)] p-3"
          aria-label="逐文件材料观察"
        >
          <h3 className="text-sm font-medium">
            {checkLabels[selectedCheck.outcome] ?? selectedCheck.outcome}
          </h3>
          <p className="text-xs text-[var(--muted)]">
            以下是 {new Date(selectedCheck.checked_at).toLocaleString("zh-CN")}{" "}
            的核查事实，旧结果保留；当前文件可能随后变化。
          </p>
          {selectedCheck.gaps.map((gap, index) => (
            <p
              key={`${gap}:${index}`}
              className="break-all text-xs text-amber-700 dark:text-amber-300"
            >
              {gap}
            </p>
          ))}
          {selectedCheck.observations.length ? (
            <ul className="space-y-2">
              {selectedCheck.observations.map((observation) => (
                <li
                  key={observation.asset_id}
                  className="space-y-1 rounded border border-[var(--border)] p-2 text-xs"
                >
                  <p className="break-all font-medium">
                    {version.assets.find(
                      (asset) => asset.id === observation.asset_id,
                    )?.path ?? "历史材料条目"}{" "}
                    · {observation.status}
                  </p>
                  <p className="break-all font-mono">
                    实际 SHA-256：{observation.actual_sha256 ?? "未取得"}
                  </p>
                  <p>实际字节：{observation.actual_size_bytes ?? "未取得"}</p>
                  {observation.issue && (
                    <p className="break-words">{observation.issue}</p>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-[var(--muted)]">
              此核查没有文件观察条目。
            </p>
          )}
          <details className="text-xs">
            <summary className="cursor-pointer">核查器与版本哈希</summary>
            <div className="mt-2 space-y-1 break-all font-mono">
              <p>
                {selectedCheck.checker_version} · {selectedCheck.checker_sha256}
              </p>
              <p>目标版本 SHA-256：{selectedCheck.version_sha256}</p>
              <p>记录 ID：{selectedCheck.id}</p>
            </div>
          </details>
        </section>
      )}
    </section>
  );
}
