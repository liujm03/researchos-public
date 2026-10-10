"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Clock3, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input, Textarea } from "@/components/ui/input";
import { ErrorState, LoadingState } from "@/components/ui/state";
import { api, type Journal } from "@/lib/api";

type JournalFields = Pick<Journal, "completed" | "papers_read" | "experiments" | "learning" | "problems" | "new_ideas" | "tomorrow_plan">;
const fields: { key: keyof JournalFields; label: string; placeholder: string }[] = [
  { key: "completed", label: "今天完成", placeholder: "完成的任务、代码或里程碑" },
  { key: "papers_read", label: "今天阅读", placeholder: "论文及关键收获" },
  { key: "experiments", label: "今天实验", placeholder: "运行、结果与异常" },
  { key: "learning", label: "今天学习", placeholder: "学习的概念与练习" },
  { key: "problems", label: "遇到问题", placeholder: "阻塞因素和待验证问题" },
  { key: "new_ideas", label: "新 Idea", placeholder: "灵感、假设或后续实验" },
  { key: "tomorrow_plan", label: "明天计划", placeholder: "最重要的下一步" },
];

const emptyFields: JournalFields = {
  completed: null, papers_read: null, experiments: null, learning: null,
  problems: null, new_ideas: null, tomorrow_plan: null,
};

function todayString() {
  return new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
}

export default function JournalPage() {
  const [day, setDay] = useState(todayString);
  const [journal, setJournal] = useState<Journal | null>(null);
  const [values, setValues] = useState<JournalFields>(emptyFields);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [category, setCategory] = useState("research");
  const [startTime, setStartTime] = useState("");
  const [endTime, setEndTime] = useState("");

  const load = useCallback(() => {
    api.get<Journal | null>(`/journals/${day}`)
      .then((result) => { setJournal(result); setValues(result ?? emptyFields); setError(""); })
      .catch((cause) => setError(cause instanceof Error ? cause.message : "无法加载日志"))
      .finally(() => setLoading(false));
  }, [day]);
  useEffect(load, [load]);

  async function save(event: FormEvent) {
    event.preventDefault(); setSaving(true); setError(""); setMessage("");
    try {
      const updated = await api.put<Journal>(`/journals/${day}`, values, journal?.version);
      setJournal(updated); setValues(updated); setMessage("日志已保存");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "保存失败"); }
    finally { setSaving(false); }
  }

  async function draft() {
    setSaving(true); setError("");
    try {
      const result = await api.post<JournalFields>(`/journals/${day}/draft`);
      setValues((current) => {
        const merged = { ...current };
        for (const field of fields) if (!merged[field.key]) merged[field.key] = result[field.key];
        return merged;
      });
      setMessage("已从任务与阅读记录填入草稿，请检查后保存。");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "生成草稿失败"); }
    finally { setSaving(false); }
  }

  async function addTime(event: FormEvent) {
    event.preventDefault(); setSaving(true); setError("");
    try {
      await api.post("/time-entries", {
        category,
        started_at: new Date(`${day}T${startTime}`).toISOString(),
        ended_at: new Date(`${day}T${endTime}`).toISOString(),
      });
      setStartTime(""); setEndTime(""); setMessage("科研时间已记录，Dashboard 统计将更新。");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "时间记录失败"); }
    finally { setSaving(false); }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3"><div><p className="mb-1 text-xs font-medium uppercase tracking-[0.18em] text-[var(--accent)]">Research journal</p><h1 className="text-2xl font-semibold">科研日志</h1><p className="mt-1 text-sm text-[var(--muted)]">记录今日证据、问题与明天的行动。</p></div><Input type="date" className="w-auto" value={day} onChange={(event) => setDay(event.target.value)} aria-label="日志日期" /></div>
      {error && <ErrorState message={error} onRetry={load} />}
      {message && <p role="status" className="rounded-md border border-[var(--accent)]/30 bg-[var(--accent)]/8 px-3 py-2 text-sm text-[var(--accent)]">{message}</p>}
      {loading ? <LoadingState /> : <div className="grid gap-4 xl:grid-cols-[1fr_320px]"><Card><CardHeader><div><h2 className="font-semibold">{day} · 每日记录</h2><p className="mt-1 text-xs text-[var(--muted)]">自动草稿只填空白处，不覆盖已写内容。</p></div><Button variant="secondary" size="sm" disabled={saving} onClick={draft}><Sparkles className="h-3.5 w-3.5" />从活动生成草稿</Button></CardHeader><CardContent><form onSubmit={save} className="space-y-5">{fields.map((field) => <label key={field.key} className="block space-y-2 text-sm font-medium">{field.label}<Textarea value={values[field.key] ?? ""} onChange={(event) => setValues((current) => ({ ...current, [field.key]: event.target.value }))} placeholder={field.placeholder} /></label>)}<Button type="submit" disabled={saving}>{saving ? "保存中…" : "保存日志"}</Button></form></CardContent></Card><Card className="h-fit"><CardHeader><div className="flex items-center gap-2"><Clock3 className="h-4 w-4 text-[var(--accent)]" /><h2 className="font-semibold">记录科研时间</h2></div></CardHeader><CardContent><form onSubmit={addTime} className="space-y-4"><label className="block space-y-1.5 text-xs font-medium">活动类别<select value={category} onChange={(event) => setCategory(event.target.value)} className="h-9 w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-3 text-sm">{["reading", "learning", "coding", "experiment", "writing", "research", "other"].map((item) => <option key={item} value={item}>{item}</option>)}</select></label><label className="block space-y-1.5 text-xs font-medium">开始时间<Input required type="time" value={startTime} onChange={(event) => setStartTime(event.target.value)} /></label><label className="block space-y-1.5 text-xs font-medium">结束时间<Input required type="time" value={endTime} onChange={(event) => setEndTime(event.target.value)} /></label><Button type="submit" className="w-full" disabled={saving}>添加时段</Button></form></CardContent></Card></div>}
    </div>
  );
}
