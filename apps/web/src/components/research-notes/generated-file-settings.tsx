"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { ErrorState, LoadingState } from "@/components/ui/state";
import { type GeneratedFileSettings } from "./trash-contract";

export function GeneratedFileSettingsPanel() {
  const [settings, setSettings] = useState<GeneratedFileSettings | null>(null);
  const [enabled, setEnabled] = useState(true);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const submitting = useRef(false);

  function apply(value: GeneratedFileSettings) {
    setSettings(value);
    setEnabled(value.enabled);
  }
  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      apply(await api.get<GeneratedFileSettings>("/settings/generated-files"));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "无法加载删除设置");
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    queueMicrotask(() => void load());
  }, [load]);
  async function save() {
    if (submitting.current || !settings) return;
    submitting.current = true;
    setSaving(true);
    setError("");
    setMessage("");
    const desired = { enabled, note_delete_scope: "READING_RUN" as const };
    try {
      try {
        apply(
          await api.patch<GeneratedFileSettings>(
            "/settings/generated-files",
            desired,
          ),
        );
        setMessage("删除设置已保存；不会自动删除任何笔记。");
      } catch (cause) {
        // A config assignment is read back after a lost response; never automatically resend.
        const observed = await api.get<GeneratedFileSettings>(
          "/settings/generated-files",
        );
        if (
          observed.enabled === desired.enabled &&
          observed.note_delete_scope === desired.note_delete_scope
        ) {
          apply(observed);
          setMessage("删除设置已核查保存。");
        } else throw cause;
      }
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "保存结果待核查，请刷新设置确认",
      );
    } finally {
      submitting.current = false;
      setSaving(false);
    }
  }
  return (
    <Card>
      <CardHeader>
        <h2 className="font-semibold">生成文件删除</h2>
        <Link href="/note-trash" className="text-sm text-[var(--accent)]">
          查看历史删除记录 →
        </Link>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm leading-6 text-[var(--muted)]">
          精读笔记确认后永久删除，包括本次精读的全部版本及系统管理的 Markdown
          文件和副本，不可恢复。原始 PDF 和 Zotero 文献保留。
          独立备份和手动副本不在删除范围内。当前支持精读笔记；其他生成文件不受此设置影响。
        </p>
        {error && <ErrorState message={error} onRetry={() => void load()} />}
        {loading ? (
          <LoadingState label="正在加载删除设置…" />
        ) : (
          settings && (
            <>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={enabled}
                  disabled={saving}
                  onChange={(event) => setEnabled(event.target.checked)}
                />
                允许永久删除精读笔记
              </label>
              <p className="text-sm">删除范围：本次精读的全部笔记版本。</p>
              <p className="text-xs text-[var(--muted)]">
                每次先展示实际范围，再由你确认。已被其他资料引用的笔记须先处理引用。
                设置不会自动删除现有笔记或清空历史记录。
              </p>
              {message && (
                <p role="status" className="text-sm text-[var(--accent)]">
                  {message}
                </p>
              )}
              <Button disabled={saving} onClick={() => void save()}>
                {saving ? "保存中…" : "保存删除设置"}
              </Button>
            </>
          )
        )}
      </CardContent>
    </Card>
  );
}
