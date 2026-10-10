"use client";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import type { Build } from "./types";
export function BuildDetail({
  endpoint,
  build,
  busy,
  onSend,
  onRefresh,
}: {
  endpoint: string;
  build: Build;
  busy: boolean;
  onSend: (
    path: string,
    body: Record<string, unknown>,
    label: string,
  ) => Promise<void>;
  onRefresh: () => Promise<void>;
}) {
  const [ack, setAck] = useState(false);
  return (
    <section className="space-y-3" aria-label="文档构建详情">
      <div className="flex flex-wrap justify-between gap-2">
        <h3 className="font-medium">
          {build.selection.template_key} / {build.selection.variant} ·{" "}
          {build.status}
        </h3>
        <Button
          size="sm"
          variant="secondary"
          disabled={busy}
          onClick={() => void onRefresh()}
        >
          刷新构建状态
        </Button>
      </div>
      <p className="text-xs text-[var(--muted)]">
        READY
        仅证明技术构建与附件存储完成，不代表科学接受或投稿格式符合。没有实际 PDF
        附件就不显示下载。
      </p>
      {!build.context_current && (
        <p role="alert">
          稿件或图表来源已变化；此构建保留冻结历史，重试不会换成新材料。
        </p>
      )}
      <p className="break-all text-xs">
        完整源码 SHA：{build.source_sha256}
        <br />
        实际输入 ZIP SHA：{build.input_source_zip_sha256}
        <br />
        已保存构建回执 ZIP SHA：{build.source_zip_sha256 ?? "尚未保存"} ·{" "}
        {build.source_zip_size_bytes === null
          ? "字节数未知"
          : `${build.source_zip_size_bytes} 字节`}
        <br />
        编译输入 SHA：{build.compile_source_sha256}
        <br />
        编译器 manifest SHA：{build.compiler_manifest_sha256}
        <br />
        批准预览 SHA：{build.preview_sha256}
      </p>
      <ul className="list-disc pl-5 text-xs">
        {build.gaps.map((g, i) => (
          <li key={i}>{g}</li>
        ))}
      </ul>
      <div className="flex flex-wrap gap-3 text-sm">
        {(
          [
            [
              "source",
              build.source_attachment_id ?? build.input_source_attachment_id,
              "下载可编辑源码 ZIP",
            ],
            ["pdf", build.pdf_attachment_id, "下载实际 PDF"],
            ["log", build.log_attachment_id, "下载实际编译日志"],
          ] as const
        ).map(([kind, id, label]) =>
          id ? (
            <a
              key={kind}
              className="text-[var(--accent)] underline"
              href={`/api/v1${endpoint}/${build.id}/download?kind=${kind}`}
            >
              {label}
            </a>
          ) : (
            <span key={kind} className="text-xs text-[var(--muted)]">
              {kind}：尚无实际保存附件
            </span>
          ),
        )}
      </div>
      <details>
        <summary>冻结源文件清单 · {build.files.length} 项</summary>
        {build.files.map((f) => (
          <details key={f.path}>
            <summary className="break-all text-xs">
              {f.path} · {f.size_bytes} 字节 · {f.sha256}
            </summary>
            {f.text_content !== null && (
              <pre className="max-h-72 overflow-auto whitespace-pre-wrap text-xs">
                {f.text_content}
              </pre>
            )}
          </details>
        ))}
      </details>
      <details>
        <summary>真实构建尝试与隔离观察 · {build.attempts.length} 次</summary>
        {build.attempts.map((a) => (
          <div key={a.id} className="my-2 rounded border p-2 text-xs">
            <p>
              {a.status} · exit {a.exit_code ?? "未知"} ·{" "}
              {a.error_code ?? "无错误代码"}
            </p>
            <p className="break-all">镜像 {a.image_id ?? "未知"}</p>
            <p>
              {a.started_at} → {a.ended_at ?? "尚未结束"}
            </p>
            <p className="break-all">
              实际尝试源码 ZIP：{a.source_zip_sha256 ?? "尚无回执"} ·{" "}
              {a.source_zip_size_bytes ?? "未知"} 字节
            </p>
            <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-all">
              {JSON.stringify(a.observations, null, 2)}
            </pre>
            {a.result_payload && (
              <details>
                <summary>原编译产物回执</summary>
                <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-all">
                  {JSON.stringify(a.result_payload, null, 2)}
                </pre>
              </details>
            )}
          </div>
        ))}
      </details>
      {["SAVING", "QUEUED", "RUNNING"].includes(build.status) && (
        <Button
          variant="secondary"
          disabled={busy}
          onClick={() =>
            void onSend(`${endpoint}/${build.id}/cancel`, {}, "取消文档构建")
          }
        >
          取消本次文档构建
        </Button>
      )}
      {["SAVING", "FAILED", "NEEDS_ATTENTION", "CANCELLED"].includes(
        build.status,
      ) && (
        <div className="space-y-2 rounded border p-3">
          <p className="text-xs">
            重试只使用本次原冻结源码及固定受限编译器，不调用
            AI、不重选稿件或图表。
          </p>
          <label className="flex gap-2 text-xs">
            <input
              type="checkbox"
              checked={ack}
              disabled={busy}
              onChange={(e) => setAck(e.target.checked)}
            />
            我已核对当前失败、未知或取消结果，同意重试这份冻结源码
          </label>
          <Button
            disabled={busy || !ack}
            onClick={() =>
              void onSend(
                `${endpoint}/${build.id}/retry`,
                {
                  expected_source_sha256: build.source_sha256,
                  acknowledge_unknown: true,
                },
                "重试冻结文档构建",
              )
            }
          >
            重试原冻结源码
          </Button>
        </div>
      )}
    </section>
  );
}
