"use client";
import { useEffect, useState } from "react";
import { getSession, api, ApiError } from "@/lib/api";
import type { Create, Idea } from "./types";
export type PendingCapture = { key: string; signature: string; body: Create };
export function useIdeaCapture(projectId: string) {
  const [storageKey, setStorageKey] = useState<string | null>(null);
  const [pending, setPending] = useState<PendingCapture | null>(null);
  const [restored, setRestored] = useState<PendingCapture | null>(null);
  const [ready, setReady] = useState(false);
  const [canAbandon, setCanAbandon] = useState(false);
  const [storageWarning, setStorageWarning] = useState("");
  useEffect(() => {
    let active = true;
    void getSession()
      .then((owner) => {
        if (!active) return;
        const key = `researchos.idea.capture:${owner.id}:${projectId || "global"}`;
        setStorageKey(key);
        try {
          const raw = sessionStorage.getItem(key);
          if (raw) {
            const saved: PendingCapture = JSON.parse(raw);
            if (
              typeof saved.key === "string" &&
              typeof saved.signature === "string" &&
              typeof saved.body?.title === "string" &&
              saved.body.idempotency_key === saved.key
            ) {
              setPending(saved);
              setRestored(saved);
            } else sessionStorage.removeItem(key);
          }
        } catch {
          setStorageWarning(
            "浏览器无法恢复上次捕获记录，未自动执行保存；请先核查列表。",
          );
        }
        setReady(true);
      })
      .catch(() => {
        if (active) setStorageWarning("无法确认本人会话，暂不能创建灵感。");
      });
    return () => {
      active = false;
    };
  }, [projectId]);
  function freeze(body: Create) {
    if (!ready || !storageKey) throw new Error("本人会话尚未确认");
    const signature = JSON.stringify({ ...body, idempotency_key: null });
    if (pending && pending.signature !== signature)
      throw new Error(
        "上次捕获结果待核查，不能改内容后换新请求。请先核查；未保存时可明确放弃原捕获，再保存新内容。",
      );
    const key = pending?.key ?? crypto.randomUUID();
    const next: PendingCapture = {
      key,
      signature,
      body: { ...body, idempotency_key: key },
    };
    setPending(next);
    setCanAbandon(false);
    try {
      sessionStorage.setItem(storageKey, JSON.stringify(next));
    } catch {
      setStorageWarning(
        "本次捕获仍可在当前页面核查，但浏览器不能保存刷新恢复信息，请不要关闭页面。",
      );
    }
    return next.body;
  }
  function clear() {
    if (storageKey)
      try {
        sessionStorage.removeItem(storageKey);
      } catch {
        /* no credentials are stored */
      }
    setPending(null);
    setRestored(null);
    setCanAbandon(false);
  }
  async function lookup(): Promise<Idea | null> {
    if (!pending) return null;
    try {
      const result = await api.get<Idea>(
        `/ideas/lookup?key=${encodeURIComponent(pending.key)}`,
      );
      clear();
      return result;
    } catch (cause) {
      if (
        cause instanceof ApiError &&
        cause.status === 404 &&
        cause.code === "NOT_FOUND"
      ) {
        setCanAbandon(true);
        return null;
      }
      throw cause;
    }
  }
  return {
    pending,
    restored,
    ready,
    canAbandon,
    storageWarning,
    freeze,
    clear,
    lookup,
  };
}
