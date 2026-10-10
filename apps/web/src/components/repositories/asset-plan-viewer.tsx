"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { api } from "@/lib/api";
import type { components } from "@/lib/generated";
type Plan = components["schemas"]["AssetPlanOut"];
type FilePage = components["schemas"]["AssetPlanFilePage"];
type Capability = components["schemas"]["AssetCapabilityOut"];
type Create = components["schemas"]["AssetPlanCreate"];

export function AssetPlanViewer({
  plan,
  capability,
  busy,
  onPreview,
  onApprove,
}: {
  plan: Plan;
  capability: Capability | null;
  busy: boolean;
  onPreview: (body: Create) => Promise<void>;
  onApprove: () => Promise<void>;
}) {
  const [page, setPage] = useState<FilePage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  const [index, setIndex] = useState(0);
  const [subset, setSubset] = useState(false);
  const [paths, setPaths] = useState<string[]>([]);
  const [byteLimit, setByteLimit] = useState(String(plan.max_bytes));
  const [fileLimit, setFileLimit] = useState(String(plan.max_files));
  const [confirmed, setConfirmed] = useState(false);
  const sequence = useRef(0);
  const load = useCallback(
    async (cursor: string | null, pageIndex: number) => {
      const current = ++sequence.current;
      setLoading(true);
      setError("");
      try {
        const result = await api.get<FilePage>(
          `/repository-asset-plans/${plan.id}/files?limit=50${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
        );
        if (current === sequence.current) {
          setPage(result);
          setIndex(pageIndex);
        }
      } catch (cause) {
        if (current === sequence.current)
          setError(cause instanceof Error ? cause.message : "资产库存暂不可读");
      } finally {
        if (current === sequence.current) setLoading(false);
      }
    },
    [plan.id],
  );
  useEffect(() => {
    let active = true;
    void Promise.resolve().then(() => {
      if (active) void load(null, 0);
    });
    return () => {
      active = false;
      sequence.current += 1;
    };
  }, [load]);
  async function selectedPreview() {
    if (!capability?.enabled || busy || (subset && !paths.length)) return;
    await onPreview({
      selected_paths: subset ? paths : null,
      max_bytes: Number(byteLimit),
      max_files: Number(fileLimit),
    });
  }
  const unchangedLimits =
    Number(byteLimit) === plan.max_bytes &&
    Number(fileLimit) === plan.max_files;
  return (
    <Card>
      <CardHeader>
        <h3 className="font-semibold">冻结资产清单 · {plan.state}</h3>
        <span className="text-xs text-[var(--muted)]">{plan.scope}</span>
      </CardHeader>
      <CardContent className="space-y-4 text-xs">
        <dl className="grid gap-3 sm:grid-cols-2">
          {[
            [
              "Provider / 仓库",
              `${plan.provider_key} / ${plan.repo_kind} / ${plan.repo_id}`,
            ],
            ["Provider 身份", plan.provider_id],
            ["固定 Commit", plan.commit_sha],
            ["许可证", plan.license_id || "来源未提供，使用前需核对"],
            ["来源快照 ID", plan.source_snapshot_id],
            [
              "清单文件 / 总预计字节",
              `${plan.total_files} / ${plan.total_bytes === null ? "未知" : plan.total_bytes.toLocaleString("zh-CN")}`,
            ],
            [
              "已冻结选择 / 预计字节",
              `${plan.selected_files} / ${plan.selected_bytes.toLocaleString("zh-CN")}`,
            ],
            ["计划 SHA-256", plan.plan_sha256],
            ["库存 Manifest SHA-256", plan.manifest_sha256],
            ["批准的 SHA-256", plan.approved_hash || "尚未批准"],
          ].map(([label, value]) => (
            <div key={label}>
              <dt className="text-[var(--muted)]">{label}</dt>
              <dd className="mt-1 break-all font-mono">{value}</dd>
            </div>
          ))}
        </dl>
        <p className="leading-5 text-[var(--muted)]">
          预览只读取官方元数据，没有下载文件载荷。远端 digest
          是上游身份核验字段，下载后的实际 SHA-256 和字节数另行记录。
        </p>
        {plan.gaps.length > 0 && (
          <section aria-label="资产库存缺口">
            <ul className="space-y-1 text-[var(--muted)]">
              {plan.gaps.map((gap, at) => (
                <li key={`${gap}:${at}`}>{gap}</li>
              ))}
            </ul>
          </section>
        )}
        {!plan.inventory_complete && (
          <p className="text-[var(--danger)]">
            库存未完整取得或被截断，不能批准这份下载计划。
          </p>
        )}
        <div className="flex flex-wrap gap-4">
          <label className="space-y-1.5">
            总下载字节限制
            <Input
              type="number"
              min={1}
              max={capability?.max_bytes ?? 1073741824}
              step={1}
              value={byteLimit}
              disabled={busy || !capability?.enabled}
              onChange={(event) => {
                setByteLimit(event.target.value);
                setConfirmed(false);
              }}
            />
          </label>
          <label className="space-y-1.5">
            文件数量限制
            <Input
              type="number"
              min={1}
              max={capability?.max_files ?? 10000}
              step={1}
              value={fileLimit}
              disabled={busy || !capability?.enabled}
              onChange={(event) => {
                setFileLimit(event.target.value);
                setConfirmed(false);
              }}
            />
          </label>
        </div>
        {capability?.enabled && (
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={subset}
              disabled={busy}
              onChange={(event) => {
                setSubset(event.target.checked);
                setPaths([]);
                setConfirmed(false);
              }}
            />
            改为明确选择下载子集
          </label>
        )}
        {subset && (
          <p className="leading-5 text-[var(--muted)]">
            只下载本人勾选的路径。已选择 {paths.length}{" "}
            个文件；未勾选或尚未翻页查看的文件不会被默认为选择。子集缓存只能
            PARTIAL，不是完整基线。
          </p>
        )}
        {error && (
          <ErrorState
            message={error}
            onRetry={() => void load(cursors[index] ?? null, index)}
          />
        )}
        {loading && <LoadingState label="正在读取固定版本库存…" />}
        {!loading &&
          page &&
          (page.items.length ? (
            <div className="overflow-x-auto rounded border border-[var(--border)]">
              <table className="w-full text-left">
                <caption className="sr-only">
                  固定仓库版本的资产路径、预期大小和远端校验信息
                </caption>
                <thead>
                  <tr>
                    <th scope="col" className="p-2">
                      路径 / 选择
                    </th>
                    <th scope="col" className="p-2">
                      类型 / 字节
                    </th>
                    <th scope="col" className="p-2">
                      远端 digest / 支持情况
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {page.items.map((file) => (
                    <tr
                      key={file.file_key_sha256}
                      className="border-t border-[var(--border)]"
                    >
                      <td className="p-2">
                        {subset ? (
                          <label className="flex items-start gap-2">
                            <input
                              aria-label={`选择资产：${file.path}`}
                              type="checkbox"
                              checked={paths.includes(file.path)}
                              disabled={
                                busy ||
                                !file.supported ||
                                file.size_bytes === null ||
                                !file.digest_algorithm ||
                                !file.digest ||
                                (paths.length >= 1000 &&
                                  !paths.includes(file.path))
                              }
                              onChange={(event) =>
                                setPaths((old) =>
                                  event.target.checked
                                    ? [...old, file.path]
                                    : old.filter((path) => path !== file.path),
                                )
                              }
                            />
                            <span className="break-all">{file.path}</span>
                          </label>
                        ) : (
                          <>
                            <p className="break-all">{file.path}</p>
                            <p className="text-[var(--muted)]">
                              {file.selected ? "计划已选择" : "计划未选择"}
                            </p>
                          </>
                        )}
                      </td>
                      <td className="p-2">
                        <p>{file.file_kind}</p>
                        <p>
                          {file.size_bytes === null
                            ? "大小未知"
                            : `${file.size_bytes.toLocaleString("zh-CN")} 字节`}
                        </p>
                      </td>
                      <td className="space-y-1 p-2">
                        <p className="break-all font-mono">
                          {file.digest_algorithm || "digest 未知"} ·{" "}
                          {file.digest || "未记录"}
                        </p>
                        <p>
                          {file.supported
                            ? "支持此载荷"
                            : "不支持，不跟随或执行"}
                        </p>
                        {file.issue && (
                          <p className="break-words text-[var(--muted)]">
                            {file.issue}
                          </p>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState title="此库存没有文件条目" />
          ))}
        <div className="flex items-center justify-between gap-2">
          <Button
            size="sm"
            variant="secondary"
            disabled={busy || loading || index === 0}
            onClick={() => void load(cursors[index - 1] ?? null, index - 1)}
          >
            上一页库存
          </Button>
          <span>第 {index + 1} 页</span>
          <Button
            size="sm"
            variant="secondary"
            disabled={busy || loading || !page?.page.next_cursor}
            onClick={() => {
              const next = page?.page.next_cursor;
              if (next) {
                setCursors((old) => [...old.slice(0, index + 1), next]);
                void load(next, index + 1);
              }
            }}
          >
            下一页库存
          </Button>
        </div>
        {capability?.enabled && (
          <Button
            size="sm"
            variant="secondary"
            disabled={busy || (subset && !paths.length)}
            onClick={() => void selectedPreview()}
          >
            {subset ? "按所选文件生成新清单预览" : "按当前限制重新预览清单"}
          </Button>
        )}
        {plan.state === "DRAFT" && capability?.enabled && (
          <div className="space-y-3">
            <label className="flex items-start gap-2 leading-5">
              <input
                aria-label="批准固定清单资产下载"
                type="checkbox"
                checked={confirmed}
                disabled={
                  busy || !plan.can_approve || subset || !unchangedLimits
                }
                onChange={(event) => setConfirmed(event.target.checked)}
              />
              本人批准按此确切 Commit、清单
              SHA、文件选择与限制下载到平台受管理缓存。不执行仓库代码、不训练，不授予基线资格。
            </label>
            <Button
              disabled={
                busy ||
                !confirmed ||
                !plan.can_approve ||
                subset ||
                !unchangedLimits
              }
              onClick={() => void onApprove()}
            >
              批准并自动创建下载任务
            </Button>
            {!plan.can_approve && (
              <p className="text-[var(--muted)]">
                服务端未允许批准：请核对完整库存、已选文件的已知大小/digest及限制。
              </p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
