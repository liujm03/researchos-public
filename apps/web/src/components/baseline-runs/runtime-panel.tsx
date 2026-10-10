"use client";
import { Button } from "@/components/ui/button";
import type { components } from "@/lib/generated";
export function BaselineRuntimePanel({
  runtime,
  loading,
  onRefresh,
}: {
  runtime: components["schemas"]["BaselineRuntimeOut"] | null;
  loading: boolean;
  onRefresh: () => void;
}) {
  return (
    <section
      className="space-y-3 rounded border border-[var(--border)] p-4"
      aria-label="实际基线运行环境"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold">实际运行环境</h2>
        <Button
          type="button"
          size="sm"
          variant="secondary"
          disabled={loading}
          onClick={onRefresh}
        >
          {loading ? "核对环境中…" : "重新核对实际环境"}
        </Button>
      </div>
      <p className="text-sm">
        {runtime
          ? runtime.available && runtime.enabled
            ? "记录的本机环境可用，当前策略仍禁止科研执行"
            : "本机运行已关闭；实验与仿真只在课题组服务器执行"
          : "环境状态尚未读取"}
      </p>
      {runtime?.issues.map((issue, index) => (
        <p
          key={`${issue}:${index}`}
          className="break-words text-xs text-amber-700 dark:text-amber-300"
        >
          {issue}
        </p>
      ))}
      {runtime && (
        <details className="text-xs">
          <summary className="cursor-pointer">
            查看实时环境身份与检查时间
          </summary>
          <div className="mt-2 space-y-1 break-all font-mono">
            <p>Docker endpoint：{runtime.docker_host}</p>
            <p>Daemon：{runtime.daemon_id ?? "未取得"}</p>
            <p>镜像：{runtime.image_id ?? "未取得"}</p>
            <p>
              查询时间：{new Date(runtime.checked_at).toLocaleString("zh-CN")}
            </p>
          </div>
        </details>
      )}
      <p className="text-xs text-[var(--muted)]">
        科学资格：NOT_GRANTED。环境存在或进程退出 0 均不代表论文已复现。
      </p>
    </section>
  );
}
