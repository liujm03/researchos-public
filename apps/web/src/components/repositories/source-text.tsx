import { MarkdownViewer } from "@/components/markdown/markdown-viewer";

export function RepositorySourceText({
  text,
  hash,
}: {
  text: string | null;
  hash: string | null;
}) {
  return (
    <section className="space-y-3">
      <div>
        <h3 className="text-sm font-semibold">
          README / Model Card / Data Card
        </h3>
        <p className="mt-1 text-xs leading-5 text-[var(--muted)]">
          以下为来源文本，内容和安装命令仅供核对。
        </p>
      </div>
      {text ? (
        <MarkdownViewer content={text} label="仓库来源原文" />
      ) : (
        <p className="text-xs text-[var(--muted)]">
          来源未提供可读取的说明文本。
        </p>
      )}
      {hash && (
        <p className="break-all text-[10px] text-[var(--muted)]">
          说明文本 SHA-256：<span className="font-mono">{hash}</span>
        </p>
      )}
    </section>
  );
}
