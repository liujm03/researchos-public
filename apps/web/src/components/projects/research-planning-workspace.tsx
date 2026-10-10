"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Textarea } from "@/components/ui/input";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { api, type Project } from "@/lib/api";
import { PlanningGrantForm } from "./planning-grant-form";
import { PlanningGrantDetail } from "./planning-grant-detail";
import { PlanningJobCard } from "./planning-job-card";
import type { components } from "@/lib/generated";

type Capability = components["schemas"]["PlanningCapabilityOut"];
type BriefPage = components["schemas"]["ResearchBriefPage"];
type Brief = components["schemas"]["ResearchBriefSummaryOut"];
type Grant = components["schemas"]["PlanningGrantOut"];
type GrantPage = components["schemas"]["PlanningGrantPage"];
type Job = components["schemas"]["PlanningJobOut"];
type Create = components["schemas"]["PlanningGrantCreate"];
const errorMessage = (value: unknown, fallback: string) =>
  value instanceof Error ? value.message : fallback;

export function ResearchPlanningWorkspace({
  projectId,
}: {
  projectId: string;
}) {
  const endpoint = `/projects/${encodeURIComponent(projectId)}`;
  const [project, setProject] = useState<Project | null>(null);
  const [capability, setCapability] = useState<Capability | null>(null);
  const [briefs, setBriefs] = useState<Brief[]>([]);
  const [briefCursor, setBriefCursor] = useState<string | null>(null);
  const [grants, setGrants] = useState<Grant[] | null>(null);
  const [grantCursor, setGrantCursor] = useState<string | null>(null);
  const [selected, setSelected] = useState<Grant | null>(null);
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [focus, setFocus] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [listError, setListError] = useState("");
  const [scopeError, setScopeError] = useState("");
  const [notice, setNotice] = useState("");
  const selectedRef = useRef<string | null>(null);
  const busyRef = useRef(false);
  const polling = useRef(false);
  const loadSequence = useRef(0);
  const scopeSequence = useRef(0);
  const nonce = useRef<{
    grant: string;
    focus: string | null;
    key: string;
  } | null>(null);

  const loadLists = useCallback(async () => {
    const sequence = ++loadSequence.current;
    setListError("");
    const results = await Promise.allSettled([
      api.get<Capability>("/research-planning/capability"),
      api.get<BriefPage>(`${endpoint}/research-briefs?limit=100`),
      api.get<GrantPage>(`${endpoint}/planning-grants?limit=20`),
    ]);
    if (sequence !== loadSequence.current) return;
    const [capResult, briefResult, grantResult] = results;
    if (capResult.status === "fulfilled") setCapability(capResult.value);
    if (briefResult.status === "fulfilled") {
      setBriefs(briefResult.value.items);
      setBriefCursor(briefResult.value.page.next_cursor);
    }
    if (grantResult.status === "fulfilled") {
      setGrants(grantResult.value.items);
      setGrantCursor(grantResult.value.page.next_cursor);
    }
    const failures = results.filter(
      (item): item is PromiseRejectedResult => item.status === "rejected",
    );
    if (failures.length)
      setListError(
        failures
          .map((item) => errorMessage(item.reason, "规划资料暂不可读"))
          .join("；"),
      );
  }, [endpoint]);
  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setProject(await api.get<Project>(endpoint));
      await loadLists();
    } catch (cause) {
      setError(errorMessage(cause, "科研规划页面读取失败"));
    } finally {
      setLoading(false);
    }
  }, [endpoint, loadLists]);
  const readScope = useCallback(
    async (id: string) => {
      const sequence = ++scopeSequence.current;
      selectedRef.current = id;
      setScopeError("");
      try {
        const [grant, list] = await Promise.all([
          api.get<Grant>(`${endpoint}/planning-grants/${id}`),
          api.get<Job[]>(`${endpoint}/planning-grants/${id}/jobs`),
        ]);
        if (sequence !== scopeSequence.current) return;
        setSelected(grant);
        setJobs(list);
        setGrants(
          (old) =>
            old?.map((item) => (item.id === grant.id ? grant : item)) ?? [
              grant,
            ],
        );
      } catch (cause) {
        if (sequence === scopeSequence.current)
          setScopeError(errorMessage(cause, "授权或任务记录暂不可读"));
      }
    },
    [endpoint],
  );
  useEffect(() => {
    let active = true;
    void Promise.resolve().then(() => {
      if (!active) return;
      void (async () => {
        await load();
        if (!active) return;
        const sourceJobId = new URLSearchParams(window.location.search).get(
          "job",
        );
        if (!sourceJobId) return;
        try {
          const sourceJob = await api.get<Job>(
            `${endpoint}/planning-jobs/${encodeURIComponent(sourceJobId)}`,
          );
          if (active) await readScope(sourceJob.grant_id);
        } catch (cause) {
          if (active)
            setScopeError(errorMessage(cause, "来源规划任务不可读取"));
        }
      })();
    });
    return () => {
      active = false;
      loadSequence.current += 1;
      scopeSequence.current += 1;
    };
  }, [load, readScope, endpoint]);
  const activeScope =
    selected?.effective_state === "ACTIVE" ||
    !!jobs?.some((job) =>
      ["QUEUED", "RUNNING", "CANCEL_REQUESTED"].includes(job.status),
    );
  useEffect(() => {
    if (!activeScope) return;
    let active = true;
    const poll = async () => {
      if (
        !active ||
        document.hidden ||
        busyRef.current ||
        polling.current ||
        !selectedRef.current
      )
        return;
      polling.current = true;
      try {
        await readScope(selectedRef.current);
      } finally {
        polling.current = false;
      }
    };
    const interval = window.setInterval(() => void poll(), 4000);
    const visible = () => {
      if (!document.hidden) void poll();
    };
    document.addEventListener("visibilitychange", visible);
    return () => {
      active = false;
      window.clearInterval(interval);
      document.removeEventListener("visibilitychange", visible);
    };
  }, [activeScope, readScope]);
  function beginAction() {
    if (busyRef.current) return false;
    busyRef.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    scopeSequence.current += 1;
    return true;
  }
  function endAction() {
    busyRef.current = false;
    setBusy(false);
  }
  async function preview(body: Create) {
    if (!capability?.enabled || !beginAction()) return;
    try {
      const grant = await api.post<Grant>(`${endpoint}/planning-grants`, body);
      selectedRef.current = grant.id;
      setSelected(grant);
      setJobs([]);
      setGrants((old) => [
        grant,
        ...(old ?? []).filter((item) => item.id !== grant.id),
      ]);
      setNotice("规划授权草稿已冻结；未调用模型。请核对资料与范围后批准。");
    } catch (cause) {
      setError(
        errorMessage(cause, "授权预览失败") +
          "。输入保留，请核对当前任务书和来源。",
      );
    } finally {
      endAction();
    }
  }
  async function approve() {
    if (!selected || !capability?.enabled || !beginAction()) return;
    try {
      const grant = await api.post<Grant>(
        `${endpoint}/planning-grants/${selected.id}/approve`,
        {
          expected_sha256: selected.sha256,
          allow_cloud_transfer: true,
        } satisfies components["schemas"]["PlanningGrantApprove"],
      );
      setSelected(grant);
      setGrants(
        (old) =>
          old?.map((item) => (item.id === grant.id ? grant : item)) ?? [grant],
      );
      await readScope(grant.id);
      setNotice("已批准本规划范围并自动创建首个任务；无需第二次启动确认。");
    } catch (cause) {
      setError(
        errorMessage(cause, "授权批准失败") +
          "。草稿和输入保留，未推断任务已启动。",
      );
    } finally {
      endAction();
    }
  }
  async function revoke() {
    if (!selected || !beginAction()) return;
    try {
      const grant = await api.post<Grant>(
        `${endpoint}/planning-grants/${selected.id}/revoke`,
        {},
      );
      setSelected(grant);
      await readScope(grant.id);
      setNotice("授权已撤销；排队任务取消，运行中的停止等待实际确认。");
    } catch (cause) {
      setError(errorMessage(cause, "授权撤销失败"));
    } finally {
      endAction();
    }
  }
  async function createJob() {
    if (!selected?.can_submit || !capability?.enabled || !beginAction()) return;
    const value = focus.trim() || null;
    if (nonce.current?.grant !== selected.id || nonce.current?.focus !== value)
      nonce.current = {
        grant: selected.id,
        focus: value,
        key: crypto.randomUUID(),
      };
    try {
      await api.post<Job>(`${endpoint}/planning-grants/${selected.id}/jobs`, {
        focus: value,
        idempotency_key: nonce.current.key,
      } satisfies components["schemas"]["PlanningJobCreate"]);
      nonce.current = null;
      setFocus("");
      await readScope(selected.id);
      setNotice("已在同一授权范围提交规划任务；没有重新扩大授权。");
    } catch (cause) {
      setError(
        errorMessage(cause, "规划任务提交失败") +
          "。再次提交相同关注点会复用本次请求编号。",
      );
    } finally {
      endAction();
    }
  }
  async function cancel(job: Job) {
    if (!beginAction()) return;
    try {
      const updated = await api.post<Job>(
        `${endpoint}/planning-jobs/${job.id}/cancel`,
        {},
      );
      setJobs(
        (old) =>
          old?.map((item) => (item.id === updated.id ? updated : item)) ?? [
            updated,
          ],
      );
      setNotice(
        updated.status === "CANCEL_REQUESTED"
          ? "已请求停止外部调用，尚未确认已停止。"
          : "排队任务已取消，调用次数记录保留。",
      );
    } catch (cause) {
      setError(errorMessage(cause, "任务取消失败"));
    } finally {
      endAction();
    }
  }
  async function moreBriefs() {
    if (!briefCursor || busyRef.current) return;
    if (!beginAction()) return;
    try {
      const result = await api.get<BriefPage>(
        `${endpoint}/research-briefs?limit=100&cursor=${encodeURIComponent(briefCursor)}`,
      );
      setBriefs((old) => [
        ...old,
        ...result.items.filter(
          (item) => !old.some((value) => value.id === item.id),
        ),
      ]);
      setBriefCursor(result.page.next_cursor);
    } catch (cause) {
      setListError(errorMessage(cause, "更多任务书暂不可读"));
    } finally {
      endAction();
    }
  }
  async function moreGrants() {
    if (!grantCursor || !beginAction()) return;
    try {
      const result = await api.get<GrantPage>(
        `${endpoint}/planning-grants?limit=20&cursor=${encodeURIComponent(grantCursor)}`,
      );
      setGrants((old) => [
        ...(old ?? []),
        ...result.items.filter(
          (item) => !(old ?? []).some((value) => value.id === item.id),
        ),
      ]);
      setGrantCursor(result.page.next_cursor);
    } catch (cause) {
      setListError(errorMessage(cause, "更多授权暂不可读"));
    } finally {
      endAction();
    }
  }
  if (loading) return <LoadingState label="正在读取规划授权与任务…" />;
  if (!project)
    return (
      <ErrorState message={error || "课题不可用"} onRetry={() => void load()} />
    );
  const scopeBusy = busy || !!scopeError || jobs === null;
  const unresolved = !!jobs?.some((job) =>
    ["QUEUED", "RUNNING", "CANCEL_REQUESTED", "NEEDS_ATTENTION"].includes(
      job.status,
    ),
  );
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap gap-4 text-xs text-[var(--muted)]">
        <Link href={`/projects/${projectId}`}>返回课题</Link>
        <Link href={`/projects/${projectId}/brief`}>任务书与本人审阅</Link>
      </div>
      <header className="space-y-2">
        <p className="text-xs uppercase tracking-[0.18em] text-[var(--accent)]">
          Research planning
        </p>
        <h1 className="text-2xl font-semibold">{project.name} · AI 研究规划</h1>
        <p className="text-sm leading-6 text-[var(--muted)]">
          本人决定任务书、专业
          Skill、重要关注点、资料外发和阶段边界。批准后，后台在冻结范围内自动规划；产物保留为待核对候选。
        </p>
      </header>
      {error && (
        <div role="alert" aria-label="规划操作失败">
          <ErrorState message={error} />
        </div>
      )}
      {notice && (
        <p
          role="status"
          className="rounded border border-[var(--accent)] p-3 text-sm"
        >
          {notice}
        </p>
      )}
      {listError && (
        <ErrorState message={listError} onRetry={() => void loadLists()} />
      )}
      {capability ? (
        <>
          <p className="text-xs text-[var(--muted)]">{capability.detail}</p>
          {!capability.enabled && (
            <p className="text-sm font-medium">
              服务器尚未开启规划执行；已有记录和安全停止操作仍可使用。
            </p>
          )}
          <PlanningGrantForm
            capability={capability}
            briefs={briefs}
            busy={busy || !!listError}
            onPreview={preview}
            onInputsChanged={() => {
              if (selected?.state === "DRAFT") {
                selectedRef.current = null;
                setSelected(null);
                setJobs(null);
                setNotice("");
              }
            }}
          />
          {!briefs.some(
            (item) => item.status === "ACCEPTED" && item.context_current,
          ) && (
            <EmptyState
              title="尚无已接受且当前的任务书"
              detail="先在任务书页创建并审阅当前版本，再选择规划范围。"
            />
          )}
          {briefCursor && (
            <Button
              size="sm"
              variant="secondary"
              disabled={busy}
              onClick={() => void moreBriefs()}
            >
              加载更多任务书版本
            </Button>
          )}
        </>
      ) : (
        <p className="text-xs text-[var(--muted)]">
          规划能力未能读取；当前不提供新执行操作。
        </p>
      )}
      <Card>
        <CardHeader>
          <h2 className="font-semibold">已有阶段授权</h2>
          <Button
            size="sm"
            variant="secondary"
            disabled={busy}
            onClick={() => void loadLists()}
          >
            刷新授权列表
          </Button>
        </CardHeader>
        <CardContent>
          {grants === null ? (
            <p className="text-xs text-[var(--muted)]">
              授权列表尚未读取成功，请重试读取。
            </p>
          ) : grants.length ? (
            <ul className="space-y-2">
              {grants.map((grant) => (
                <li
                  key={grant.id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded border border-[var(--border)] p-3 text-xs"
                >
                  <p>
                    {grant.skill_key} · {grant.state} · 已用 {grant.used_jobs}/
                    {grant.max_jobs}
                  </p>
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={busy}
                    onClick={() => {
                      selectedRef.current = grant.id;
                      setSelected(grant);
                      setJobs(null);
                      setFocus("");
                      void readScope(grant.id);
                    }}
                  >
                    查看此授权
                  </Button>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState title="尚无规划阶段授权" />
          )}
        </CardContent>
        {grantCursor && (
          <div className="p-4 pt-0">
            <Button
              size="sm"
              variant="secondary"
              disabled={busy}
              onClick={() => void moreGrants()}
            >
              加载更早的阶段授权
            </Button>
          </div>
        )}
      </Card>
      {scopeError && (
        <ErrorState
          message={scopeError}
          onRetry={() => {
            if (selectedRef.current) void readScope(selectedRef.current);
          }}
        />
      )}
      {selected && (
        <>
          <PlanningGrantDetail
            key={selected.id}
            grant={selected}
            enabled={!!capability?.enabled}
            busy={scopeBusy}
            onApprove={approve}
            onRevoke={revoke}
          />
          <div className="flex items-center justify-between">
            <h2 className="font-semibold">授权范围内的规划任务</h2>
            <Button
              size="sm"
              variant="secondary"
              disabled={busy}
              onClick={() => void readScope(selected.id)}
            >
              刷新授权与任务
            </Button>
          </div>
          {selected.state === "ACTIVE" && (
            <Card>
              <CardContent className="space-y-3 pt-4">
                <label className="block space-y-1.5 text-xs font-medium">
                  下一次规划关注点（可选）
                  <Textarea
                    aria-label="下一次规划关注点（可选）"
                    value={focus}
                    disabled={scopeBusy}
                    maxLength={12000}
                    onChange={(event) => setFocus(event.target.value)}
                    placeholder="留空沿用已批准的关注点。"
                  />
                </label>
                <Button
                  disabled={
                    scopeBusy ||
                    !capability?.enabled ||
                    !selected.can_submit ||
                    selected.jobs_remaining <= 0 ||
                    unresolved ||
                    jobs === null
                  }
                  onClick={() => void createJob()}
                >
                  在此授权范围提交规划
                </Button>
                <p className="text-xs text-[var(--muted)]">
                  后续提交不重新批准同一范围；来源变化、到期、撤销、次数耗尽或未确认调用会阻止新执行。
                </p>
              </CardContent>
            </Card>
          )}
          {jobs === null ? (
            <LoadingState label="正在读取本授权任务…" />
          ) : jobs.length ? (
            jobs.map((job) => (
              <PlanningJobCard
                key={job.id}
                job={job}
                busy={scopeBusy}
                onCancel={() => cancel(job)}
              />
            ))
          ) : (
            <EmptyState title="此授权尚无规划任务" />
          )}
        </>
      )}
    </div>
  );
}
