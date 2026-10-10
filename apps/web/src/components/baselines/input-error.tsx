"use client";
import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/ui/state";

/** Retrying a readonly selector must never submit its surrounding version form. */
export function BaselineInputError({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <div className="space-y-2">
      <ErrorState message={message} />
      <Button type="button" variant="ghost" size="sm" onClick={onRetry}>
        重试
      </Button>
    </div>
  );
}
