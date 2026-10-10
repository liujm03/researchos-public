"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { api } from "@/lib/api";
import type { components } from "@/lib/generated";
type Plan = components["schemas"]["ProjectSourcePlanOut"];
type FilePage = components["schemas"]["ProjectSourcePlanFilePage"];

export function ProjectSourcePlanViewer({
  plan,
  enabled,
  busy,
  onApprove,
}: {
  plan: Plan;
  enabled: boolean;
  busy: boolean;
  onApprove: () => Promise<void>;
}) {
  const [files, setFiles] = useState<FilePage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [index, setIndex] = useState(0);
  const [cursors, setCursors] = useState<(string | null)[]>([null]);
  const seq = useRef(0);
  const load = useCallback(
    async (cursor: string | null, pageIndex: number) => {
      const current = ++seq.current;
      setLoading(true);
      setError("");
      try {
        const value = await api.get<FilePage>(
          `/project-source-plans/${plan.id}/files?limit=50${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
        );
        if (current === seq.current) {
          setFiles(value);
          setIndex(pageIndex);
        }
      } catch (cause) {
        if (current === seq.current)
          setError(
            cause instanceof Error ? cause.message : "冻结复制文件清单不可读",
          );
      } finally {
        if (current === seq.current) setLoading(false);
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
      seq.current += 1;
    };
  }, [load]);
  return (
    <Card>
      <CardHeader>
        <h2 className="font-semibold">项目源码复制计划 · {plan.state}</h2>
        <span className="text-xs text-[var(--muted)]">
          {plan.source_status}
        </span>
      </CardHeader>
      <CardContent className="space-y-4 text-xs">
        <p className="leading-5 text-[var(--muted)]">
          将已保存资产的原始字节复制到以下项目目录；复制不会执行代码或训练。
        </p>
        <dl className="grid gap-3 sm:grid-cols-2">
          {[
            ["固定项目根目录", plan.root_label],
            ["固定相对缓存目录", plan.binding.relative_path],
            [
              "来源 Provider / 仓库",
              `${plan.provider_key} / ${plan.repo_kind} / ${plan.repo_id}`,
            ],

            ["固定 Commit", plan.commit_sha],

            [
              "实际文件 / 字节",
              `${plan.file_count} / ${plan.total_bytes.toLocaleString("zh-CN")}`,
            ],

            [
              "路径授权",
              plan.binding.state === "ACTIVE"
                ? "已批准"
                : plan.binding.state === "REVOKED"
                  ? "已撤销"
                  : "待批准",
            ],
          ].map(([label, value]) => (
            <div key={label}>
              <dt className="text-[var(--muted)]">{label}</dt>
              <dd className="mt-1 break-all font-mono">{value}</dd>
            </div>
          ))}
        </dl>
        <details className="rounded border border-[var(--border)]">
          <summary className="cursor-pointer p-3">来源身份与校验详情</summary>
          <div className="p-3 pt-0">
            {" "}
            <dl className="grid gap-3 sm:grid-cols-2">
              {[
                ["固定项目根目录", plan.root_label],
                ["固定相对缓存目录", plan.binding.relative_path],
                [
                  "来源 Provider / 仓库",
                  `${plan.provider_key} / ${plan.repo_kind} / ${plan.repo_id}`,
                ],
                ["Provider 身份", plan.provider_id],
                ["固定 Commit", plan.commit_sha],
                ["资产 Snapshot ID", plan.asset_snapshot_id],
                [
                  "实际文件 / 字节",
                  `${plan.file_count} / ${plan.total_bytes.toLocaleString("zh-CN")}`,
                ],
                ["资产 Manifest SHA-256", plan.asset_manifest_sha256],
                ["复制计划 SHA-256", plan.plan_sha256],
                ["批准 SHA-256", plan.approved_hash || "尚未批准"],
                [
                  "路径绑定 ID / 状态",
                  `${plan.path_binding_id} / ${plan.binding.state}`,
                ],
                ["项目根指纹", plan.binding.root_fingerprint],
                ["路径范围 SHA-256", plan.binding.scope_sha256],
              ]
                .filter(
                  ([label]) =>
                    ![
                      "固定项目根目录",
                      "固定相对缓存目录",
                      "来源 Provider / 仓库",
                      "固定 Commit",
                      "实际文件 / 字节",
                    ].includes(label),
                )
                .map(([label, value]) => (
                  <div key={label}>
                    <dt className="text-[var(--muted)]">{label}</dt>
                    <dd className="mt-1 break-all font-mono">{value}</dd>
                  </div>
                ))}
            </dl>
          </div>
        </details>
        {plan.source_status === "PARTIAL" && (
          <p className="text-amber-700 dark:text-amber-300">
            来源保持
            PARTIAL；只复制实际取得成员，不能补齐缺失分片、外部数据或变成已验证基线。
          </p>
        )}
        {plan.gaps.length > 0 && (
          <section aria-label="源码计划缺口">
            <ul className="space-y-1 text-[var(--muted)]">
              {plan.gaps.map((gap, at) => (
                <li key={`${gap}:${at}`}>{gap}</li>
              ))}
            </ul>
          </section>
        )}
        <p className="leading-5">
          缓存无覆盖写入，已有人工或不同内容会保留并提示冲突。第三方资料不进入项目正常代码推送；这不是
          Git clone/fetch 历史，也未授模型、代码执行或训练权限。
        </p>
        {error && (
          <ErrorState
            message={error}
            onRetry={() => void load(cursors[index] ?? null, index)}
          />
        )}
        {loading && <LoadingState label="正在读取完整固定文件库存…" />}
        {!loading &&
          files &&
          (files.items.length ? (
            <div className="overflow-x-auto rounded border border-[var(--border)]">
              <table className="w-full text-left">
                <caption className="sr-only">
                  实际缓存成员与目标相对路径、完整哈希和字节
                </caption>
                <thead>
                  <tr>
                    <th scope="col" className="p-2">
                      路径
                    </th>
                    <th scope="col" className="p-2">
                      实测 SHA-256
                    </th>
                    <th scope="col" className="p-2">
                      字节 / 来源成员
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {files.items.map((file) => (
                    <tr
                      key={file.file_key_sha256}
                      className="border-t border-[var(--border)]"
                    >
                      <td className="break-all p-2">{file.path}</td>
                      <td className="break-all p-2 font-mono">{file.sha256}</td>
                      <td className="p-2">
                        <p>{file.size_bytes.toLocaleString("zh-CN")}</p>
                        <p className="break-all font-mono">
                          AssetFile {file.asset_file_id}
                        </p>
                        <p className="break-all font-mono">
                          Attachment {file.attachment_id}
                        </p>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState title="没有可复制的实际文件成员" />
          ))}
        <div className="flex items-center justify-between">
          <Button
            size="sm"
            variant="secondary"
            disabled={busy || loading || index === 0}
            onClick={() => void load(cursors[index - 1] ?? null, index - 1)}
          >
            上一页复制文件
          </Button>
          <span>
            第 {index + 1} 页 · 总文件 {plan.file_count}
          </span>
          <Button
            size="sm"
            variant="secondary"
            disabled={busy || loading || !files?.page.next_cursor}
            onClick={() => {
              const next = files?.page.next_cursor;
              if (next) {
                setCursors((old) => [...old.slice(0, index + 1), next]);
                void load(next, index + 1);
              }
            }}
          >
            下一页复制文件
          </Button>
        </div>
        {plan.state === "DRAFT" && enabled && (
          <div className="space-y-3">
            <label className="flex items-start gap-2 leading-5">
              <input
                aria-label="批准固定项目源码缓存复制"
                type="checkbox"
                checked={confirmed}
                disabled={busy || !plan.can_approve || !files || !!error}
                onChange={(event) => setConfirmed(event.target.checked)}
              />
              本人批准将此确切资产 Snapshot、文件与 SHA
              按固定绑定目录无覆盖复制，仅建立源码缓存及核验回执。
            </label>
            <Button
              disabled={
                busy || !confirmed || !plan.can_approve || !files || !!error
              }
              onClick={() => void onApprove()}
            >
              批准并自动创建首次复制任务
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
