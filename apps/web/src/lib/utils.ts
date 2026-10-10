import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatDate(value: string | null | undefined, locale = "zh-CN") {
  if (!value) return "—";
  return new Intl.DateTimeFormat(locale, { year: "numeric", month: "short", day: "numeric" }).format(
    new Date(value),
  );
}
