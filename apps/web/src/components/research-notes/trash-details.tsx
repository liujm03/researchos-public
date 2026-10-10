import {
  fileRetentionMessage,
  scopeLabel,
  type NoteTrashPreview,
  type NoteTrashEntry,
} from "./trash-contract";

export function NoteTrashDetails({
  value,
}: {
  value: NoteTrashPreview | NoteTrashEntry;
}) {
  return (
    <div className="space-y-3 text-sm">
      <p>
        {scopeLabel(value.scope)} · {value.members.length} 个版本
      </p>
      <p className="leading-6 text-[var(--muted)]">{fileRetentionMessage}</p>
      <ul className="flex flex-wrap gap-2" aria-label="受影响笔记版本">
        {value.members.map((member) => (
          <li
            key={member.note_id}
            className="rounded border border-[var(--border)] px-2 py-1"
          >
            v{member.revision} ·{" "}
            {member.created_by === "AI" ? "AI 原文" : "修订版"}
          </li>
        ))}
      </ul>
      {value.reference_counts.some((item) => item.count > 0) && (
        <p className="text-amber-800 dark:text-amber-300">
          旧版回收时保留了这些引用。永久删除前须处理实际关联，系统不会连带删除课题、Idea
          或稿件。
        </p>
      )}
      {"warnings" in value && value.warnings.length > 0 && (
        <ul className="list-disc space-y-1 pl-5 text-amber-800 dark:text-amber-300">
          {value.warnings.map((warning, index) => (
            <li key={index}>{warning}</li>
          ))}
        </ul>
      )}
      <details className="rounded border border-[var(--border)] p-3">
        <summary className="cursor-pointer text-xs">历史文件与关联记录</summary>
        <div className="mt-2 space-y-2 text-xs text-[var(--muted)]">
          {value.file_paths.length ? (
            value.file_paths.map((path) => (
              <p key={path} className="break-all font-mono">
                {path}
              </p>
            ))
          ) : (
            <p>此笔记未登记外部文件路径。</p>
          )}
          {value.reference_counts.map((item) => (
            <p key={item.kind}>
              {item.kind}：{item.count}
            </p>
          ))}
        </div>
      </details>
    </div>
  );
}
