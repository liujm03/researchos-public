"use client";
import { useEffect, useState } from "react";
import { getSession } from "@/lib/api";
import type { TaskCreate, BriefCreate } from "./types";
export type ActionKind = "task" | "brief";
export type PendingAction = {
  kind: ActionKind;
  signature: string;
  body: TaskCreate | BriefCreate;
};
export function useActionRecovery(ideaId: string) {
  const [prefix, setPrefix] = useState<string | null>(null);
  const [pending, setPending] = useState<
    Partial<Record<ActionKind, PendingAction>>
  >({});
  const [ready, setReady] = useState(false);
  const [warning, setWarning] = useState("");
  useEffect(() => {
    let active = true;
    void getSession()
      .then((owner) => {
        if (!active) return;
        const storagePrefix = `researchos.idea.action:${owner.id}:${ideaId}:`;
        setPrefix(storagePrefix);
        const saved: Partial<Record<ActionKind, PendingAction>> = {};
        for (const kind of ["task", "brief"] as const) {
          try {
            const raw = sessionStorage.getItem(storagePrefix + kind);
            if (!raw) continue;
            const record: PendingAction = JSON.parse(raw);
            if (
              record.kind === kind &&
              typeof record.signature === "string" &&
              typeof record.body?.idempotency_key === "string" &&
              typeof record.body?.expected_revision_sha256 === "string"
            )
              saved[kind] = record;
            else sessionStorage.removeItem(storagePrefix + kind);
          } catch {
            setWarning("无法恢复上次动作记录，请先只读核查已有任务与草稿。");
          }
        }
        setPending(saved);
        setReady(true);
      })
      .catch(() => {
        if (active) setWarning("无法确认本人会话，暂不能创建灵感动作。");
      });
    return () => {
      active = false;
    };
  }, [ideaId]);
  function freeze(kind: ActionKind, body: TaskCreate | BriefCreate) {
    if (!ready || !prefix) throw new Error("本人会话尚未确认");
    const signature = JSON.stringify({ ...body, idempotency_key: null });
    const previous = pending[kind];
    if (previous && previous.signature !== signature)
      throw new Error("上次动作仍待核查；先核查或明确放弃，再提交不同输入。");
    const key = previous?.body.idempotency_key ?? crypto.randomUUID();
    const record: PendingAction = {
      kind,
      signature,
      body: { ...body, idempotency_key: key },
    };
    setPending((current) => ({ ...current, [kind]: record }));
    try {
      sessionStorage.setItem(prefix + kind, JSON.stringify(record));
    } catch {
      setWarning("浏览器无法保存本次动作恢复记录，请保持当前页面并核查结果。");
    }
    return record.body;
  }
  function clear(kind: ActionKind) {
    if (prefix)
      try {
        sessionStorage.removeItem(prefix + kind);
      } catch {
        /* retain no credentials */
      }
    setPending((current) => {
      const next = { ...current };
      delete next[kind];
      return next;
    });
  }
  return { pending, ready, warning, freeze, clear };
}
