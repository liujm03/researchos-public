"use client";

import { useState } from "react";
import { MarkdownContent } from "@/components/markdown/markdown-content";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import type { components } from "@/lib/generated";
type Grant = components["schemas"]["PlanningGrantOut"];

export function PlanningGrantDetail({
  grant,
  enabled,
  busy,
  onApprove,
  onRevoke,
}: {
  grant: Grant;
  enabled: boolean;
  busy: boolean;
  onApprove: () => Promise<void>;
  onRevoke: () => Promise<void>;
}) {
  const [allowCloud, setAllowCloud] = useState(false);
  const expired = grant.expired;
  return (
    <Card>
      <CardHeader>
        <h2 className="font-semibold">规划授权 · {grant.effective_state}</h2>
        <span className="text-xs text-[var(--muted)]">
          {expired ? "有效期已结束" : "PLANNING"}
        </span>
      </CardHeader>
      <CardContent className="space-y-4 text-xs">
        <p className="leading-5">
          {grant.scope === "BRIEF_DERIVED_NOTES"
            ? "资料范围包含已冻结任务书、所选文献元数据、完整精读 Markdown 派生笔记与固定专业 Skill 资料。笔记全文将随批准发送到云模型，需要全文外发权限；原 PDF 仅保留批准来源绑定，不发送。"
            : "资料范围仅为已冻结任务书、其所选文献元数据与固定专业 Skill 资料。"}
          没有代码、数据集、权重或主机文件访问；此授权不授予代码执行和训练。
        </p>
        <dl className="grid gap-3 sm:grid-cols-2">
          <div>
            <dt className="text-[var(--muted)]">技能及版本</dt>
            <dd>
              {grant.skill_key} · {grant.skill_version}
            </dd>
          </div>
          <div>
            <dt className="text-[var(--muted)]">模型 / 推理强度</dt>
            <dd>
              {grant.model_key} / {grant.reasoning_effort}
            </dd>
          </div>
          <div>
            <dt className="text-[var(--muted)]">有效期</dt>
            <dd>{new Date(grant.expires_at).toLocaleString("zh-CN")}</dd>
          </div>
          <div>
            <dt className="text-[var(--muted)]">任务次数 / 单次超时</dt>
            <dd>
              已用 {grant.used_jobs}/{grant.max_jobs} · 剩余{" "}
              {grant.jobs_remaining} · {grant.timeout_seconds} 秒
            </dd>
          </div>
          <div>
            <dt className="text-[var(--muted)]">资料 / 工具范围</dt>
            <dd>{grant.scope} · 工具禁用</dd>
          </div>
        </dl>
        <details className="rounded border border-[var(--border)]">
          <summary className="cursor-pointer p-3">授权身份与校验详情</summary>
          <dl className="grid gap-3 p-3 pt-0 sm:grid-cols-2">
            {" "}
            <div>
              <dt className="text-[var(--muted)]">授权 ID</dt>
              <dd className="break-all font-mono">{grant.id}</dd>
            </div>
            <div className="sm:col-span-2">
              <dt className="text-[var(--muted)]">授权 SHA-256</dt>
              <dd className="break-all font-mono">{grant.sha256}</dd>
            </div>
            <div className="sm:col-span-2">
              <dt className="text-[var(--muted)]">本人批准的授权 SHA-256</dt>
              <dd className="break-all font-mono">
                {grant.approved_sha256 || "尚未批准"}
              </dd>
            </div>
            <div className="sm:col-span-2">
              <dt className="text-[var(--muted)]">Brief SHA-256</dt>
              <dd className="break-all font-mono">{grant.brief_sha256}</dd>
            </div>
            <div className="sm:col-span-2">
              <dt className="text-[var(--muted)]">
                组装指令 / 来源清单 SHA-256
              </dt>
              <dd className="break-all font-mono">
                {grant.instructions_sha256}
                <br />
                {grant.source_manifest_sha256}
              </dd>
            </div>
          </dl>
        </details>
        <p className="whitespace-pre-wrap break-words rounded bg-[var(--surface)] p-3 leading-5">
          已冻结关注点：{grant.focus}
        </p>
        <details className="rounded border border-[var(--border)]">
          <summary className="cursor-pointer p-3">查看冻结输出合同</summary>
          <div className="space-y-2 border-t border-[var(--border)] p-3">
            <p>输出合同版本：{grant.output_contract_version}</p>
            <p className="break-all font-mono">
              附加合同 SHA-256：{grant.output_contract_sha256 || "旧版未记录"}
            </p>
            <p className="leading-5 text-[var(--muted)]">
              原专业 Skill Markdown
              保留；规范候选只能摘录其中原文或保持空值。不会为规范化另发模型调用，旧合同不被自动替换。
            </p>
            {grant.output_contract_payload && (
              <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words bg-[var(--surface)] p-2 font-mono">
                {JSON.stringify(grant.output_contract_payload, null, 2)}
              </pre>
            )}
          </div>
        </details>
        {!!grant.warnings.length && (
          <section aria-label="规划授权提示">
            <ul className="space-y-1 text-[var(--muted)]">
              {grant.warnings.map((item, index) => (
                <li key={`${item}:${index}`}>{item}</li>
              ))}
            </ul>
          </section>
        )}
        {!!grant.gaps.length && (
          <section aria-label="规划授权缺口">
            <ul className="space-y-1 text-[var(--danger)]">
              {grant.gaps.map((item, index) => (
                <li key={`${item}:${index}`}>{item}</li>
              ))}
            </ul>
          </section>
        )}
        {!grant.context_current && (
          <p className="text-[var(--danger)]">
            任务书或来源上下文已变化；不能继续批准或提交，请核对当前任务书后重新预览。
          </p>
        )}
        <details className="rounded border border-[var(--border)]">
          <summary className="cursor-pointer p-3">
            查看冻结任务书与资料外发内容
          </summary>
          <div className="space-y-3 border-t border-[var(--border)] p-3">
            <p className="whitespace-pre-wrap break-words">
              Idea：{grant.brief.idea}
            </p>
            {grant.brief.sections.map((section) => (
              <div key={section.key}>
                <p>
                  {section.key} · 来源 {section.origin_type}
                </p>
                <p className="whitespace-pre-wrap break-words text-[var(--muted)]">
                  {section.content || "未填写"}
                </p>
              </div>
            ))}
            {grant.brief.stop_rules && (
              <p className="whitespace-pre-wrap break-words">
                停止规则：{grant.brief.stop_rules}
              </p>
            )}
            <p>文献元数据仅为候选来源，不表示已精读或科学结论成立。</p>
            {grant.brief.evidence.map((source) => (
              <div key={source.id} className="space-y-1">
                <p>
                  {source.title} · {source.year ?? "年份未知"} · DOI{" "}
                  {source.doi || "未记录"}
                </p>
                <p className="break-all font-mono">
                  Paper {source.paper_id} v{source.paper_version} ·{" "}
                  {source.sha256}
                </p>
                <p className="whitespace-pre-wrap break-words text-[var(--muted)]">
                  {source.abstract || "未记录摘要"}
                </p>
              </div>
            ))}
            {grant.brief.canonical_note_sources?.map((source) => (
              <details
                key={source.canonical_note_id}
                className="rounded border border-[var(--border)]"
              >
                <summary className="cursor-pointer p-2">
                  精读笔记全文 · {source.paper_title} · AI 派生候选
                </summary>
                <div className="space-y-2 p-2">
                  <p className="break-all font-mono">
                    Canonical {source.canonical_note_id} · 原 MD SHA-256{" "}
                    {source.note_sha256}
                  </p>
                  <p>
                    范围：{source.source_scope} / {source.note_origin}。PDF
                    仅绑定，不发送；不代表科学验证。
                  </p>
                  <MarkdownContent content={source.markdown} />
                  <details>
                    <summary className="cursor-pointer py-1">
                      原 Markdown 与来源事实
                    </summary>
                    <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-all">
                      {source.markdown}
                    </pre>
                    <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-all">
                      {JSON.stringify(source.source_facts, null, 2)}
                    </pre>
                  </details>
                </div>
              </details>
            ))}
          </div>
        </details>
        <details className="rounded border border-[var(--border)]">
          <summary className="cursor-pointer p-3">
            查看实际 Skill 来源 · {grant.files.length} 个文件
          </summary>
          <div className="p-3 pt-0">
            {" "}
            <section aria-label="规划 Skill 冻结文件" className="space-y-2">
              <h3 className="font-semibold">
                实际 Skill 来源 · {grant.files.length} 个文件
              </h3>
              {grant.files.map((file) => (
                <details
                  key={`${file.role}:${file.path}`}
                  className="rounded border border-[var(--border)]"
                >
                  <summary className="cursor-pointer break-all p-3">
                    {file.path}
                  </summary>
                  <div className="space-y-2 border-t border-[var(--border)] p-3">
                    <p className="break-all font-mono">
                      原文件 SHA-256：{file.sha256} ·{" "}
                      {file.size_bytes.toLocaleString("zh-CN")} 字节
                    </p>
                    <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words font-mono leading-5">
                      {file.content}
                    </pre>
                  </div>
                </details>
              ))}
              <p className="text-[var(--muted)]">
                此工具禁用规划适配只使用已冻结文件，不宣称整个 Skill
                目录或通用脚本已获 READY。
              </p>
            </section>
          </div>
        </details>
        {grant.initial_job_id && (
          <p className="break-all font-mono">
            自动首次任务 ID：{grant.initial_job_id}
          </p>
        )}
        {enabled && grant.state === "DRAFT" && (
          <div className="space-y-3">
            <label className="flex items-start gap-2 leading-5">
              <input
                type="checkbox"
                disabled={busy || expired || !grant.context_current}
                checked={allowCloud}
                onChange={(event) => setAllowCloud(event.target.checked)}
              />
              <span>
                我批准上述冻结资料发送到 Codex
                云模型，并在此范围及限制内自动规划。
              </span>
            </label>
            <Button
              disabled={
                busy || expired || !grant.context_current || !allowCloud
              }
              onClick={() => void onApprove()}
            >
              批准并自动开始首次规划
            </Button>
          </div>
        )}
        {grant.state === "ACTIVE" && (
          <>
            <p className="text-[var(--muted)]">
              同一有效范围内后续任务沿用此授权；撤销或到期拒绝新动作并取消排队任务。已运行任务的停止需等待实际确认。
            </p>
            <Button
              variant="secondary"
              disabled={busy}
              onClick={() => void onRevoke()}
            >
              撤销此规划授权
            </Button>
          </>
        )}
      </CardContent>
    </Card>
  );
}
