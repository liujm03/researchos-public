import { ExternalLink } from "lucide-react";
import {
  publicRepositoryHref,
  repositoryKindLabels,
  type RepositoryCandidate,
} from "@/lib/repositories";
import { RepositorySourceText } from "./source-text";

export function RepositoryMetadataView({
  candidate,
}: {
  candidate: RepositoryCandidate;
}) {
  const href = publicRepositoryHref(candidate.canonical_url);
  const rows = [
    [
      "来源",
      `${candidate.provider_key} · ${repositoryKindLabels[candidate.repo_kind] ?? candidate.repo_kind}`,
    ],
    ["仓库身份", candidate.repo_id],
    ["Provider ID", candidate.provider_id],
    ["许可证", candidate.license_id || "未提供，使用前需要核对"],
    ["默认分支", candidate.default_branch || "未记录"],
    ["Commit / 来源版本", candidate.commit_sha || "未提供"],
    ["Stars", candidate.stars == null ? "未记录" : String(candidate.stars)],
    [
      "Hub 下载统计",
      candidate.downloads == null
        ? "未记录"
        : `${candidate.downloads}（来源统计）`,
    ],
    ["获取时间", new Date(candidate.fetched_at).toLocaleString("zh-CN")],
    [
      "来源更新时间",
      candidate.updated_at
        ? new Date(candidate.updated_at).toLocaleString("zh-CN")
        : "未提供",
    ],
  ];
  return (
    <div className="space-y-5">
      <div>
        <h3 className="text-base font-semibold">{candidate.name}</h3>
        {candidate.description && (
          <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-[var(--muted)]">
            {candidate.description}
          </p>
        )}
        {href ? (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-2 inline-flex items-center gap-1 text-xs text-[var(--accent)] hover:underline"
          >
            <ExternalLink className="h-3 w-3" />
            查看公开仓库
          </a>
        ) : (
          <p className="mt-2 break-all text-xs text-[var(--muted)]">
            {candidate.canonical_url}
          </p>
        )}
      </div>
      <dl className="grid gap-3 text-xs sm:grid-cols-2">
        {rows.map(([label, value]) => (
          <div key={label}>
            <dt className="text-[var(--muted)]">{label}</dt>
            <dd className="mt-1 break-all leading-5">{value}</dd>
          </div>
        ))}
      </dl>
      {(candidate.topics ?? []).length > 0 && (
        <div className="flex flex-wrap gap-1.5" aria-label="来源标签">
          {[...new Set(candidate.topics ?? [])].map((topic) => (
            <span
              key={topic}
              className="rounded bg-[var(--surface-hover)] px-2 py-1 text-[11px]"
            >
              {topic}
            </span>
          ))}
        </div>
      )}
      {(candidate.task_hints ?? []).length > 0 && (
        <p className="text-xs leading-5 text-[var(--muted)]">
          来源任务提示：{candidate.task_hints.join(" / ")}
          ；科研任务字段由你确认。
        </p>
      )}
      <RepositorySourceText
        text={candidate.readme_text}
        hash={candidate.readme_sha256}
      />
    </div>
  );
}
