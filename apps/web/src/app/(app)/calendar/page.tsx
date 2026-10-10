"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { ErrorState, LoadingState } from "@/components/ui/state";
import { api } from "@/lib/api";

type CalendarEvent = { id: string; type: string; title: string; at: string; local_date: string; status: string };

function isoDay(day: Date) {
  return `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, "0")}-${String(day.getDate()).padStart(2, "0")}`;
}

export default function CalendarPage() {
  const [month, setMonth] = useState(() => new Date(new Date().getFullYear(), new Date().getMonth(), 1));
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const first = useMemo(() => new Date(month.getFullYear(), month.getMonth(), 1), [month]);
  const last = useMemo(() => new Date(month.getFullYear(), month.getMonth() + 1, 0), [month]);

  const load = useCallback(() => {
    api.get<CalendarEvent[]>(`/calendar?start=${isoDay(first)}&end=${isoDay(last)}`)
      .then((result) => { setEvents(result); setError(""); })
      .catch((cause) => setError(cause instanceof Error ? cause.message : "无法加载日历"))
      .finally(() => setLoading(false));
  }, [first, last]);
  useEffect(load, [load]);

  const blank = (first.getDay() + 6) % 7;
  const cells = Array.from({ length: blank + last.getDate() }, (_, index) => index < blank ? null : new Date(month.getFullYear(), month.getMonth(), index - blank + 1));

  return (
    <div className="space-y-6">
      <div><p className="mb-1 text-xs font-medium uppercase tracking-[0.18em] text-[var(--accent)]">Calendar</p><h1 className="text-2xl font-semibold">科研日历</h1><p className="mt-1 text-sm text-[var(--muted)]">按截止日期查看科研任务。</p></div>
      <Card><CardHeader><div className="flex items-center gap-2"><Button variant="ghost" size="icon" aria-label="上个月" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() - 1, 1))}><ChevronLeft className="h-4 w-4" /></Button><h2 className="min-w-32 text-center font-semibold">{month.getFullYear()} 年 {month.getMonth() + 1} 月</h2><Button variant="ghost" size="icon" aria-label="下个月" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() + 1, 1))}><ChevronRight className="h-4 w-4" /></Button></div><Link href="/tasks" className="text-xs text-[var(--accent)] hover:underline">管理任务</Link></CardHeader><CardContent>{error && <ErrorState message={error} onRetry={load} />}{loading ? <LoadingState /> : <div className="grid grid-cols-7 gap-px overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--border)]">{["周一", "周二", "周三", "周四", "周五", "周六", "周日"].map((label) => <div key={label} className="bg-[var(--surface-hover)] px-2 py-2 text-center text-xs text-[var(--muted)]">{label}</div>)}{cells.map((day, index) => <div key={index} className="min-h-24 bg-[var(--surface)] p-2 sm:min-h-32"><div className="text-xs text-[var(--muted)]">{day?.getDate()}</div>{day && events.filter((event) => event.local_date === isoDay(day)).slice(0, 3).map((event) => <Link key={event.id} href="/tasks" className="mt-1 block truncate rounded bg-[var(--accent)]/12 px-1.5 py-1 text-[10px] text-[var(--accent)]" title={event.title}>{event.title}</Link>)}</div>)}</div>}</CardContent></Card>
    </div>
  );
}
