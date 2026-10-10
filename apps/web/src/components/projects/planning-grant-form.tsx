"use client";

import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input, Textarea } from "@/components/ui/input";
import type { components } from "@/lib/generated";

type Capability = components["schemas"]["PlanningCapabilityOut"];
type Brief = components["schemas"]["ResearchBriefSummaryOut"];
type Create = components["schemas"]["PlanningGrantCreate"];
function tomorrow() {
  const value = new Date(Date.now() + 86400000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())}T${pad(value.getHours())}:${pad(value.getMinutes())}`;
}

export function PlanningGrantForm({
  capability,
  briefs,
  busy,
  onPreview,
  onInputsChanged,
}: {
  capability: Capability;
  briefs: Brief[];
  busy: boolean;
  onPreview: (body: Create) => Promise<void>;
  onInputsChanged: () => void;
}) {
  const [briefId, setBriefId] = useState("");
  const [profile, setProfile] = useState("");
  const [focus, setFocus] = useState("");
  const [maxJobs, setMaxJobs] = useState("1");
  const [timeout, setTimeout] = useState("900");
  const [expiry, setExpiry] = useState(tomorrow);
  const selected = briefs.find(
    (brief) =>
      brief.id === briefId &&
      brief.status === "ACCEPTED" &&
      brief.context_current,
  );
  async function preview(event: FormEvent) {
    event.preventDefault();
    if (!selected || !profile || !capability.enabled || busy) return;
    const date = new Date(expiry);
    if (Number.isNaN(date.getTime())) return;
    await onPreview({
      brief_id: selected.id,
      expected_brief_sha256: selected.sha256,
      profile,
      focus: focus.trim(),
      max_jobs: Number(maxJobs),
      timeout_seconds: Number(timeout),
      expires_at: date.toISOString(),
    });
  }
  return (
    <Card>
      <CardHeader>
        <h2 className="font-semibold">预览规划阶段授权</h2>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-xs leading-5 text-[var(--muted)]">
          选择已经本人接受且上下文当前的任务书。这里仅冻结规划输入和专业 Skill
          文件，预览不会启动 AI；批准后自动创建首个任务。
          任务书若包含精读笔记，预览会列出完整 Markdown
          外发范围；需要已配置全文外发权限。
        </p>
        <form onSubmit={preview} className="grid gap-4 sm:grid-cols-2">
          <label className="space-y-1.5 text-xs font-medium">
            已接受且当前的任务书
            <select
              aria-label="已接受且当前的任务书"
              required
              disabled={busy || !capability.enabled}
              value={briefId}
              onChange={(event) => {
                setBriefId(event.target.value);
                onInputsChanged();
              }}
              className="block h-9 w-full rounded border border-[var(--border)] bg-[var(--surface)] px-2 text-sm"
            >
              <option value="">请选择任务书版本</option>
              {briefs
                .filter(
                  (item) => item.status === "ACCEPTED" && item.context_current,
                )
                .map((item) => (
                  <option key={item.id} value={item.id}>
                    版本 {item.revision} · {item.idea.slice(0, 100)}
                  </option>
                ))}
            </select>
          </label>
          <label className="space-y-1.5 text-xs font-medium">
            专业规划 Skill
            <select
              aria-label="专业规划 Skill"
              required
              disabled={busy || !capability.enabled}
              value={profile}
              onChange={(event) => {
                setProfile(event.target.value);
                onInputsChanged();
              }}
              className="block h-9 w-full rounded border border-[var(--border)] bg-[var(--surface)] px-2 text-sm"
            >
              <option value="">请选择专业 Skill</option>
              {capability.profiles.map((item) => (
                <option key={item.key} value={item.key}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <label className="space-y-1.5 text-xs font-medium sm:col-span-2">
            本阶段关注点（可选）
            <Textarea
              aria-label="本阶段关注点（可选）"
              disabled={busy || !capability.enabled}
              maxLength={12000}
              value={focus}
              placeholder="留空沿用任务书 Idea；可说明希望重点评估的问题。"
              onChange={(event) => {
                setFocus(event.target.value);
                onInputsChanged();
              }}
            />
          </label>
          <details className="rounded border border-[var(--border)] sm:col-span-2">
            <summary className="cursor-pointer p-3 text-sm">
              高级范围设置 · 最多 {maxJobs} 次 / 单次 {Number(timeout) / 60}{" "}
              分钟
            </summary>
            <div className="grid gap-4 p-3 pt-0 sm:grid-cols-2">
              {" "}
              <label className="space-y-1.5 text-xs font-medium">
                本阶段最多任务数
                <Input
                  required
                  type="number"
                  min={1}
                  max={20}
                  step={1}
                  disabled={busy || !capability.enabled}
                  value={maxJobs}
                  onChange={(event) => {
                    setMaxJobs(event.target.value);
                    onInputsChanged();
                  }}
                />
              </label>
              <label className="space-y-1.5 text-xs font-medium">
                单次超时（秒）
                <Input
                  required
                  type="number"
                  min={60}
                  max={1800}
                  step={1}
                  disabled={busy || !capability.enabled}
                  value={timeout}
                  onChange={(event) => {
                    setTimeout(event.target.value);
                    onInputsChanged();
                  }}
                />
              </label>
              <label className="space-y-1.5 text-xs font-medium sm:col-span-2">
                授权有效期（本地时间）
                <Input
                  required
                  type="datetime-local"
                  disabled={busy || !capability.enabled}
                  value={expiry}
                  onChange={(event) => {
                    setExpiry(event.target.value);
                    onInputsChanged();
                  }}
                />
              </label>
              <p className="text-xs leading-5 text-[var(--muted)] sm:col-span-2">
                次数包含失败和取消任务。这是本人选择的阶段范围；推理由 Codex
                账号实际可用量决定，没有额外每日/月度 Token 停止阈值。已报告
                Token 不代表账号余额。
              </p>
            </div>
          </details>
          <p className="text-xs text-[var(--muted)] sm:col-span-2">
            当前范围有效至 {new Date(expiry).toLocaleString("zh-CN")}；推理跟随
            Codex 账号额度。
          </p>
          <Button
            type="submit"
            disabled={busy || !capability.enabled || !selected || !profile}
            className="sm:col-span-2"
          >
            预览授权及实际 Skill 来源
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
