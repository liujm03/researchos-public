"use client";

import { useEffect, useState, type FormEvent } from "react";
import { api, ApiError, getSession } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { components } from "@/lib/generated";
import { selectVenueSummary } from "./venue-summary";

export type VenueAssessment = components["schemas"]["VenueAssessmentOut"];
type AssessmentCreate = components["schemas"]["VenueAssessmentCreate"];
const schemes = ["JCR", "CAS", "CCF", "INDEX", "TOP_CONFERENCE"] as const;
const names = {
  JCR: "JCR 分区 / JIF",
  CAS: "中科院分区",
  CCF: "CCF 等级",
  INDEX: "Web of Science 索引",
  TOP_CONFERENCE: "顶会标记（本人定义）",
};
function sourceHref(url: string, sourceKind?: VenueAssessment["source_kind"]) {
  if (
    sourceKind === "ZOTERO_METADATA" &&
    /^\/integrations\/zotero\?item=[A-Z0-9]{8}$/.test(url)
  )
    return url;
  try {
    const parsed = new URL(url);
    return ["https:", "http:"].includes(parsed.protocol) &&
      !parsed.username &&
      !parsed.password
      ? parsed.href
      : undefined;
  } catch {
    return undefined;
  }
}
function sameReceipt(body: AssessmentCreate, receipt: VenueAssessment) {
  return (
    receipt.source_kind === "OWNER_REPORTED" &&
    typeof receipt.id === "string" &&
    Object.entries(body).every(
      ([key, value]) => receipt[key as keyof VenueAssessment] === value,
    )
  );
}
function label(record: VenueAssessment) {
  const year = record.metric_year ?? "年份未注明";
  switch (record.scheme) {
    case "JCR":
      return [
        record.rank_value ? `JCR ${record.rank_value} · ${year}` : null,
        record.impact_factor != null
          ? `IF ${record.impact_factor} · ${year}`
          : null,
      ]
        .filter(Boolean)
        .join(" / ");
    case "CAS":
      return `中科院 ${record.rank_value ? `${record.rank_value} 区${record.is_top ? " · TOP" : ""}` : record.is_top ? "TOP" : "分区未记录"} · ${year}`;
    case "CCF":
      return `CCF ${record.rank_value ?? "未记录"} · ${year}`;
    case "INDEX":
      return `${record.rank_value ?? "索引未记录"} · ${year}`;
    case "TOP_CONFERENCE":
      return `${record.is_top ? "顶会" : "非顶会（本人记录）"} · ${year}`;
  }
}
function sourceLabel(record: VenueAssessment) {
  return record.source_kind === "ZOTERO_METADATA"
    ? "Zotero字段"
    : record.source_kind === "OWNER_REPORTED"
      ? "本人录入"
      : "官方目录";
}
export function VenueBadges({ records = [] }: { records?: VenueAssessment[] }) {
  const chosen = selectVenueSummary(records);
  const chips: { key: string; record: VenueAssessment; text: string }[] = [];
  const year = (row: VenueAssessment) => row.metric_year ?? "年份未注明";
  if (chosen.quarter)
    chips.push({
      key: "jcr",
      record: chosen.quarter,
      text: `JCR ${chosen.quarter.rank_value} · ${year(chosen.quarter)}`,
    });
  if (chosen.impact)
    chips.push({
      key: "if",
      record: chosen.impact,
      text: `IF ${chosen.impact.impact_factor} · ${year(chosen.impact)}`,
    });
  if (chosen.cas)
    chips.push({
      key: "cas",
      record: chosen.cas,
      text: `中科院 ${chosen.cas.rank_value} 区 · ${year(chosen.cas)}`,
    });
  if (chosen.conference)
    chips.push({
      key: "conference",
      record: chosen.conference,
      text: label(chosen.conference),
    });
  return (
    <div className="mt-2 flex flex-wrap gap-1.5" aria-label="期刊与会议标记">
      {chips.map(({ key, record, text }) => (
        <a
          key={key}
          href={sourceHref(record.source_url, record.source_kind)}
          target="_blank"
          rel="noopener noreferrer"
          className="rounded-md border border-[var(--border)] bg-[var(--surface-hover)] px-2 py-1 text-xs text-[var(--accent)] hover:underline"
          title={`${record.category || "未注明学科"}；${record.source_label}；${sourceLabel(record)}；版本 ${record.edition_year ?? "未记录"}；核查 ${record.checked_at}。当前已知年度优先；完整来源与历史在“补充与历史”中查看。`}
        >
          {text}
        </a>
      ))}
      {!chips.length && (
        <span className="text-xs text-[var(--muted)]">
          分区 / IF / 会议等级未记录
        </span>
      )}
    </div>
  );
}

export function VenueRatingsEditor({
  paperId,
  records = [],
  onChange,
}: {
  paperId: string;
  records?: VenueAssessment[];
  onChange: (records: VenueAssessment[]) => void;
}) {
  const [open, setOpen] = useState(false),
    [history, setHistory] = useState(records),
    [loading, setLoading] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [message, setMessage] = useState("");
  const [scheme, setScheme] = useState<VenueAssessment["scheme"]>("JCR"),
    [year, setYear] = useState(String(new Date().getFullYear() - 1)),
    [edition, setEdition] = useState(""),
    [category, setCategory] = useState(""),
    [rank, setRank] = useState(""),
    [impact, setImpact] = useState(""),
    [isTop, setIsTop] = useState(true),
    [url, setUrl] = useState(""),
    [source, setSource] = useState("");
  const [pending, setPending] = useState<AssessmentCreate | null>(null),
    [storageKey, setStorageKey] = useState(""),
    [absent, setAbsent] = useState(false);
  const path = `/papers/${paperId}/venue-assessments`;
  useEffect(() => {
    let active = true;
    getSession()
      .then((owner) => {
        const key = `researchos:venue-assessment:${owner.id}:${paperId}`;
        const saved = localStorage.getItem(key);
        if (active) {
          setStorageKey(key);
          setPending(null);
          setAbsent(false);
          setMessage("");
          if (saved) {
            const body = JSON.parse(saved) as AssessmentCreate;
            if (
              !body ||
              typeof body.request_key !== "string" ||
              !/^[0-9a-f-]{36}$/i.test(body.request_key) ||
              !schemes.includes(body.scheme) ||
              !Number.isInteger(body.metric_year) ||
              typeof body.category !== "string" ||
              typeof body.source_label !== "string" ||
              !sourceHref(body.source_url)
            )
              throw new Error("Invalid pending record");
            setPending(body);
            setMessage("有一条尚未核查保存结果的记录，请先核查。");
          }
        }
      })
      .catch(() => {
        if (active) setError("无法准备保存记录，请刷新后重试。");
      });
    return () => {
      active = false;
    };
  }, [paperId]);
  async function loadHistory() {
    setLoading(true);
    setError("");
    try {
      const found = await api.get<VenueAssessment[]>(path);
      setHistory(found);
      onChange(found);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "无法读取评级历史");
    } finally {
      setLoading(false);
    }
  }
  async function refreshZotero() {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const found = await api.post<VenueAssessment[]>(`${path}/refresh-zotero`);
      setHistory(found);
      onChange(found);
      setMessage(
        found.some((row) => row.source_kind === "ZOTERO_METADATA")
          ? "已从 Zotero 字段更新；官方目录和本人记录保留。"
          : "Zotero 条目中未发现可识别的评级字段；官方目录和本人记录保留。",
      );
    } catch (cause) {
      const detail = cause instanceof Error ? cause.message : "刷新失败";
      setError(`Zotero 字段刷新未完成，当前显示的记录保留。${detail}`);
    } finally {
      setBusy(false);
    }
  }
  function clearPending() {
    localStorage.removeItem(storageKey);
    setPending(null);
    setAbsent(false);
  }
  async function reconcile() {
    if (!pending) return;
    setBusy(true);
    setError("");
    setAbsent(false);
    try {
      const found = await api.get<VenueAssessment[]>(
        `${path}?request_key=${encodeURIComponent(pending.request_key)}`,
      );
      const receipt = found.find(
        (row) => row.request_key === pending.request_key,
      );
      if (receipt) {
        if (!sameReceipt(pending, receipt))
          throw new Error(
            "已找到相同请求编号，但内容不一致；请检查历史记录，不会自动重写。",
          );
        clearPending();
        setMessage("已核查到保存回执。");
        await loadHistory();
      } else {
        setAbsent(true);
        setMessage("此次核查尚未找到记录，可以恢复提交相同编号和内容。");
      }
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "核查失败，尚不能恢复提交",
      );
    } finally {
      setBusy(false);
    }
  }
  async function send(body: AssessmentCreate) {
    setBusy(true);
    setError("");
    setMessage("");
    setAbsent(false);
    try {
      const receipt = await api.post<VenueAssessment>(path, body);
      if (!sameReceipt(body, receipt))
        throw new Error(
          "保存回执与提交内容不一致，请先核查，不会自动重新提交。",
        );
      clearPending();
      setMessage("记录已保存；同场馆文献共享该记录。");
      await loadHistory();
    } catch (cause) {
      if (
        cause instanceof ApiError &&
        cause.status >= 400 &&
        cause.status < 500 &&
        ![408, 409, 429].includes(cause.status)
      )
        clearPending();
      setError(
        cause instanceof Error ? cause.message : "保存结果未知，请先核查",
      );
    } finally {
      setBusy(false);
    }
  }
  async function save(event: FormEvent) {
    event.preventDefault();
    if (pending || !storageKey) return;
    const body: AssessmentCreate = {
      request_key: crypto.randomUUID(),
      scheme,
      metric_year: Number(year),
      edition_year: edition ? Number(edition) : null,
      category: category.trim(),
      rank_value: scheme === "TOP_CONFERENCE" || !rank ? null : rank,
      impact_factor: scheme === "JCR" && impact !== "" ? Number(impact) : null,
      is_top: scheme === "TOP_CONFERENCE" ? isTop : null,
      source_url: url.trim(),
      source_label: source.trim(),
    };
    try {
      localStorage.setItem(storageKey, JSON.stringify(body));
      setPending(body);
      await send(body);
    } catch {
      setError("无法保留请求编号，尚未提交；请检查浏览器存储权限。");
    }
  }
  const ranks =
    scheme === "JCR"
      ? ["Q1", "Q2", "Q3", "Q4"]
      : scheme === "CAS"
        ? ["1", "2", "3", "4"]
        : scheme === "CCF"
          ? ["A", "B", "C"]
          : ["SCIE", "SSCI", "ESCI", "AHCI"];
  return (
    <details
      className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4"
      onToggle={(event) => {
        if (event.target !== event.currentTarget) return;
        const expanded = event.currentTarget.open;
        setOpen(expanded);
        if (expanded) void loadHistory();
      }}
    >
      <summary className="cursor-pointer text-sm font-medium">
        期刊 / 会议标记：补充与历史
      </summary>
      {open && (
        <div className="mt-4 space-y-4">
          <p className="text-sm leading-6 text-[var(--muted)]">
            JCR 分区与中科院分区分别记录。IF 为两年
            JIF，填写指标年份和学科；旧年度不会标为最新。手工记录显示为本人录入，场馆等级不代表单篇论文质量。
          </p>
          <div className="space-y-2">
            <Button
              variant="secondary"
              disabled={busy || loading}
              onClick={() => void refreshZotero()}
            >
              {busy ? "正在处理…" : "从Zotero字段刷新"}
            </Button>
            <p className="text-xs text-[var(--muted)]">
              仅读取已关联条目的元数据，不读取 PDF 或调用 AI；Zotero
              字段不代表官方评级核验，缺失年份保留为未注明。
            </p>
          </div>
          {error && (
            <p role="alert" className="text-sm text-[var(--danger)]">
              {error}
            </p>
          )}
          {message && (
            <p role="status" className="text-sm text-[var(--muted)]">
              {message}
            </p>
          )}
          {pending && (
            <div className="space-y-2 rounded border border-amber-500/40 p-3">
              <p className="text-sm">
                待核查：{names[pending.scheme]} · {pending.metric_year} ·{" "}
                {pending.source_label}
              </p>
              <Button
                variant="secondary"
                disabled={busy}
                onClick={() => void reconcile()}
              >
                核查保存结果
              </Button>
              {absent && (
                <Button disabled={busy} onClick={() => void send(pending)}>
                  恢复相同请求
                </Button>
              )}
            </div>
          )}
          <form onSubmit={save} className="grid gap-3 sm:grid-cols-2">
            <fieldset disabled={busy || !!pending} className="contents">
              <label className="space-y-1 text-sm">
                评级标准
                <select
                  aria-label="评级标准"
                  className="h-9 w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-3"
                  value={scheme}
                  onChange={(event) => {
                    const value = event.target
                      .value as VenueAssessment["scheme"];
                    setScheme(value);
                    setRank("");
                  }}
                >
                  {schemes.map((item) => (
                    <option key={item} value={item}>
                      {names[item]}
                    </option>
                  ))}
                </select>
              </label>
              <label className="space-y-1 text-sm">
                指标 / 分区年份
                <Input
                  aria-label="指标 / 分区年份"
                  type="number"
                  min="1900"
                  max="2200"
                  required
                  value={year}
                  onChange={(event) => setYear(event.target.value)}
                />
              </label>
              <label className="space-y-1 text-sm">
                发布版本年份（可选）
                <Input
                  aria-label="发布版本年份"
                  type="number"
                  min="1900"
                  max="2200"
                  value={edition}
                  onChange={(event) => setEdition(event.target.value)}
                />
              </label>
              <label className="space-y-1 text-sm">
                学科 / 分区类别
                <Input
                  aria-label="学科 / 分区类别"
                  required
                  value={category}
                  onChange={(event) => setCategory(event.target.value)}
                  placeholder="如 Computer Science, Artificial Intelligence / 大类：计算机科学"
                />
              </label>
              {scheme === "TOP_CONFERENCE" ? (
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={isTop}
                    onChange={(event) => setIsTop(event.target.checked)}
                  />
                  本人标记为顶会
                </label>
              ) : (
                <label className="space-y-1 text-sm">
                  分区 / 等级
                  <select
                    aria-label="分区 / 等级"
                    required={scheme !== "JCR"}
                    className="h-9 w-full rounded-md border border-[var(--border)] bg-[var(--background)] px-3"
                    value={rank}
                    onChange={(event) => setRank(event.target.value)}
                  >
                    <option value="">
                      {scheme === "JCR"
                        ? "分区未记录（可只记录 JIF）"
                        : "请选择已核实的分区 / 等级"}
                    </option>
                    {ranks.map((item) => (
                      <option key={item}>{item}</option>
                    ))}
                  </select>
                </label>
              )}
              {scheme === "JCR" && (
                <label className="space-y-1 text-sm">
                  两年影响因子 JIF（可选）
                  <Input
                    aria-label="两年影响因子 JIF"
                    type="number"
                    min="0"
                    step="0.001"
                    value={impact}
                    onChange={(event) => setImpact(event.target.value)}
                  />
                </label>
              )}
              <label className="space-y-1 text-sm">
                来源名称
                <Input
                  aria-label="来源名称"
                  required
                  maxLength={200}
                  value={source}
                  onChange={(event) => setSource(event.target.value)}
                />
              </label>
              <label className="space-y-1 text-sm">
                来源链接
                <Input
                  aria-label="来源链接"
                  type="url"
                  pattern="https?://.*"
                  required
                  value={url}
                  onChange={(event) => setUrl(event.target.value)}
                />
              </label>
              <Button
                type="submit"
                disabled={busy || !!pending || !storageKey}
                className="justify-self-start"
              >
                {busy ? "正在保存…" : "保存本人记录"}
              </Button>
            </fieldset>
          </form>
          <div className="border-t border-[var(--border)] pt-3">
            <h3 className="text-sm font-semibold">记录历史</h3>
            {loading ? (
              <p className="mt-2 text-sm text-[var(--muted)]">正在读取…</p>
            ) : !history.length ? (
              <p className="mt-2 text-sm text-[var(--muted)]">
                尚无记录；没有来源的数值不会自动推测。
              </p>
            ) : (
              <ul className="mt-2 space-y-3">
                {[...history]
                  .sort(
                    (a, b) =>
                      (b.metric_year ?? -1) - (a.metric_year ?? -1) ||
                      b.checked_at.localeCompare(a.checked_at),
                  )
                  .map((row, index) => (
                    <li
                      key={row.id ?? `${row.scheme}:${index}`}
                      className="break-words text-sm"
                    >
                      <p>
                        {label(row)} · {row.category}
                      </p>
                      <p className="text-xs text-[var(--muted)]">
                        版本 {row.edition_year ?? "未记录"} · {sourceLabel(row)}{" "}
                        · 核查{" "}
                        {new Date(row.checked_at).toLocaleDateString("zh-CN")}
                      </p>
                      <a
                        className="text-[var(--accent)] hover:underline"
                        href={sourceHref(row.source_url, row.source_kind)}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        {row.source_label} ↗
                      </a>
                      {row.source_kind === "ZOTERO_METADATA" && (
                        <details className="mt-1 rounded border border-[var(--border)] px-2 py-1">
                          <summary className="cursor-pointer text-xs">
                            Zotero 原始字段
                          </summary>
                          <dl className="mt-2 space-y-1 text-xs">
                            <div>
                              <dt className="inline text-[var(--muted)]">
                                字段：
                              </dt>
                              <dd className="inline whitespace-pre-wrap">
                                {row.raw_field ?? "未记录"}
                              </dd>
                            </div>
                            <div>
                              <dt className="inline text-[var(--muted)]">
                                原始值：
                              </dt>
                              <dd className="inline whitespace-pre-wrap">
                                {row.raw_value ?? "未记录"}
                              </dd>
                            </div>
                            <div>
                              <dt className="inline text-[var(--muted)]">
                                条目 / 版本：
                              </dt>
                              <dd className="inline">
                                {row.source_item_key ?? "未记录"} /{" "}
                                {row.source_version ?? "未记录"}
                              </dd>
                            </div>
                          </dl>
                        </details>
                      )}
                    </li>
                  ))}
              </ul>
            )}
            <Button
              className="mt-3"
              variant="ghost"
              disabled={loading}
              onClick={() => void loadHistory()}
            >
              刷新记录
            </Button>
          </div>
        </div>
      )}
    </details>
  );
}
