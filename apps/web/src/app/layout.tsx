import type { Metadata } from "next";
import type { ReactNode } from "react";
import { ThemeProvider } from "@/components/theme-provider";
import "./globals.css";

export const metadata: Metadata = {
  title: "ResearchOS",
  description: "Personal Research Operating System",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body><ThemeProvider>{children}</ThemeProvider></body>
    </html>
  );
}
