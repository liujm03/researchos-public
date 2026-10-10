"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { ArrowLeft, ExternalLink, Library, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { api } from "@/lib/api";
import type { components } from "@/lib/generated";

type ResearchLinks = components["schemas"]["LiteratureResearchLinks"];

function officialUrl(value: string) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && !url.username && !url.password
      ? url.href
      : null;
  } catch {
    return null;
  }
}

export default function ProjectLiteraturePage() {
  const { id } = useParams<{ id: string }>();
  return <LiteratureLinksPage key={id} id={id} />;
}

function LiteratureLinksPage({ id }: { id: string }) {
  const endpoint = `/projects/${id}/literature-recommendations/links`;
  const [data, setData] = useState<ResearchLinks | null>(null);
  const [query, setQuery] = useState("");
  const [questionId, setQuestionId] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const requestVersion = useRef(0);
  const retryPath = useRef(endpoint);

  const load = useCallback(async (path: string, initial: boolean) => {
    const version = ++requestVersion.current;
    retryPath.current = path;
    setError("");
    if (initial) setLoading(true);
    else setBusy(true);
    try {
      const result = await api.get<ResearchLinks>(path);
      if (version !== requestVersion.current) return;
      setData(result);
      if (initial) {
        setQuery(result.query);
        setQuestionId("");
      }
    } catch (cause) {
      if (version === requestVersion.current) {
        setError(
          cause instanceof Error ? cause.message : "无法生成文献入口，请重试",
        );
      }
    } finally {
      if (version === requestVersion.current) {
        setLoading(false);
        setBusy(false);
      }
    }
  }, []);

  useEffect(() => {
    const initialLoad = setTimeout(() => void load(endpoint, true), 0);
    return () => {
      clearTimeout(initialLoad);
      requestVersion.current += 1;
    };
  }, [endpoint, load]);

  function generate(event: FormEvent) {
    event.preventDefault();
    const text = query.trim();
    if (!text || text.length > 500) {
      setError("请输入 1–500 字的检索词");
      return;
    }
    const params = new URLSearchParams({ query: text });
    if (questionId) params.set("question_id", questionId);
    void load(`${endpoint}?${params.toString()}`, false);
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Link
          href={`/projects/${id}`}
          className="inline-flex items-center gap-2 text-sm text-[var(--muted)]"
        >
          <ArrowLeft className="h-4 w-4" /> 返回课题
        </Link>
        <Link
          href="/integrations/zotero"
          className="inline-flex items-center gap-2 text-sm text-[var(--accent)]"
        >
          <Library className="h-4 w-4" /> 打开 Zotero 文献库
        </Link>
      </div>
      <div>
        <h1 className="text-2xl font-semibold">课题文献入口</h1>
        <p className="mt-2 text-sm text-[var(--muted)]">
          {data?.project_name ? `${data.project_name} · ` : ""}
          选择官方会议或期刊链接，使用自己的账号查阅，选定后加入 Zotero。
        </p>
      </div>
      {loading ? (
        <LoadingState label="正在读取课题与官方文献入口…" />
      ) : (
        <>
          <Card>
            <CardContent>
              <form onSubmit={generate} className="space-y-4">
                {data && data.questions.length > 0 && (
                  <div>
                    <label
                      htmlFor="literature-question"
                      className="mb-2 block text-sm font-medium"
                    >
                      研究问题
                    </label>
                    <select
                      id="literature-question"
                      value={questionId}
                      disabled={busy}
                      onChange={(event) => {
                        const value = event.target.value;
                        setQuestionId(value);
                        const question = data.questions.find(
                          (item) => item.id === value,
                        );
                        setQuery(question?.question ?? data.project_name);
                      }}
                      className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm"
                    >
                      <option value="">整个课题</option>
                      {data.questions.map((question) => (
                        <option key={question.id} value={question.id}>
                          {question.question}
                        </option>
                      ))}
                    </select>
                  </div>
                )}
                <div>
                  <label
                    htmlFor="literature-query"
                    className="mb-2 block text-sm font-medium"
                  >
                    检索词
                  </label>
                  <div className="flex flex-col gap-3 sm:flex-row">
                    <Input
                      id="literature-query"
                      value={query}
                      onChange={(event) => setQuery(event.target.value)}
                      maxLength={500}
                      required
                      disabled={busy}
                      placeholder="例如 multimodal transmission line inspection"
                      className="flex-1"
                    />
                    <Button type="submit" disabled={busy || !query.trim()}>
                      <Search className="h-4 w-4" />{" "}
                      {busy ? "正在生成…" : "生成检索链接"}
                    </Button>
                  </div>
                </div>
                <p className="text-xs leading-relaxed text-[var(--muted)]">
                  生成链接只在本机处理。点击外部检索链接时，检索词才会发送给对应网站；查阅和登录由你完成。
                </p>
              </form>
            </CardContent>
          </Card>
          {error && (
            <ErrorState
              message={error}
              onRetry={() => void load(retryPath.current, !data)}
            />
          )}
          {data && !error && (
            <>
              <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-4 py-3 text-sm">
                <p>
                  当前检索词：
                  <span className="font-medium break-words">{data.query}</span>
                </p>
                <p className="mt-1 text-[var(--muted)]">
                  优先查阅 {data.recent_from_year}–{data.recent_until_year}{" "}
                  年论文。网站未支持直接带入年份时，请在站内筛选这两个年度。
                </p>
              </div>
              {data.groups.length === 0 ? (
                <EmptyState title="暂无可用官方文献入口" />
              ) : (
                data.groups.map((group) => (
                  <Card key={group.key}>
                    <CardHeader>
                      <h2 className="text-base font-semibold">{group.label}</h2>
                    </CardHeader>
                    <CardContent className="grid gap-3 lg:grid-cols-2">
                      {group.items.length === 0 ? (
                        <EmptyState title="该方向暂无入口" />
                      ) : (
                        group.items.map((item) => {
                          const homepage = officialUrl(item.homepage_url);
                          const search = officialUrl(item.search_url);
                          return (
                            <div
                              key={item.key}
                              className="rounded-lg border border-[var(--border)] p-4"
                            >
                              <h3 className="font-medium">{item.label}</h3>
                              <p className="mt-1 text-xs text-[var(--muted)]">
                                {item.publisher}
                              </p>
                              <div className="mt-3 flex flex-wrap gap-4 text-sm text-[var(--accent)]">
                                {search && (
                                  <a
                                    href={search}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    referrerPolicy="no-referrer"
                                    className="inline-flex items-center gap-1"
                                  >
                                    检索相关论文{" "}
                                    <ExternalLink className="h-3 w-3" />
                                  </a>
                                )}
                                {homepage && (
                                  <a
                                    href={homepage}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    referrerPolicy="no-referrer"
                                    className="inline-flex items-center gap-1"
                                  >
                                    官方网站{" "}
                                    <ExternalLink className="h-3 w-3" />
                                  </a>
                                )}
                              </div>
                              {item.search_note && (
                                <p className="mt-3 text-xs leading-relaxed text-[var(--muted)]">
                                  {item.search_note}
                                </p>
                              )}
                              {!homepage && !search && (
                                <p className="mt-3 text-xs text-[var(--muted)]">
                                  暂无有效链接
                                </p>
                              )}
                            </div>
                          );
                        })
                      )}
                    </CardContent>
                  </Card>
                ))
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}
