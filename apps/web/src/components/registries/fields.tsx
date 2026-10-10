import type { ComponentProps } from "react";
import { Input, Textarea } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

export function RegistryField({
  label,
  ...props
}: ComponentProps<typeof Input> & { label: string }) {
  return (
    <label className="block space-y-1.5 text-xs font-medium">
      {label}
      <Input aria-label={label} {...props} />
    </label>
  );
}
export function RegistryText({
  label,
  ...props
}: ComponentProps<typeof Textarea> & { label: string }) {
  return (
    <label className="block space-y-1.5 text-xs font-medium">
      {label}
      <Textarea aria-label={label} {...props} />
    </label>
  );
}
export function RemoveRowButton({
  onClick,
  label,
}: {
  onClick: () => void;
  label: string;
}) {
  return (
    <Button
      type="button"
      size="sm"
      variant="ghost"
      onClick={onClick}
      aria-label={label}
    >
      移除
    </Button>
  );
}
export function NumberCell({ value }: { value: number | null | undefined }) {
  return (
    <>
      {value === null || value === undefined
        ? "未记录"
        : value.toLocaleString()}
    </>
  );
}
