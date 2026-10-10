"use client";

import Link from "next/link";
import { useEffect, useState, type FormEvent } from "react";
import { Download, RefreshCw, ShieldCheck } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ErrorState, LoadingState } from "@/components/ui/state";
import { LiteratureProviderCatalog } from "@/components/literature/provider-catalog";
import { GeneratedFileSettingsPanel } from "@/components/research-notes/generated-file-settings";
import {
  api,
  getSession,
  type ConfigurationReport,
  type SessionUser,
} from "@/lib/api";

const exportFormats = [
  { format: "json", label: "JSON 全量结构" },
  { format: "csv", label: "CSV 表格包" },
  { format: "markdown", label: "Markdown 阅读包" },
  { format: "bibtex", label: "BibTeX 文献" },
  { format: "ris", label: "RIS 文献" },
] as const;

const configurationLabels: Record<string, string> = {
  environment: "运行环境",
  database_url: "数据库地址",
  database_runtime: "数据库与迁移",
  authentication_secrets: "会话安全",
  initial_setup_token: "首次初始化",
  storage: "附件存储",
  zotero: "Zotero 文献",
  crossref: "Crossref DOI",
  paper_ai: "论文 AI",
  codex: "Codex 执行器",
};

export default function SettingsPage() {
  const [user, setUser] = useState<SessionUser | null>(null);
  const [displayName, setDisplayName] = useState("");
  const [timezone, setTimezone] = useState("Asia/Shanghai");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [configuration, setConfiguration] =
    useState<ConfigurationReport | null>(null);
  const [configurationLoading, setConfigurationLoading] = useState(false);
  const [diagnosticsOpen, setDiagnosticsOpen] = useState(false);
  const [providersOpen, setProvidersOpen] = useState(false);
  const [configurationError, setConfigurationError] = useState("");

  function loadConfiguration() {
    setConfigurationLoading(true);
    setConfigurationError("");
    api
      .get<ConfigurationReport>("/system/configuration")
      .then(setConfiguration)
      .catch((cause) =>
        setConfigurationError(
          cause instanceof Error ? cause.message : "无法检查系统配置",
        ),
      )
      .finally(() => setConfigurationLoading(false));
  }

  useEffect(() => {
    getSession()
      .then((result) => {
        setUser(result);
        setDisplayName(result.display_name);
        setTimezone(result.timezone);
      })
      .catch((cause) =>
        setError(cause instanceof Error ? cause.message : "无法加载设置"),
      )
      .finally(() => setLoading(false));
  }, []);

  async function save(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const result = await api.patch<SessionUser>("/me", {
        display_name: displayName,
        timezone,
      });
      setUser(result);
      setMessage("设置已保存。刷新后侧栏名称和日期统计会更新。");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <p className="mb-1 text-xs font-medium uppercase tracking-[0.18em] text-[var(--accent)]">
          Workspace settings
        </p>
        <h1 className="text-2xl font-semibold">设置</h1>
        <p className="mt-1 text-sm text-[var(--muted)]">
          管理连接、AI 权限和数据导出。
        </p>
      </div>
      {error && <ErrorState message={error} />}
      {loading ? (
        <LoadingState />
      ) : (
        user && (
          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <h2 className="font-semibold">个人资料</h2>
              </CardHeader>
              <CardContent>
                <form onSubmit={save} className="space-y-4">
                  <label className="block space-y-1.5 text-xs font-medium">
                    邮箱
                    <Input value={user.email} disabled />
                  </label>
                  <label className="block space-y-1.5 text-xs font-medium">
                    显示名称
                    <Input
                      required
                      value={displayName}
                      onChange={(event) => setDisplayName(event.target.value)}
                    />
                  </label>
                  <label className="block space-y-1.5 text-xs font-medium">
                    时区
                    <Input
                      required
                      value={timezone}
                      onChange={(event) => setTimezone(event.target.value)}
                      placeholder="Asia/Shanghai"
                    />
                  </label>
                  <p className="text-xs leading-5 text-[var(--muted)]">
                    时区决定每日科研、日历与热力图的日期边界，使用 IANA 名称。
                  </p>
                  {message && (
                    <p role="status" className="text-xs text-[var(--accent)]">
                      {message}
                    </p>
                  )}
                  <Button disabled={saving} type="submit">
                    {saving ? "保存中…" : "保存设置"}
                  </Button>
                </form>
              </CardContent>
            </Card>
            <Card className="h-fit">
              <CardHeader>
                <h2 className="font-semibold">数据与安全</h2>
                <ShieldCheck className="h-4 w-4 text-[var(--accent)]" />
              </CardHeader>
              <CardContent className="space-y-4">
                <p className="text-sm leading-6 text-[var(--muted)]">
                  JSON 与 CSV 包含当前 owner 的结构化数据；Markdown
                  适合阅读，BibTeX/RIS 仅包含文献元数据。导出可能包含私有笔记与
                  Codex
                  任务内容，请妥善保管。完整数据库和附件备份需在服务器侧执行。
                </p>
                <div className="flex flex-wrap gap-2">
                  {exportFormats.map((item) => (
                    <a
                      key={item.format}
                      href={`/api/v1/exports?format=${item.format}`}
                      download
                      className="inline-flex h-9 items-center gap-2 rounded-md border border-[var(--border)] bg-[var(--surface-hover)] px-3 text-sm hover:border-[var(--accent)]"
                    >
                      <Download className="h-4 w-4" />
                      {item.label}
                    </a>
                  ))}
                </div>
              </CardContent>
            </Card>
          </div>
        )
      )}
      <GeneratedFileSettingsPanel />
      <Card>
        <CardContent className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h2 className="font-semibold">文献自动化与 AI 权限</h2>
            <p className="mt-1 text-sm text-[var(--muted)]">
              设置 Zotero 同步、资料外发范围、分析额度和自动任务。
            </p>
          </div>
          <Link
            href="/settings/literature"
            className="inline-flex h-9 items-center rounded-md border border-[var(--border)] px-3 text-sm text-[var(--accent)] hover:bg-[var(--surface-hover)]"
          >
            打开设置 →
          </Link>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <h2 className="font-semibold">连接与工具</h2>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-3">
          {[
            { href: "/integrations/zotero", label: "Zotero 文献库" },
            {
              href: "/integrations/repositories",
              label: "GitHub / Hugging Face",
            },
            { href: "/integrations/skills", label: "科研 Skills" },
          ].map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className="rounded-md border border-[var(--border)] px-3 py-2 text-sm hover:text-[var(--accent)]"
            >
              {item.label} →
            </Link>
          ))}
        </CardContent>
      </Card>
      <details
        className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4"
        onToggle={(event) => setProvidersOpen(event.currentTarget.open)}
      >
        <summary className="cursor-pointer text-sm font-medium">
          文献来源与能力
        </summary>
        {providersOpen && (
          <div className="mt-4">
            <LiteratureProviderCatalog />
          </div>
        )}
      </details>
      <details
        className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4"
        onToggle={(event) => {
          const open = event.currentTarget.open;
          setDiagnosticsOpen(open);
          if (open && !configuration && !configurationLoading)
            loadConfiguration();
        }}
      >
        <summary className="cursor-pointer text-sm font-medium">
          运行配置诊断
        </summary>
        {diagnosticsOpen && (
          <Card className="mt-4">
            <CardHeader>
              <div className="flex items-center justify-between gap-3">
                <div>
                  <h2 className="font-semibold">运行状态</h2>
                  <p className="mt-1 text-xs text-[var(--muted)]">
                    只显示状态，不读取或展示密钥；连接状态来自当前 API 进程。
                  </p>
                </div>
                <Button
                  type="button"
                  disabled={configurationLoading}
                  onClick={loadConfiguration}
                >
                  <RefreshCw className="h-4 w-4" />
                  刷新
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              {configurationLoading ? (
                <LoadingState />
              ) : configurationError ? (
                <ErrorState message={configurationError} />
              ) : configuration ? (
                <div className="space-y-4">
                  <p role="status" className="text-sm">
                    {configuration.ready ? "核心配置就绪" : "核心配置需处理"} ·{" "}
                    {configuration.database_probed
                      ? "数据库与迁移已检查"
                      : "数据库尚未检查"}
                  </p>
                  <div className="grid gap-2 md:grid-cols-2">
                    {configuration.checks.map((check) => (
                      <div
                        key={check.key}
                        className="rounded-md border border-[var(--border)] p-3"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-sm font-medium">
                            {configurationLabels[check.key] ?? check.key}
                          </span>
                          <span
                            className={
                              check.status === "configured"
                                ? "text-xs text-emerald-600"
                                : check.status === "disabled"
                                  ? "text-xs text-[var(--muted)]"
                                  : check.status === "invalid"
                                    ? "text-xs text-red-600"
                                    : "text-xs text-amber-600"
                            }
                          >
                            {check.status === "configured"
                              ? "已配置"
                              : check.status === "disabled"
                                ? "未启用"
                                : check.status === "missing"
                                  ? "待配置"
                                  : "配置异常"}
                          </span>
                        </div>
                        <p className="mt-1 text-xs leading-5 text-[var(--muted)]">
                          {check.detail}
                        </p>
                      </div>
                    ))}
                  </div>
                  <p className="text-xs text-[var(--muted)]">
                    本机可运行 <code>python -m app.doctor --connect</code>{" "}
                    做独立检查。Codex 实际可用性还取决于执行主机的
                    SDK、登录和工作区。
                  </p>
                </div>
              ) : (
                <p className="text-sm text-[var(--muted)]">暂无诊断结果。</p>
              )}
            </CardContent>
          </Card>
        )}
      </details>
    </div>
  );
}
