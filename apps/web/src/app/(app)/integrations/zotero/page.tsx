"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import {
  BookOpen,
  FileText,
  FolderOpen,
  Import,
  LibraryBig,
  Search,
  Unplug,
} from "lucide-react";

import { ZoteroSyncSummary } from "@/components/zotero/sync-summary";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import {
  api,
  type ClearLiteratureJobsOut,
  type LiteratureJob,
  type ZoteroAttachment,
  type ZoteroCatalogPage,
  type ZoteroCollection,
  type ZoteroFulltext,
  type ZoteroItem,
  type ZoteroStatus,
  type ZoteroSyncJob,
  type ZoteroSyncJobPage,
  type ZoteroSyncItemPage,
  type ZoteroSyncRequest,
} from "@/lib/api";

const base = "/reference-managers/zotero";
const syncStatusLabels: Record<string, string> = {
  QUEUED: "等待执行",
  RUNNING: "正在同步",
  COMPLETED: "同步完成",
  PARTIAL: "部分完成",
  FAILED: "同步失败",
  CANCELLED: "已取消",
};
const pendingSyncKey = "researchos.zotero.pending-incremental-sync";
const pendingFullSyncKey = "researchos.zotero.pending-full-library-sync";
const catalogPageSize = 100;

async function readCollections(): Promise<ZoteroCollection[]> {
  const collected = new Map<string, ZoteroCollection>();
  let start = 0;
  while (true) {
    const page = await api.get<ZoteroCollection[]>(
      `${base}/collections?limit=100&start=${start}`,
    );
    const previousCount = collected.size;
    for (const collection of page) collected.set(collection.key, collection);
    if (page.length < 100) return [...collected.values()];
    if (collected.size === previousCount)
      throw new Error("Zotero collection 分页未推进，请刷新连接后重试。");
    start += page.length;
  }
}

export default function ZoteroPage() {
  const router = useRouter();
  const [status, setStatus] = useState<ZoteroStatus | null>(null);
  const [collections, setCollections] = useState<ZoteroCollection[]>([]);
  const [items, setItems] = useState<ZoteroItem[]>([]);
  const [catalog, setCatalog] = useState<ZoteroCatalogPage | null>(null);
  const [catalogError, setCatalogError] = useState("");
  const [selected, setSelected] = useState<ZoteroItem | null>(null);
  const [attachments, setAttachments] = useState<ZoteroAttachment[]>([]);
  const [fulltext, setFulltext] = useState<ZoteroFulltext | null>(null);
  const [query, setQuery] = useState("");
  const [collectionKey, setCollectionKey] = useState("");
  const [copyPdf, setCopyPdf] = useState(false);
  const [loading, setLoading] = useState(true);
  const [searching, setSearching] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState<ZoteroSyncJob | null>(null);
  const [syncJobs, setSyncJobs] = useState<ZoteroSyncJobPage | null>(null);
  const [syncItems, setSyncItems] = useState<ZoteroSyncItemPage | null>(null);
  const [syncJobsOffset, setSyncJobsOffset] = useState(0);
  const [syncItemsOffset, setSyncItemsOffset] = useState(0);
  const [syncJobsLoading, setSyncJobsLoading] = useState(true);
  const [syncItemsLoading, setSyncItemsLoading] = useState(false);
  const [syncJobsError, setSyncJobsError] = useState("");
  const [syncItemsError, setSyncItemsError] = useState("");
  const [syncDetailError, setSyncDetailError] = useState("");
  const [syncIssuesOpen, setSyncIssuesOpen] = useState(false);
  const issueRequest = useRef(0);
  const [syncActionError, setSyncActionError] = useState("");
  const [syncMessage, setSyncMessage] = useState("");
  const submissionKeys = useRef<Record<string, string>>({});
  const catalogRequest = useRef(0);
  const catalogFilter = useRef({ query: "", collectionKey: "" });
  const catalogRetry = useRef({ query: "", collectionKey: "", start: 0 });
  const detailRequest = useRef(0);
  const [jobs, setJobs] = useState<LiteratureJob[]>([]);
  const [processingOpen, setProcessingOpen] = useState(false);
  const [jobsError, setJobsError] = useState("");
  const [jobsLoading, setJobsLoading] = useState(false);
  const [clearingJobs, setClearingJobs] = useState(false);
  const [jobsMessage, setJobsMessage] = useState("");
  const jobsRequest = useRef(0);

  const loadSyncJobs = useCallback(async () => {
    setSyncJobsLoading(true);
    try {
      const page = await api.get<ZoteroSyncJobPage>(
        `${base}/sync/jobs?limit=10&offset=${syncJobsOffset}`,
      );
      setSyncJobs(page);
      setSyncResult((current) =>
        current
          ? (page.items.find((job) => job.job_id === current.job_id) ?? current)
          : (page.items[0] ?? null),
      );
      setSyncJobsError("");
    } catch (cause) {
      setSyncJobsError(
        cause instanceof Error ? cause.message : "无法读取同步任务",
      );
    } finally {
      setSyncJobsLoading(false);
    }
  }, [syncJobsOffset]);

  const syncJobId = syncResult?.job_id;
  const loadSyncDetail = useCallback(async () => {
    if (!syncJobId) return;
    const requestNumber = ++detailRequest.current;
    try {
      const job = await api.get<ZoteroSyncJob>(
        `${base}/sync/jobs/${syncJobId}`,
      );
      if (requestNumber !== detailRequest.current) return;
      setSyncResult((current) =>
        current?.job_id === job.job_id ? job : current,
      );
      setSyncDetailError("");
    } catch (cause) {
      if (requestNumber === detailRequest.current)
        setSyncDetailError(
          cause instanceof Error ? cause.message : "无法读取同步状态",
        );
    }
  }, [syncJobId]);

  const loadSyncIssues = useCallback(async () => {
    if (!syncJobId) return;
    const requestNumber = ++issueRequest.current;
    setSyncItemsLoading(true);
    try {
      const page = await api.get<ZoteroSyncItemPage>(
        `${base}/sync/jobs/${syncJobId}/items?status=FAILED&limit=20&offset=${syncItemsOffset}`,
      );
      if (requestNumber !== issueRequest.current) return;
      setSyncItems(page);
      setSyncItemsError("");
    } catch (cause) {
      if (requestNumber === issueRequest.current)
        setSyncItemsError(
          cause instanceof Error ? cause.message : "无法读取同步异常",
        );
    } finally {
      if (requestNumber === issueRequest.current) setSyncItemsLoading(false);
    }
  }, [syncJobId, syncItemsOffset]);

  useEffect(() => {
    if (!syncIssuesOpen || !syncResult?.failed) return;
    queueMicrotask(() => void loadSyncIssues());
  }, [syncIssuesOpen, syncResult?.failed, loadSyncIssues]);

  const loadJobs = useCallback(async () => {
    const requestNumber = ++jobsRequest.current;
    setJobsLoading(true);
    try {
      const records = await api.get<LiteratureJob[]>(
        "/literature-jobs?limit=10",
      );
      if (requestNumber !== jobsRequest.current) return;
      setJobs(records);
      setJobsError("");
    } catch (cause) {
      if (requestNumber === jobsRequest.current)
        setJobsError(
          cause instanceof Error ? cause.message : "无法加载文献处理任务",
        );
    } finally {
      if (requestNumber === jobsRequest.current) setJobsLoading(false);
    }
  }, []);

  async function clearJobs() {
    if (clearingJobs) return;
    setClearingJobs(true);
    setJobsError("");
    setJobsMessage("");
    jobsRequest.current += 1;
    setJobsLoading(false);
    try {
      const result = await api.post<ClearLiteratureJobsOut>(
        "/literature-jobs/clear",
      );
      setJobs([]);
      setJobsMessage(
        "任务列表已清空：" +
          result.cleared +
          " 项，停止 " +
          result.cancelled +
          " 项未完成处理。论文、PDF 和笔记保留。",
      );
      await loadJobs();
    } catch (cause) {
      setJobsError(cause instanceof Error ? cause.message : "清空任务列表失败");
    } finally {
      setClearingJobs(false);
    }
  }

  const loadCatalog = useCallback(
    async (searchQuery: string, selectedCollection: string, start: number) => {
      const requestNumber = ++catalogRequest.current;
      setSearching(true);
      setCatalogError("");
      const params = new URLSearchParams({
        q: searchQuery,
        limit: String(catalogPageSize),
        start: String(start),
      });
      if (selectedCollection) params.set("collection_key", selectedCollection);
      catalogRetry.current = {
        query: searchQuery,
        collectionKey: selectedCollection,
        start,
      };
      try {
        const page = await api.get<ZoteroCatalogPage>(
          `${base}/catalog/items?${params}`,
        );
        if (requestNumber !== catalogRequest.current) return;
        setItems(page.items);
        setCatalog(page);
        catalogFilter.current = {
          query: searchQuery,
          collectionKey: selectedCollection,
        };
      } catch (cause) {
        if (requestNumber === catalogRequest.current)
          setCatalogError(
            cause instanceof Error ? cause.message : "Zotero 文献分页读取失败",
          );
      } finally {
        if (requestNumber === catalogRequest.current) setSearching(false);
      }
    },
    [],
  );

  const load = useCallback(() => {
    api
      .get<ZoteroStatus>(`${base}/status`)
      .then(async (connection) => {
        setStatus(connection);
        if (!connection.connected) return;
        const [, libraryCollections] = await Promise.all([
          loadCatalog("", "", 0),
          readCollections(),
        ]);
        setCollections(libraryCollections);
        const linkedKey = new URLSearchParams(window.location.search).get(
          "item",
        );
        if (linkedKey) {
          const linked = await api.get<ZoteroItem>(
            `${base}/items/${encodeURIComponent(linkedKey)}`,
          );
          setSelected(linked);
          setAttachments(
            await api.get<ZoteroAttachment[]>(
              `${base}/items/${linked.key}/attachments`,
            ),
          );
        }
      })
      .catch((cause) =>
        setError(cause instanceof Error ? cause.message : "无法连接 Zotero"),
      )
      .finally(() => setLoading(false));
  }, [loadCatalog]);

  useEffect(load, [load]);
  useEffect(() => {
    queueMicrotask(() => void loadJobs());
  }, [loadJobs]);
  useEffect(() => {
    queueMicrotask(() => void loadSyncJobs());
  }, [loadSyncJobs]);
  useEffect(() => {
    queueMicrotask(() => void loadSyncDetail());
  }, [loadSyncDetail]);
  const hasActiveSync =
    syncJobs?.items.some((job) => ["QUEUED", "RUNNING"].includes(job.status)) ||
    (syncResult && ["QUEUED", "RUNNING"].includes(syncResult.status));
  useEffect(() => {
    if (!hasActiveSync) return;
    const timer = window.setInterval(() => {
      void loadSyncJobs();
      void loadSyncDetail();
    }, 3000);
    return () => window.clearInterval(timer);
  }, [hasActiveSync, loadSyncJobs, loadSyncDetail]);

  async function search(event: FormEvent) {
    event.preventDefault();
    setSelected(null);
    setFulltext(null);
    await loadCatalog(query, collectionKey, 0);
  }

  async function syncLibrary(fullLibrary = false) {
    setSyncing(true);
    setSyncActionError("");
    setSyncMessage("");
    try {
      const storageKey = fullLibrary ? pendingFullSyncKey : pendingSyncKey;
      if (!submissionKeys.current[storageKey]) {
        try {
          const saved = window.sessionStorage.getItem(storageKey);
          if (saved) submissionKeys.current[storageKey] = saved;
        } catch {
          /* Browser storage may be unavailable. */
        }
        submissionKeys.current[storageKey] ??= crypto.randomUUID();
      }
      try {
        window.sessionStorage.setItem(
          storageKey,
          submissionKeys.current[storageKey],
        );
      } catch {
        /* The in-memory request key still protects retries. */
      }
      const body: ZoteroSyncRequest = {
        idempotency_key: submissionKeys.current[storageKey],
        full_library: fullLibrary,
      };
      const result = await api.post<ZoteroSyncJob>(`${base}/sync`, body);
      setSyncResult(result);
      issueRequest.current += 1;
      setSyncIssuesOpen(false);
      setSyncItemsLoading(false);
      setSyncItems(null);
      setSyncItemsOffset(0);
      setSyncJobsOffset(0);
      delete submissionKeys.current[storageKey];
      try {
        window.sessionStorage.removeItem(storageKey);
      } catch {
        /* Receipt has already been received. */
      }
      setSyncMessage(
        result.status === "QUEUED"
          ? "同步任务已保存，等待 worker 执行。刷新页面后仍可查看进度。"
          : `已恢复同步任务：${syncStatusLabels[result.status]}。`,
      );
      await loadSyncJobs();
    } catch (cause) {
      setSyncActionError(
        `${cause instanceof Error ? cause.message : "Zotero 同步请求失败"}。再次提交将复用本次请求编号，避免重复创建。`,
      );
    } finally {
      setSyncing(false);
    }
  }

  function selectSyncJob(job: ZoteroSyncJob) {
    detailRequest.current += 1;
    issueRequest.current += 1;
    setSyncIssuesOpen(false);
    setSyncItemsLoading(false);
    setSyncDetailError("");
    setSyncResult(job);
    setSyncItems(null);
    setSyncItemsOffset(0);
    setSyncItemsError("");
  }

  async function updateSyncJob(action: "retry" | "cancel") {
    if (!syncResult) return;
    setSyncing(true);
    setSyncActionError("");
    setSyncMessage("");
    try {
      const updated = await api.post<ZoteroSyncJob>(
        `${base}/sync/jobs/${syncResult.job_id}/${action}`,
      );
      issueRequest.current += 1;
      setSyncIssuesOpen(false);
      setSyncItemsLoading(false);
      setSyncItems(null);
      setSyncItemsOffset(0);
      setSyncResult(updated);
      setSyncMessage(
        action === "retry"
          ? "同步任务已重新排队，已完成的条目会保留。"
          : "同步任务已取消，已保存的论文仍可查阅。",
      );
      await loadSyncJobs();
      await loadSyncDetail();
    } catch (cause) {
      setSyncActionError(
        cause instanceof Error ? cause.message : "无法更新同步任务",
      );
    } finally {
      setSyncing(false);
    }
  }

  async function selectItem(item: ZoteroItem) {
    setSelected(item);
    setFulltext(null);
    setAttachments([]);
    setError("");
    try {
      setAttachments(
        await api.get<ZoteroAttachment[]>(
          `${base}/items/${encodeURIComponent(item.key)}/attachments`,
        ),
      );
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "附件读取失败");
    }
  }

  async function ingestItem() {
    if (!selected) return;
    setBusy(true);
    setError("");
    try {
      const job = await api.post<LiteratureJob>(
        `${base}/items/${encodeURIComponent(selected.key)}/ingest`,
        {
          copy_pdf: copyPdf,
        },
      );
      router.push(`/literature-jobs/${job.id}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "文献处理任务创建失败");
    } finally {
      setBusy(false);
    }
  }

  async function readFulltext(attachmentKey: string) {
    if (!selected) return;
    setBusy(true);
    setError("");
    try {
      setFulltext(
        await api.get<ZoteroFulltext>(
          `${base}/items/${encodeURIComponent(selected.key)}/attachments/${encodeURIComponent(attachmentKey)}/fulltext?limit_chars=20000`,
        ),
      );
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Zotero 尚无可读取的全文索引",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <p className="mb-1 text-xs font-medium uppercase tracking-[0.18em] text-[var(--accent)]">
          Reference manager
        </p>
        <Link
          href="/papers"
          className="mb-2 inline-block text-xs text-[var(--accent)]"
        >
          返回文献中心
        </Link>
        <h1 className="text-2xl font-semibold">Zotero 文献库</h1>
        <p className="mt-1 text-sm text-[var(--muted)]">
          从你自己的 Zotero 库检索、查阅和导入论文。当前连接为只读。
        </p>
      </div>
      <ZoteroSyncSummary
        job={syncResult}
        records={syncJobs}
        loading={syncJobsLoading}
        recordsOffset={syncJobsOffset}
        recordsError={syncJobsError}
        detailError={syncDetailError}
        actionError={syncActionError}
        message={syncMessage}
        busy={syncing}
        issuesOpen={syncIssuesOpen}
        issues={syncItems}
        issuesLoading={syncItemsLoading}
        issuesError={syncItemsError}
        issuesOffset={syncItemsOffset}
        onRefresh={() => {
          void loadSyncJobs();
          void loadSyncDetail();
          if (syncIssuesOpen) void loadSyncIssues();
        }}
        onSelect={selectSyncJob}
        onRecordsOffset={setSyncJobsOffset}
        onAction={(action) => void updateSyncJob(action)}
        onToggleIssues={() => {
          issueRequest.current += 1;
          setSyncItemsLoading(false);
          setSyncIssuesOpen((current) => !current);
        }}
        onReloadIssues={() => void loadSyncIssues()}
        onIssuesOffset={setSyncItemsOffset}
      />
      {jobsError && (
        <ErrorState message={jobsError} onRetry={() => void loadJobs()} />
      )}
      {jobsMessage && (
        <p role="status" className="text-xs text-[var(--accent)]">
          {jobsMessage}
        </p>
      )}
      {jobs.some(
        (job) =>
          job.error_code ||
          job.warning_code ||
          job.status === "FAILED" ||
          job.status.startsWith("WAITING_"),
      ) && (
        <div
          role="alert"
          aria-label="文献处理需处理事项"
          className="space-y-2 rounded border border-amber-500/40 p-3 text-xs"
        >
          <p>
            {
              jobs.filter(
                (job) =>
                  job.error_code ||
                  job.warning_code ||
                  job.status === "FAILED" ||
                  job.status.startsWith("WAITING_"),
              ).length
            }{" "}
            条处理记录需核对
          </p>
          {jobs
            .filter(
              (job) =>
                job.error_code ||
                job.warning_code ||
                job.status === "FAILED" ||
                job.status.startsWith("WAITING_"),
            )
            .map((job) => (
              <Link
                key={job.id}
                className="block text-[var(--accent)] underline"
                href={`/literature-jobs/${job.id}`}
              >
                {job.item_title} ·{" "}
                {job.error_message ||
                  job.warning_message ||
                  "查看等待原因与下一步"}
              </Link>
            ))}
        </div>
      )}
      <details
        open={processingOpen}
        onToggle={(event) => setProcessingOpen(event.currentTarget.open)}
        className="rounded-md border border-[var(--border)] p-3"
      >
        <summary className="cursor-pointer text-sm font-medium">
          处理记录 · {jobs.length} 条
        </summary>
        <div className="mt-3">
          {" "}
          <Card>
            <CardHeader>
              <h2 className="font-semibold">处理记录</h2>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => void loadJobs()}
                  disabled={jobsLoading || clearingJobs}
                >
                  {jobsLoading ? "刷新中…" : "刷新"}
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => void clearJobs()}
                  disabled={jobsLoading || clearingJobs || jobs.length === 0}
                >
                  {clearingJobs ? "清空中…" : "清空任务列表"}
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              {jobsLoading && !jobs.length ? (
                <LoadingState label="正在读取处理任务…" />
              ) : jobs.length ? (
                <div className="divide-y divide-[var(--border)]">
                  {jobs.map((job) => (
                    <Link
                      key={job.id}
                      href={`/literature-jobs/${job.id}`}
                      className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm hover:text-[var(--accent)]"
                    >
                      <span className="min-w-0">
                        <span className="block truncate font-medium">
                          {job.item_title}
                        </span>
                        <span className="text-xs text-[var(--muted)]">
                          {new Date(job.created_at).toLocaleString("zh-CN")}
                        </span>
                      </span>
                      <span className="text-xs text-[var(--muted)]">
                        {job.stage} · {job.status}
                      </span>
                    </Link>
                  ))}
                </div>
              ) : (
                !jobsError && (
                  <EmptyState
                    title="尚无文献处理任务"
                    detail="选择一篇 Zotero 文献后，可创建可追踪的导入任务。"
                  />
                )
              )}
            </CardContent>
          </Card>
        </div>
      </details>
      {loading ? (
        <LoadingState label="正在检查 Zotero 连接…" />
      ) : error && !status ? (
        <ErrorState
          message={error}
          onRetry={() => {
            setLoading(true);
            setError("");
            load();
          }}
        />
      ) : status && !status.connected ? (
        <Card>
          <CardContent className="flex max-w-2xl gap-4 p-6">
            <Unplug className="mt-0.5 h-5 w-5 shrink-0 text-[var(--muted)]" />
            <div>
              <h2 className="font-semibold">Zotero 尚未启用</h2>
              <p className="mt-2 text-sm leading-6 text-[var(--muted)]">
                本机使用 `ZOTERO_MODE=local` 并启用 Zotero Desktop Local
                API；容器或服务器可配置 `ZOTERO_MODE=web`、只读 Web API Key 与库
                ID。配置保存在服务端环境变量中，重启 API 后再连接。
              </p>
            </div>
          </CardContent>
        </Card>
      ) : (
        status && (
          <>
            <Card>
              <CardContent className="flex flex-wrap items-center gap-3 p-4">
                <span className="h-2 w-2 rounded-full bg-emerald-500" />
                <span className="text-sm font-medium">
                  {status.mode === "web"
                    ? "Zotero Web API 已连接"
                    : "本机 Zotero 已连接"}
                </span>
                <span className="text-xs text-[var(--muted)]">
                  API v{status.api_version} · {collections.length} 个 collection
                  已加载
                </span>
              </CardContent>
            </Card>
            {(status.mode === "local" || status.mode === "web") && (
              <div className="flex flex-wrap items-center gap-3">
                <Button
                  onClick={() => void syncLibrary(true)}
                  disabled={syncing}
                >
                  {syncing ? "提交中…" : "读取全部文献"}
                </Button>
                <Button
                  variant="secondary"
                  onClick={() => void syncLibrary(false)}
                  disabled={syncing}
                >
                  {syncing ? "提交中…" : "启动增量同步"}
                </Button>
                <p className="text-xs text-[var(--muted)]">
                  整库读取从头遍历当前文献库的全部来源页，不受每轮自动同步上限限制。分析由你单独提交，进度见上方「同步状态」。
                </p>
              </div>
            )}

            {collections.length > 0 && (
              <label className="flex max-w-xl flex-wrap items-center gap-2 text-xs text-[var(--muted)]">
                浏览 collection
                <select
                  value={collectionKey}
                  aria-label="浏览 collection"
                  disabled={searching}
                  onChange={(event) => {
                    const key = event.target.value;
                    setCollectionKey(key);
                    setSelected(null);
                    setFulltext(null);
                    setItems([]);
                    setCatalog(null);
                    void loadCatalog(query, key, 0);
                  }}
                  className="h-9 min-w-52 flex-1 rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 text-sm text-[var(--foreground)]"
                >
                  <option value="">整个文献库</option>
                  {collections.map((collection) => (
                    <option key={collection.key} value={collection.key}>
                      {collection.name}
                    </option>
                  ))}
                </select>
                <span>选择分类后自动更新文献</span>
              </label>
            )}
            <div className="grid gap-4 xl:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)]">
              <Card className="min-w-0">
                <CardHeader>
                  <div className="flex items-center gap-2">
                    <LibraryBig className="h-4 w-4 text-[var(--accent)]" />
                    <h2 className="font-semibold">当前文献库</h2>
                  </div>
                  <span className="text-xs text-[var(--muted)]">
                    本页 {items.length} 篇
                  </span>
                </CardHeader>
                <CardContent className="p-0">
                  <form
                    onSubmit={search}
                    className="flex gap-2 border-b border-[var(--border)] p-4"
                  >
                    <div className="relative flex-1">
                      <Search className="absolute left-3 top-2.5 h-4 w-4 text-[var(--muted)]" />
                      <Input
                        className="pl-9"
                        value={query}
                        onChange={(event) => setQuery(event.target.value)}
                        placeholder="在 Zotero 中搜索标题、作者…"
                      />
                    </div>
                    <Button
                      variant="secondary"
                      type="submit"
                      disabled={searching}
                    >
                      {searching ? "搜索中…" : "搜索"}
                    </Button>
                  </form>
                  {collections.length > 0 && (
                    <div className="flex items-center gap-2 border-b border-[var(--border)] px-4 py-2 text-xs text-[var(--muted)]">
                      <FolderOpen className="h-3.5 w-3.5" />
                      已连接 {collections.length} 个 collection；可按 collection
                      检索。
                    </div>
                  )}
                  {catalogError && (
                    <ErrorState
                      message={catalogError}
                      onRetry={() =>
                        void loadCatalog(
                          catalogRetry.current.query,
                          catalogRetry.current.collectionKey,
                          catalogRetry.current.start,
                        )
                      }
                    />
                  )}
                  {searching && !catalog ? (
                    <LoadingState label="正在读取 Zotero 文献分页…" />
                  ) : items.length ? (
                    <div className="max-h-[640px] divide-y divide-[var(--border)] overflow-y-auto">
                      {items.map((item) => (
                        <button
                          key={item.key}
                          type="button"
                          disabled={searching}
                          onClick={() => void selectItem(item)}
                          className={`block w-full px-4 py-3 text-left hover:bg-[var(--surface-hover)] ${selected?.key === item.key ? "bg-[var(--accent)]/10" : ""}`}
                        >
                          <div className="line-clamp-2 text-sm font-medium">
                            {item.title}
                          </div>
                          <div className="mt-1 text-xs text-[var(--muted)]">
                            {item.creators.slice(0, 2).join(", ") || "作者未知"}{" "}
                            · {item.year ?? "年份未知"}
                          </div>
                        </button>
                      ))}
                    </div>
                  ) : (
                    <EmptyState
                      title="没有匹配的 Zotero 条目"
                      detail={
                        catalog?.next_start !== null &&
                        catalog?.next_start !== undefined
                          ? "当前来源页不含论文，可继续查看下一页。"
                          : "换一个关键词，或确认 Zotero 中有文献条目。"
                      }
                    />
                  )}
                  {catalog && (
                    <div className="space-y-2 border-t border-[var(--border)] px-4 py-3">
                      <p className="text-xs text-[var(--muted)]">
                        {catalog.raw_count > 0
                          ? `来源条目 ${catalog.start + 1}–${catalog.start + catalog.raw_count}`
                          : "本页无来源条目"}
                        {catalog.source_total === null
                          ? " · 来源总数未提供"
                          : ` / ${catalog.source_total} 个来源条目`}
                        。来源条目可能包含独立笔记，论文按页展示。
                      </p>
                      <div className="flex items-center justify-between gap-3">
                        <Button
                          size="sm"
                          variant="ghost"
                          disabled={searching || catalog.start === 0}
                          onClick={() =>
                            void loadCatalog(
                              catalogFilter.current.query,
                              catalogFilter.current.collectionKey,
                              Math.max(0, catalog.start - catalog.limit),
                            )
                          }
                        >
                          上一页文献
                        </Button>
                        <span className="text-xs text-[var(--muted)]">
                          {searching
                            ? "读取中…"
                            : `第 ${Math.floor(catalog.start / catalog.limit) + 1} 页`}
                        </span>
                        <Button
                          size="sm"
                          variant="ghost"
                          disabled={searching || catalog.next_start === null}
                          onClick={() => {
                            if (catalog.next_start === null) return;
                            void loadCatalog(
                              catalogFilter.current.query,
                              catalogFilter.current.collectionKey,
                              catalog.next_start,
                            );
                          }}
                        >
                          下一页文献
                        </Button>
                      </div>
                    </div>
                  )}
                </CardContent>
              </Card>
              <Card className="min-w-0">
                <CardHeader>
                  <div className="flex items-center gap-2">
                    <BookOpen className="h-4 w-4 text-[var(--accent)]" />
                    <h2 className="font-semibold">文献详情</h2>
                  </div>
                </CardHeader>
                <CardContent>
                  {selected ? (
                    <div className="space-y-5">
                      <div>
                        <div className="text-[11px] uppercase tracking-wider text-[var(--accent)]">
                          {selected.item_type} · {selected.key}
                        </div>
                        <h3 className="mt-2 text-lg font-semibold leading-7">
                          {selected.title}
                        </h3>
                        <p className="mt-2 text-xs text-[var(--muted)]">
                          {selected.creators.join(", ") || "作者未知"} ·{" "}
                          {selected.venue || "来源未知"} ·{" "}
                          {selected.year ?? "年份未知"}
                        </p>
                      </div>
                      {selected.abstract && (
                        <div>
                          <h4 className="mb-2 text-xs font-semibold">摘要</h4>
                          <p className="max-h-44 overflow-y-auto whitespace-pre-wrap text-sm leading-6 text-[var(--muted)]">
                            {selected.abstract}
                          </p>
                        </div>
                      )}
                      {selected.tags.length > 0 && (
                        <div className="flex flex-wrap gap-1.5">
                          {selected.tags.map((tag) => (
                            <span
                              key={tag}
                              className="rounded bg-[var(--surface-hover)] px-2 py-1 text-xs text-[var(--muted)]"
                            >
                              #{tag}
                            </span>
                          ))}
                        </div>
                      )}
                      <div className="space-y-3 border-t border-[var(--border)] pt-4">
                        <h4 className="text-sm font-semibold">
                          导入 ResearchOS
                        </h4>
                        <p className="text-xs leading-5 text-[var(--muted)]">
                          默认只导入元数据。可单独复制 PDF；原始 PDF
                          精读在论文工作区主动提交。
                        </p>
                        <label className="flex items-start gap-2 text-sm">
                          <input
                            type="checkbox"
                            checked={copyPdf}
                            onChange={(event) =>
                              setCopyPdf(event.target.checked)
                            }
                            className="mt-1 accent-[var(--accent)]"
                          />
                          <span>复制可访问的 PDF 到 ResearchOS</span>
                        </label>
                        <Button
                          onClick={() => void ingestItem()}
                          disabled={busy}
                        >
                          <Import className="h-4 w-4" />
                          {busy ? "提交中…" : "导入并处理"}
                        </Button>
                      </div>
                      <div className="border-t border-[var(--border)] pt-4">
                        <h4 className="mb-2 flex items-center gap-2 text-sm font-semibold">
                          <FileText className="h-4 w-4" />
                          附件与全文
                        </h4>
                        {attachments.length ? (
                          <div className="space-y-2">
                            {attachments.map((attachment) => (
                              <div
                                key={attachment.key}
                                className="rounded-md border border-[var(--border)] p-3"
                              >
                                <div className="truncate text-sm font-medium">
                                  {attachment.title}
                                </div>
                                <div className="mt-1 text-xs text-[var(--muted)]">
                                  {attachment.content_type || "类型未知"} ·{" "}
                                  {attachment.link_mode || ""}
                                </div>
                                {attachment.content_type ===
                                  "application/pdf" && (
                                  <div className="mt-3 flex flex-wrap gap-2">
                                    <a
                                      href={`/api/v1${base}/items/${selected.key}/attachments/${attachment.key}/content`}
                                      target="_blank"
                                      rel="noopener noreferrer"
                                      className="inline-flex h-8 items-center rounded-md border border-[var(--border)] px-2.5 text-xs hover:bg-[var(--surface-hover)]"
                                    >
                                      打开 PDF
                                    </a>
                                    <Button
                                      variant="ghost"
                                      size="sm"
                                      onClick={() =>
                                        void readFulltext(attachment.key)
                                      }
                                      disabled={busy}
                                    >
                                      查看已索引文本
                                    </Button>
                                  </div>
                                )}
                              </div>
                            ))}
                          </div>
                        ) : (
                          <p className="text-xs text-[var(--muted)]">
                            这条文献没有可用附件；仍可查看元数据并导入。
                          </p>
                        )}
                      </div>
                      {fulltext && (
                        <div className="rounded-lg border border-[var(--border)] bg-[var(--background)] p-4">
                          <h4 className="text-sm font-semibold">
                            Zotero 已索引文本
                          </h4>
                          <p className="mt-1 text-xs text-[var(--muted)]">
                            显示前 {fulltext.content.length} /{" "}
                            {fulltext.total_characters} 字符
                          </p>
                          <p className="mt-3 max-h-72 overflow-y-auto whitespace-pre-wrap text-xs leading-6">
                            {fulltext.content}
                          </p>
                        </div>
                      )}
                    </div>
                  ) : (
                    <EmptyState
                      title="选择一篇 Zotero 文献"
                      detail="左侧检索结果可查看摘要、附件和全文索引。"
                    />
                  )}
                </CardContent>
              </Card>
            </div>
            {error && <ErrorState message={error} />}
          </>
        )
      )}
    </div>
  );
}
