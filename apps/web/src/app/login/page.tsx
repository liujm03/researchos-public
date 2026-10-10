"use client";

import { useEffect, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { BookOpenText, LockKeyhole } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api, getSession, login, setup } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [needsSetup, setNeedsSetup] = useState<boolean | null>(null);
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [setupToken, setSetupToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    getSession().then(() => router.replace("/")).catch(() => undefined);
    api.get<{ needs_setup: boolean }>("/auth/setup-state")
      .then((state) => setNeedsSetup(state.needs_setup))
      .catch(() => setError("无法连接 API。请确认服务和数据库已经启动。"));
  }, [router]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (needsSetup) await setup(setupToken, email, displayName, password);
      await login(email, password);
      router.replace("/");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "登录失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-5 py-12">
      <div className="w-full max-w-md">
        <div className="mb-8 text-center">
          <div className="mx-auto mb-5 flex h-12 w-12 items-center justify-center rounded-xl bg-[var(--accent)] text-white"><BookOpenText className="h-6 w-6" /></div>
          <h1 className="text-2xl font-semibold tracking-tight">ResearchOS</h1>
          <p className="mt-2 text-sm text-[var(--muted)]">你的个人科研工作区</p>
        </div>
        <Card>
          <CardContent className="p-7">
            <div className="mb-6 flex items-center gap-2"><LockKeyhole className="h-4 w-4 text-[var(--accent)]" /><h2 className="font-semibold">{needsSetup ? "初始化本地用户" : "登录"}</h2></div>
            {needsSetup === null && !error ? <p className="text-sm text-[var(--muted)]">正在检查工作区…</p> : (
              <form onSubmit={submit} className="space-y-4">
                {needsSetup && <label className="block space-y-1.5 text-xs font-medium">显示名称<Input required value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="例如：研究者" /></label>}
                <label className="block space-y-1.5 text-xs font-medium">邮箱<Input required type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@example.com" /></label>
                <label className="block space-y-1.5 text-xs font-medium">密码<Input required type="password" minLength={needsSetup ? 12 : undefined} value={password} onChange={(event) => setPassword(event.target.value)} placeholder={needsSetup ? "至少 12 位" : "输入密码"} /></label>
                {needsSetup && <label className="block space-y-1.5 text-xs font-medium">一次性初始化令牌<Input required type="password" value={setupToken} onChange={(event) => setSetupToken(event.target.value)} placeholder="见服务器环境变量 INITIAL_SETUP_TOKEN" /></label>}
                {error && <p role="alert" className="rounded-md bg-[var(--danger)]/10 px-3 py-2 text-xs text-[var(--danger)]">{error}</p>}
                <Button type="submit" className="w-full" disabled={busy || needsSetup === null}>{busy ? "请稍候…" : needsSetup ? "创建工作区" : "登录"}</Button>
              </form>
            )}
          </CardContent>
        </Card>
        <p className="mt-5 text-center text-xs text-[var(--muted)]">科研数据保存在你控制的数据库中</p>
      </div>
    </div>
  );
}
