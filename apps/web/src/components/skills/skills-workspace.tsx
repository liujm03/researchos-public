"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { api } from "@/lib/api";
import {
  skillConnectionLabels,
  type SkillCapability,
  type SkillDiscovery,
  type SkillDiscoverRequest,
} from "@/lib/skills";
import { SkillCandidateCard } from "./skill-candidate";

export function SkillsWorkspace() {
  const [capability, setCapability] = useState<SkillCapability | null>(null);
  const [loading, setLoading] = useState(true);
  const [capabilityError, setCapabilityError] = useState("");
  const [workspace, setWorkspace] = useState("");
  const [discovering, setDiscovering] = useState(false);
  const [discoveryError, setDiscoveryError] = useState("");
  const [result, setResult] = useState<SkillDiscovery | null>(null);
  const [search, setSearch] = useState("");
  const generation = useRef(0);

  const loadCapability = useCallback(async () => {
    const request = ++generation.current;
    setLoading(true);
    setCapabilityError("");
    setResult(null);
    setDiscoveryError("");
    try {
      const value = await api.get<SkillCapability>("/system/skills/capability");
      if (request !== generation.current) return;
      setCapability(value);
      setWorkspace((current) =>
        value.workspace_ids.includes(current)
          ? current
          : value.workspace_ids[0] || "",
      );
    } catch (cause) {
      if (request === generation.current) {
        setCapability(null);
        setCapabilityError(
          cause instanceof Error ? cause.message : "无法读取 Skills 配置",
        );
      }
    } finally {
      if (request === generation.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    let active = true;
    const controller = generation;
    queueMicrotask(() => {
      if (active) void loadCapability();
    });
    return () => {
      active = false;
      controller.current++;
    };
  }, [loadCapability]);

  async function discover() {
    if (
      !capability?.enabled ||
      !capability.runtime_installed ||
      !capability.workspace_ids.includes(workspace) ||
      discovering
    )
      return;
    const request = ++generation.current;
    setDiscovering(true);
    setDiscoveryError("");
    setResult(null);
    try {
      const body: SkillDiscoverRequest = { workspace_id: workspace };
      const value = await api.post<SkillDiscovery>(
        "/system/skills/discover",
        body,
      );
      if (request === generation.current) setResult(value);
    } catch (cause) {
      if (request === generation.current)
        setDiscoveryError(
          cause instanceof Error ? cause.message : "Skills 发现失败",
        );
    } finally {
      if (request === generation.current) setDiscovering(false);
    }
  }

  const query = search.trim().toLocaleLowerCase();
  const visible =
    result?.skills.filter((skill) =>
      [
        skill.name,
        skill.description,
        skill.path,
        skill.scope,
        skill.plugin_id || "",
      ].some((value) => value.toLocaleLowerCase().includes(query)),
    ) || [];
  const connection = result?.connection_status ?? capability?.connection_status;
  const checkedAt =
    result?.connection_checked_at ?? capability?.connection_checked_at;
  const runtimeErrors = result?.runtime_errors || [];
  const canDiscover =
    capability?.enabled &&
    capability.runtime_installed &&
    capability.workspace_ids.includes(workspace) &&
    capability.connection_status !== "NOT_CONFIGURED";

  return (
    <div className="space-y-5">
      <header>
        <p className="text-xs uppercase tracking-[0.18em] text-[var(--accent)]">
          Existing research skills
        </p>
        <h1 className="mt-1 text-2xl font-semibold">科研 Skills</h1>
        <p className="mt-2 max-w-4xl text-sm leading-6 text-[var(--muted)]">
          查看 Codex
          在已登记科研工作区发现的技能、来源和文件指纹。发现结果用于后续审核与工作流绑定；精读与复现仍使用各自已批准的入口。
        </p>
      </header>
      <Card>
        <CardHeader>
          <h2 className="font-semibold">发现配置与连接</h2>
          <Button
            variant="ghost"
            size="sm"
            disabled={loading || discovering}
            onClick={() => void loadCapability()}
          >
            刷新配置
          </Button>
        </CardHeader>
        <CardContent className="space-y-4">
          {loading ? (
            <LoadingState label="正在读取 Skills 配置…" />
          ) : capabilityError ? (
            <ErrorState
              message={capabilityError}
              onRetry={() => void loadCapability()}
            />
          ) : (
            capability && (
              <>
                <dl className="grid gap-3 text-sm sm:grid-cols-2 xl:grid-cols-4">
                  <div>
                    <dt className="text-xs text-[var(--muted)]">功能开关</dt>
                    <dd className="mt-1">
                      {capability.enabled
                        ? "服务器已开启发现"
                        : "服务器未开启发现"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-[var(--muted)]">运行时安装</dt>
                    <dd className="mt-1">
                      {capability.runtime_installed
                        ? `已安装 SDK ${capability.sdk_version || "版本未知"}`
                        : "未检测到运行时"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-[var(--muted)]">
                      实际发现连接
                    </dt>
                    <dd className="mt-1">
                      {connection
                        ? skillConnectionLabels[connection]
                        : "尚未探测"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-[var(--muted)]">
                      审核可用绑定
                    </dt>
                    <dd className="mt-1">尚未建立 READY 绑定</dd>
                  </div>
                </dl>
                {checkedAt && (
                  <p className="text-xs text-[var(--muted)]">
                    连接检查时间：{new Date(checkedAt).toLocaleString("zh-CN")}
                  </p>
                )}
                {capability.reason && (
                  <p className="break-words text-sm text-[var(--muted)]">
                    {capability.reason}
                  </p>
                )}
                {!capability.enabled && (
                  <p className="text-sm text-[var(--muted)]">
                    发现功能默认关闭，由服务器配置开启。此页不收集账号凭据或修改技能开关。
                  </p>
                )}
                <div className="flex flex-wrap items-end gap-3">
                  <label className="min-w-56 flex-1 text-sm">
                    已登记的工作区
                    <select
                      aria-label="已登记的工作区"
                      value={workspace}
                      disabled={discovering || !capability.workspace_ids.length}
                      onChange={(event) => {
                        generation.current++;
                        setWorkspace(event.target.value);
                        setResult(null);
                        setDiscoveryError("");
                      }}
                      className="mt-1 block w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2"
                    >
                      {!capability.workspace_ids.length && (
                        <option value="">尚未登记工作区</option>
                      )}
                      {capability.workspace_ids.map((id) => (
                        <option key={id} value={id}>
                          {id}
                        </option>
                      ))}
                    </select>
                  </label>
                  <Button
                    disabled={!canDiscover || discovering}
                    onClick={() => void discover()}
                  >
                    {discovering ? "正在发现…" : "只读发现 Skills"}
                  </Button>
                </div>
                <p className="text-xs leading-5 text-[var(--muted)]">
                  仅查询工作区技能元数据，读取服务器允许目录中的主文件并计算哈希。不会创建模型对话、运行依赖命令或执行技能。已安装、已启用、已发现与审核可用分别记录。
                </p>
                {capability.limitations.length > 0 && (
                  <ul className="list-disc space-y-1 pl-5 text-xs text-[var(--muted)]">
                    {capability.limitations.map((item, index) => (
                      <li key={index} className="break-words">
                        {item}
                      </li>
                    ))}
                  </ul>
                )}
              </>
            )
          )}
        </CardContent>
      </Card>
      {discovering && <LoadingState label="正在查询 Codex 原生技能目录…" />}
      {discoveryError && <ErrorState message={discoveryError} />}
      {result && (
        <Card>
          <CardHeader>
            <h2 className="font-semibold">{result.workspace_id} · 发现结果</h2>
            <span className="text-xs text-[var(--muted)]">
              {result.skills.length} 个候选
            </span>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-xs leading-5 text-[var(--muted)]">
              {result.discovery_scope} ·{" "}
              {result.discovery_complete
                ? "当前声明范围查询完成"
                : "查询范围不完整"}{" "}
              · SDK {result.sdk_version} ·{" "}
              {new Date(result.checked_at).toLocaleString("zh-CN")}
            </p>
            <p className="text-sm text-[var(--muted)]">
              当前发现会话限制插件执行范围，未发现某插件技能不能用于判断它未安装。同名技能按实际来源与路径分别显示。
            </p>
            {result.limitations.length > 0 && (
              <ul className="list-disc space-y-1 pl-5 text-xs text-[var(--muted)]">
                {result.limitations.map((item, index) => (
                  <li key={index} className="break-words">
                    {item}
                  </li>
                ))}
              </ul>
            )}
            {runtimeErrors.length > 0 && (
              <details className="text-xs">
                <summary className="cursor-pointer text-[var(--danger)]">
                  {runtimeErrors.length} 项原生发现错误
                </summary>
                <ul className="mt-2 max-h-56 overflow-auto">
                  {runtimeErrors.map((item, index) => (
                    <li key={index} className="break-all py-1">
                      {item.error_code} · {item.path}
                    </li>
                  ))}
                </ul>
              </details>
            )}
            <label className="block text-sm">
              筛选技能
              <input
                type="search"
                aria-label="筛选技能"
                maxLength={200}
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="名称、作用域、插件或路径"
                className="mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2"
              />
            </label>
            {visible.length ? (
              <ul className="space-y-3">
                {visible.map((skill) => (
                  <SkillCandidateCard
                    key={skill.identity_sha256}
                    skill={skill}
                  />
                ))}
              </ul>
            ) : (
              <EmptyState
                title={
                  result.skills.length
                    ? "没有匹配的技能"
                    : "该工作区未发现技能候选"
                }
                detail={
                  result.skills.length
                    ? "调整筛选关键词。"
                    : "核对服务器配置与发现范围；此结果不会生成可用绑定。"
                }
              />
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
