"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import { useEffect, useState, type ReactNode } from "react";
import {
  BarChart3,
  BookOpen,
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  ClipboardList,
  FolderKanban,
  FlaskConical,
  Database,
  Boxes,
  LayoutDashboard,
  Lightbulb,
  LogOut,
  Menu,
  Moon,
  NotebookPen,
  LibraryBig,
  GitBranch,
  Search,
  ChevronDown,
  Wrench,
  Settings2,
  Inbox,
  Bot,
  Puzzle,
  Sun,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { LoadingState } from "@/components/ui/state";
import { getSession, logout, type SessionUser } from "@/lib/api";
import { cn } from "@/lib/utils";

const navigation = [
  { href: "/", label: "首页", icon: LayoutDashboard },
  { href: "/papers", label: "文献", icon: BookOpen },
  { href: "/inbox", label: "精读笔记", icon: Inbox },
  { href: "/projects", label: "研究课题", icon: FolderKanban },
  { href: "/ideas", label: "科研灵感", icon: Lightbulb },
  { href: "/ai-tasks", label: "AI 任务", icon: Bot },
  { href: "/settings", label: "设置", icon: Settings2 },
];
const tools = [
  { href: "/integrations/zotero", label: "Zotero 文献库", icon: LibraryBig },
  { href: "/experiments", label: "实验管理", icon: FlaskConical },
  { href: "/datasets", label: "数据集管理", icon: Database },
  { href: "/models", label: "模型管理", icon: Boxes },
  { href: "/integrations/repositories", label: "开源仓库", icon: GitBranch },
  { href: "/integrations/skills", label: "科研 Skills", icon: Puzzle },
  { href: "/tasks", label: "科研任务", icon: ClipboardList },
  { href: "/calendar", label: "日历", icon: CalendarDays },
  { href: "/journal", label: "科研日志", icon: NotebookPen },
  { href: "/analytics", label: "科研分析", icon: BarChart3 },
];
const routeLabels = [
  { href: "/settings/literature", label: "文献与 AI 权限" },
  { href: "/research-notes", label: "精读笔记" },
  { href: "/note-trash", label: "笔记回收站" },
  { href: "/literature-jobs", label: "文献处理任务" },
  { href: "/experiment-runs", label: "实验运行" },
  { href: "/search", label: "全局搜索" },
  ...navigation,
  ...tools,
].sort((left, right) => right.href.length - left.href.length);

export function AppShell({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const { theme, setTheme } = useTheme();
  const [user, setUser] = useState<SessionUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [toolsOpen, setToolsOpen] = useState(false);

  useEffect(() => {
    getSession()
      .then(setUser)
      .catch(() => router.replace("/login"))
      .finally(() => setLoading(false));
  }, [router]);

  if (loading) return <LoadingState label="正在检查登录状态…" />;
  if (!user) return null;

  return (
    <div className="research-app-shell min-h-screen">
      {sidebarOpen && (
        <button
          aria-label="关闭侧栏"
          className="fixed inset-0 z-30 bg-black/50 lg:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-40 flex flex-col border-r border-[var(--border)] bg-[var(--surface)] transition-all duration-200",
          collapsed ? "w-17" : "w-60",
          sidebarOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0",
        )}
      >
        <div className="flex h-16 items-center gap-3 border-b border-[var(--border)] px-4">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[var(--accent)] text-sm font-bold text-white">
            R
          </div>
          {!collapsed && (
            <div className="min-w-0">
              <div className="text-sm font-semibold tracking-tight">
                ResearchOS
              </div>
              <div className="text-[11px] text-[var(--muted)]">
                Personal Research Workspace
              </div>
            </div>
          )}
        </div>
        <nav
          className="min-h-0 flex-1 space-y-1 overflow-y-auto px-2 py-5"
          aria-label="主导航"
        >
          <div className="space-y-1">
            {navigation.map(({ href, label, icon: Icon }) => {
              const active =
                href === "/"
                  ? pathname === "/"
                  : href === "/inbox"
                    ? pathname.startsWith(href) ||
                      pathname.startsWith("/research-notes/") ||
                      pathname.startsWith("/note-trash")
                    : pathname.startsWith(href);
              return (
                <Link
                  key={href}
                  href={href}
                  title={collapsed ? label : undefined}
                  onClick={() => setSidebarOpen(false)}
                  className={cn(
                    "flex h-9 items-center gap-3 rounded-md px-3 text-sm transition-colors",
                    active
                      ? "bg-[var(--accent)]/12 font-medium text-[var(--accent)]"
                      : "text-[var(--muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--foreground)]",
                  )}
                >
                  <Icon className="h-4 w-4 shrink-0" />
                  {!collapsed && label}
                </Link>
              );
            })}
          </div>
          <Button
            variant="ghost"
            className="mt-4 w-full justify-start"
            aria-label="更多工具"
            aria-expanded={toolsOpen}
            aria-controls="more-tools"
            onClick={() => {
              setToolsOpen(!toolsOpen);
              if (collapsed) setCollapsed(false);
            }}
          >
            <Wrench className="h-4 w-4 shrink-0" />
            {!collapsed && (
              <>
                <span className="flex-1 text-left">更多工具</span>
                <ChevronDown
                  className={cn("h-3 w-3", toolsOpen && "rotate-180")}
                />
              </>
            )}
          </Button>
          {toolsOpen && (
            <div
              id="more-tools"
              className="space-y-1 border-t border-[var(--border)] pt-2"
            >
              {tools.map(({ href, label, icon: Icon }) => (
                <Link
                  key={href}
                  href={href}
                  title={collapsed ? label : undefined}
                  onClick={() => setSidebarOpen(false)}
                  className={cn(
                    "flex h-9 items-center gap-3 rounded-md px-3 text-sm",
                    pathname === href || pathname.startsWith(href + "/")
                      ? "bg-[var(--accent)]/12 text-[var(--accent)]"
                      : "text-[var(--muted)] hover:bg-[var(--surface-hover)]",
                  )}
                >
                  <Icon className="h-4 w-4" />
                  {!collapsed && label}
                </Link>
              ))}
            </div>
          )}
        </nav>
        <div className="space-y-1 border-t border-[var(--border)] p-2">
          <Button
            variant="ghost"
            className="w-full justify-start"
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            title="切换深浅色模式"
          >
            {theme === "dark" ? (
              <Sun className="h-4 w-4" />
            ) : (
              <Moon className="h-4 w-4" />
            )}
            {!collapsed && "切换主题"}
          </Button>
          <Button
            variant="ghost"
            className="w-full justify-start"
            onClick={async () => {
              await logout();
              router.replace("/login");
            }}
            title="退出登录"
          >
            <LogOut className="h-4 w-4" />
            {!collapsed && "退出登录"}
          </Button>
          <div
            className={cn(
              "flex items-center gap-2 px-3 py-2",
              collapsed && "justify-center px-0",
            )}
          >
            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-[var(--surface-hover)] text-xs font-semibold">
              {user.display_name.slice(0, 1)}
            </div>
            {!collapsed && (
              <div className="min-w-0">
                <div className="truncate text-xs font-medium">
                  {user.display_name}
                </div>
                <div className="truncate text-[10px] text-[var(--muted)]">
                  本地工作区
                </div>
              </div>
            )}
          </div>
        </div>
      </aside>
      <div
        className={cn(
          "transition-all duration-200",
          collapsed ? "lg:pl-17" : "lg:pl-60",
        )}
      >
        <header className="sticky top-0 z-20 flex h-16 items-center justify-between border-b border-[var(--border)] bg-[var(--surface)] px-5 lg:px-8">
          <div className="flex items-center gap-3">
            <Button
              variant="ghost"
              size="icon"
              className="lg:hidden"
              aria-label="打开导航"
              onClick={() => setSidebarOpen(true)}
            >
              <Menu className="h-5 w-5" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="hidden lg:inline-flex"
              aria-label={collapsed ? "展开导航" : "收起导航"}
              onClick={() => setCollapsed(!collapsed)}
            >
              {collapsed ? (
                <ChevronRight className="h-4 w-4" />
              ) : (
                <ChevronLeft className="h-4 w-4" />
              )}
            </Button>
            <span className="text-sm font-medium text-[var(--muted)]">
              {routeLabels.find(
                (item) =>
                  item.href === pathname ||
                  (item.href !== "/" && pathname.startsWith(`${item.href}/`)),
              )?.label ?? "ResearchOS"}
            </span>
          </div>
          <div className="flex items-center gap-3">
            <Link
              href="/search"
              aria-label="全局搜索"
              className="inline-flex h-9 items-center gap-2 rounded-md px-2 text-sm text-[var(--muted)] hover:bg-[var(--surface-hover)]"
            >
              <Search className="h-4 w-4" />
              <span className="hidden sm:inline">搜索</span>
            </Link>
            <div className="hidden text-xs text-[var(--muted)] md:block">
              {new Intl.DateTimeFormat("zh-CN", { dateStyle: "full" }).format(
                new Date(),
              )}
            </div>
          </div>
        </header>
        <main className="mx-auto max-w-[1500px] px-5 py-7 lg:px-8">
          {children}
        </main>
      </div>
    </div>
  );
}
