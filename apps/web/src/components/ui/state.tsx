import { AlertCircle, Inbox, LoaderCircle } from "lucide-react";

export function LoadingState({ label = "正在加载…" }: { label?: string }) {
  return (
    <div className="flex min-h-48 items-center justify-center gap-3 text-sm text-[var(--muted)]" role="status">
      <LoaderCircle className="h-4 w-4 animate-spin" /> {label}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="flex min-h-32 flex-col items-center justify-center gap-2 rounded-lg border border-[var(--danger)]/30 bg-[var(--danger)]/5 px-4 text-sm">
      <AlertCircle className="h-5 w-5 text-[var(--danger)]" />
      <span>{message}</span>
      {onRetry && <button className="text-[var(--accent)] underline" onClick={onRetry}>重试</button>}
    </div>
  );
}

export function EmptyState({ title, detail }: { title: string; detail?: string }) {
  return (
    <div className="flex min-h-36 flex-col items-center justify-center gap-2 text-center text-sm text-[var(--muted)]">
      <Inbox className="h-5 w-5" />
      <span className="font-medium text-[var(--foreground)]">{title}</span>
      {detail && <span>{detail}</span>}
    </div>
  );
}
