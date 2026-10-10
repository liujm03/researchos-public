"use client";
import { useEffect, useRef, useState } from "react";
import { getSession } from "@/lib/api";

export type BuildPending = {
  path: string;
  method: "POST" | "PATCH";
  body: Record<string, unknown> & { idempotency_key: string };
  label: string;
};

/** Preserve the exact request across reloads; no action is automatically replayed. */
export function useBuildPending(projectId: string, publicationId: string) {
  const [pending, setPending] = useState<BuildPending | null>(null);
  const [ready, setReady] = useState(false);
  const [warning, setWarning] = useState("");
  const slot = useRef<string | null>(null);
  const frozen = useRef<BuildPending | null>(null);
  useEffect(() => {
    let active = true;
    void getSession()
      .then((owner) => {
        if (!active) return;
        slot.current = `researchos.builds.pending:${owner.id}:${projectId}:${publicationId}`;
        try {
          const raw = sessionStorage.getItem(slot.current);
          if (raw) {
            const value: BuildPending = JSON.parse(raw);
            if (
              ["POST", "PATCH"].includes(value.method) &&
              typeof value.label === "string" &&
              (value.path ===
                `/projects/${projectId}/publications/${publicationId}/builds` ||
                new RegExp(
                  `^/projects/${projectId}/publications/${publicationId}/builds/[0-9a-f-]{36}/(?:cancel|retry)$`,
                ).test(value.path)) &&
              value.method === "POST" &&
              typeof value.body?.idempotency_key === "string"
            ) {
              frozen.current = value;
              setPending(value);
            } else sessionStorage.removeItem(slot.current);
          }
        } catch {
          setWarning(
            "无法恢复上次保存记录，请先核查论文版本及审阅历史；未自动重发。",
          );
        }
        setReady(true);
      })
      .catch(() => {
        if (active) setWarning("本人会话尚未确认，暂不能保存科研论文。");
      });
    return () => {
      active = false;
    };
  }, [projectId, publicationId]);
  function freeze(
    path: string,
    body: Record<string, unknown>,
    label: string,
    method: "POST" | "PATCH" = "POST",
  ) {
    if (!ready || !slot.current) throw new Error("本人会话尚未确认");
    const prior = frozen.current;
    const signature = JSON.stringify({ ...body, idempotency_key: null });
    if (
      prior &&
      (prior.path !== path ||
        prior.method !== method ||
        JSON.stringify({ ...prior.body, idempotency_key: null }) !== signature)
    )
      throw new Error(
        "上次保存结果待核查，不能修改内容后重用旧请求。请先核查或继续原请求。",
      );
    const value: BuildPending = prior ?? {
      path,
      method,
      label,
      body: { ...body, idempotency_key: crypto.randomUUID() },
    };
    frozen.current = value;
    setPending(value);
    try {
      sessionStorage.setItem(slot.current, JSON.stringify(value));
    } catch {
      setWarning("浏览器不能保存刷新恢复信息，请保留本页并核查本次结果。");
    }
    return value;
  }
  function clear() {
    if (slot.current)
      try {
        sessionStorage.removeItem(slot.current);
      } catch {
        /* no credentials */
      }
    frozen.current = null;
    setPending(null);
  }
  return { pending, ready, warning, freeze, clear };
}
