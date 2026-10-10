"use client";
import Link from "next/link";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ErrorState, LoadingState } from "@/components/ui/state";
import {
  api,
  type AICapabilities,
  type AIUsage,
  type AutomationSettings,
  type ZoteroStatus,
} from "@/lib/api";

export default function LiteratureSettingsPage() {
  const [settings, setSettings] = useState<AutomationSettings | null>(null);
  const [capabilities, setCapabilities] = useState<AICapabilities | null>(null);
  const [usage, setUsage] = useState<AIUsage | null>(null);
  const [zotero, setZotero] = useState<ZoteroStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [usageLoading, setUsageLoading] = useState(false);
  const [usageError, setUsageError] = useState("");
  const [connectionError, setConnectionError] = useState("");
  const load = useCallback(() => {
    setLoading(true);
    setError("");
    Promise.all([
      api.get<AutomationSettings>("/settings/literature-automation"),
      api.get<AICapabilities>("/ai/capabilities"),
    ])
      .then(([rules, ai]) => {
        setSettings(rules);
        setCapabilities(ai);
      })
      .catch((cause) =>
        setError(cause instanceof Error ? cause.message : "无法加载文献设置"),
      )
      .finally(() => setLoading(false));
  }, []);
  useEffect(() => {
    queueMicrotask(load);
  }, [load]);
  async function loadUsage() {
    setUsageLoading(true);
    setUsageError("");
    try {
      setUsage(await api.get<AIUsage>("/ai/usage"));
    } catch (cause) {
      setUsageError(cause instanceof Error ? cause.message : "无法读取用量");
    } finally {
      setUsageLoading(false);
    }
  }
  async function checkZotero() {
    setConnectionError("");
    try {
      setZotero(
        await api.get<ZoteroStatus>("/reference-managers/zotero/status"),
      );
    } catch (cause) {
      setConnectionError(
        cause instanceof Error ? cause.message : "无法检查 Zotero 连接",
      );
    }
  }
  async function save(event: FormEvent) {
    event.preventDefault();
    if (!settings) return;
    setSaving(true);
    setError("");
    setMessage("");
    try {
      setSettings(
        await api.patch<AutomationSettings>("/settings/literature-automation", {
          cloud_scope: settings.cloud_scope,
          auto_sync_zotero: settings.auto_sync_zotero,
          auto_copy_pdf: settings.auto_copy_pdf,
          auto_analyze_paper: false,
          auto_sync_interval_minutes: settings.auto_sync_interval_minutes,
          max_papers_per_sync: settings.max_papers_per_sync,
          budget_mode: settings.budget_mode,
          daily_analysis_limit: settings.daily_analysis_limit,
          monthly_token_limit: settings.monthly_token_limit,
          max_input_tokens_per_job: settings.max_input_tokens_per_job,
          max_output_tokens_per_job: settings.max_output_tokens_per_job,
        }),
      );
      setMessage(
        "设置已保存。每篇论文仍需本人提交与批准；已入队任务请在任务页面取消。",
      );
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }
  return (
    <div className="space-y-5">
      <Link
        href="/settings"
        className="inline-flex items-center gap-2 text-xs text-[var(--muted)]"
      >
        <ArrowLeft className="h-4 w-4" />
        返回设置
      </Link>
      <div>
        <h1 className="text-2xl font-semibold">文献与 AI 权限</h1>
        <p className="mt-1 text-sm text-[var(--muted)]">
          论文由你选择并提交；批准后自动完成精读和笔记保存。
        </p>
      </div>
      {error && <ErrorState message={error} onRetry={load} />}
      {message && (
        <p role="status" className="text-sm text-[var(--accent)]">
          {message}
        </p>
      )}
      {loading ? (
        <LoadingState />
      ) : (
        settings && (
          <>
            <Card>
              <CardHeader>
                <h2 className="font-semibold">Codex 接入</h2>
              </CardHeader>
              <CardContent className="space-y-2 text-sm">
                <p>
                  {capabilities?.available
                    ? `可调用 ${capabilities.provider_key === "codex" ? "Codex 账号" : capabilities.provider_key} / ${capabilities.model_key}`
                    : capabilities?.configured
                      ? "AI 已配置，当前不可调用"
                      : "尚未配置可调用的 AI Provider"}
                </p>
                {capabilities?.reason_message && (
                  <p
                    role="alert"
                    className="text-amber-700 dark:text-amber-300"
                  >
                    {capabilities.reason_message}
                  </p>
                )}
                <p className="text-xs leading-5 text-[var(--muted)]">
                  全文精读会将你批准的原始 PDF
                  发送到云端。每篇的来源、技能、模板和保存目录仍在启动前确认。
                </p>
              </CardContent>
            </Card>
            <form onSubmit={save} className="space-y-4">
              <Card>
                <CardHeader>
                  <h2 className="font-semibold">精读权限</h2>
                </CardHeader>
                <CardContent className="space-y-4">
                  <label className="block space-y-2 text-sm">
                    <span>允许发送到云 AI 的最大资料范围</span>
                    <select
                      value={settings.cloud_scope}
                      onChange={(event) =>
                        setSettings({
                          ...settings,
                          cloud_scope: event.target
                            .value as AutomationSettings["cloud_scope"],
                        })
                      }
                      className="h-10 w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-3"
                    >
                      <option value="NONE">不允许外发论文资料</option>
                      <option value="METADATA_ONLY">仅文献元数据</option>
                      <option value="ABSTRACT_ONLY">元数据与摘要</option>
                      <option value="FULL_TEXT">论文全文与原始 PDF</option>
                    </select>
                  </label>
                  {settings.cloud_scope !== "FULL_TEXT" && (
                    <p className="text-sm text-amber-700 dark:text-amber-300">
                      原始 PDF 精读需要允许全文外发；此设置不会自动启动分析。
                    </p>
                  )}
                  <label className="block space-y-2 text-sm">
                    <span>分析额度模式</span>
                    <select
                      aria-label="分析额度模式"
                      value={settings.budget_mode}
                      onChange={(event) =>
                        setSettings({
                          ...settings,
                          budget_mode: event.target
                            .value as AutomationSettings["budget_mode"],
                        })
                      }
                      className="h-10 w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-3"
                    >
                      <option
                        value="PROVIDER_QUOTA"
                        disabled={capabilities?.provider_key !== "codex"}
                      >
                        跟随 Codex 账号额度
                      </option>
                      <option value="LOCAL_LIMITS">设置本地额度</option>
                    </select>
                  </label>
                  <p className="text-xs leading-5 text-[var(--muted)]">
                    {settings.budget_mode === "PROVIDER_QUOTA"
                      ? "不设置本平台 Token 停止上限；实际额度与限流由 Codex 账号决定。已报告 Token 不是剩余额度。"
                      : `本地限制：每天 ${settings.daily_analysis_limit} 篇，每月 ${settings.monthly_token_limit.toLocaleString()} Token。达到上限后任务等待预算。`}
                  </p>
                  {settings.budget_mode === "LOCAL_LIMITS" &&
                    (settings.daily_analysis_limit === 0 ||
                      settings.monthly_token_limit === 0) && (
                      <p
                        role="alert"
                        className="text-sm text-amber-700 dark:text-amber-300"
                      >
                        本地额度为 0，分析任务将等待预算。
                      </p>
                    )}
                  {settings.budget_mode === "LOCAL_LIMITS" && (
                    <details className="rounded-md border border-[var(--border)] p-3">
                      <summary className="cursor-pointer text-sm">
                        调整本地额度
                      </summary>
                      <div className="mt-3 grid gap-3 sm:grid-cols-2">
                        {(
                          [
                            {
                              key: "daily_analysis_limit",
                              label: "每日分析篇数上限",
                              min: 0,
                              max: 100,
                            },
                            {
                              key: "monthly_token_limit",
                              label: "每月 Token 上限",
                              min: 0,
                            },
                            {
                              key: "max_output_tokens_per_job",
                              label: "单次输出 Token 配额",
                              min: 100,
                            },
                          ] as const
                        ).map((field) => (
                          <label key={field.key} className="space-y-1 text-xs">
                            {field.label}
                            <Input
                              type="number"
                              min={field.min}
                              max={"max" in field ? field.max : undefined}
                              value={settings[field.key]}
                              onChange={(event) =>
                                setSettings({
                                  ...settings,
                                  [field.key]: Number(event.target.value),
                                })
                              }
                            />
                          </label>
                        ))}
                      </div>
                    </details>
                  )}
                  <p className="text-xs leading-5 text-[var(--muted)]">
                    论文页数不限。需要精读时，在原始 PDF
                    工作区主动提交；同步和解析不会自动调用
                    AI。结果不明的调用仍需核查后决定是否重试。
                  </p>
                </CardContent>
              </Card>
              {settings.auto_sync_last_error && (
                <p role="alert" className="text-sm text-[var(--danger)]">
                  Zotero 上次自动同步异常：{settings.auto_sync_last_error}
                </p>
              )}
              <details className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4">
                <summary className="cursor-pointer text-sm font-medium">
                  Zotero 自动同步设置 ·{" "}
                  {settings.auto_sync_zotero ? "已启用" : "已关闭"}
                </summary>
                <div className="mt-4 space-y-4 text-sm">
                  <div className="flex flex-wrap items-center gap-3">
                    <Link
                      href="/integrations/zotero"
                      className="text-[var(--accent)]"
                    >
                      打开 Zotero 文献库 →
                    </Link>
                    <Button
                      type="button"
                      variant="secondary"
                      onClick={checkZotero}
                    >
                      检查连接
                    </Button>
                  </div>
                  {connectionError && <ErrorState message={connectionError} />}
                  {zotero && (
                    <p>
                      {zotero.connected
                        ? "当前 Zotero 已连接"
                        : "当前 Zotero 不可用"}{" "}
                      · {zotero.library_type === "group" ? "群组" : "个人"}
                      文献库
                    </p>
                  )}
                  <label className="flex gap-2">
                    <input
                      type="checkbox"
                      checked={settings.auto_sync_zotero}
                      onChange={(event) =>
                        setSettings({
                          ...settings,
                          auto_sync_zotero: event.target.checked,
                        })
                      }
                    />
                    自动增量同步元数据
                  </label>
                  <label className="flex gap-2">
                    <input
                      type="checkbox"
                      checked={settings.auto_copy_pdf}
                      onChange={(event) =>
                        setSettings({
                          ...settings,
                          auto_copy_pdf: event.target.checked,
                        })
                      }
                    />
                    自动复制可访问 PDF 并解析
                  </label>
                  <p className="text-xs text-[var(--muted)]">
                    覆盖整个当前文献库，分批继续；复制只作用于自动同步新入队的论文，不会自动提交精读。
                  </p>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <label className="space-y-1 text-xs">
                      同步间隔（分钟）
                      <Input
                        type="number"
                        min="5"
                        max="1440"
                        value={settings.auto_sync_interval_minutes}
                        onChange={(event) =>
                          setSettings({
                            ...settings,
                            auto_sync_interval_minutes: Number(
                              event.target.value,
                            ),
                          })
                        }
                      />
                    </label>
                    <label className="space-y-1 text-xs">
                      每轮最多处理文献
                      <Input
                        type="number"
                        min="1"
                        max="1000"
                        value={settings.max_papers_per_sync}
                        onChange={(event) =>
                          setSettings({
                            ...settings,
                            max_papers_per_sync: Number(event.target.value),
                          })
                        }
                      />
                    </label>
                  </div>
                  <p className="text-xs text-[var(--muted)]">
                    上次检查：
                    {settings.auto_sync_last_run_at
                      ? new Date(settings.auto_sync_last_run_at).toLocaleString(
                          "zh-CN",
                        )
                      : "尚未运行"}{" "}
                    · 下次检查：
                    {settings.auto_sync_zotero
                      ? settings.auto_sync_next_run_at
                        ? new Date(
                            settings.auto_sync_next_run_at,
                          ).toLocaleString("zh-CN")
                        : "等待 worker"
                      : "已关闭"}
                  </p>
                </div>
              </details>
              <Button type="submit" disabled={saving}>
                {saving ? "保存中…" : "保存设置"}
              </Button>
            </form>
            <details className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4">
              <summary className="cursor-pointer text-sm font-medium">
                AI 用量记录
              </summary>
              <div className="mt-3 space-y-3">
                <Button
                  type="button"
                  variant="secondary"
                  onClick={loadUsage}
                  disabled={usageLoading}
                >
                  {usageLoading ? "读取中…" : "读取用量"}
                </Button>
                {usageError && <ErrorState message={usageError} />}
                {usage && (
                  <div className="grid gap-3 text-sm sm:grid-cols-3">
                    <p>
                      {usage.month} 已报告 Token：
                      {usage.used_tokens.toLocaleString()}
                    </p>
                    <p>预留 Token：{usage.reserved_tokens.toLocaleString()}</p>
                    <p>
                      费用：
                      {usage.estimated_cost === null
                        ? "未知"
                        : `${usage.estimated_cost.toFixed(4)} ${usage.cost_currency ?? ""}`}
                    </p>
                    <p>
                      预算计入 Token：
                      {usage.budget_accounted_tokens.toLocaleString()}
                    </p>
                    <p>费用未知任务：{usage.unknown_cost_jobs}</p>
                  </div>
                )}
              </div>
            </details>
          </>
        )
      )}
    </div>
  );
}
