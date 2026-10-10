"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { MarkdownViewer } from "@/components/markdown/markdown-viewer";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input, Textarea } from "@/components/ui/input";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import { api, ApiError } from "@/lib/api";
import type { components } from "@/lib/generated";

type Selection = components["schemas"]["ServerTaskPackageSelection"];
type Options = components["schemas"]["ServerTaskPackageOptions"];
type Preview = components["schemas"]["ServerTaskPackagePreviewOut"];
type Package = components["schemas"]["ServerTaskPackageOut"];
type History = components["schemas"]["ServerTaskPackagePage"];
type Create = components["schemas"]["ServerTaskPackageCreateRequest"];
type Material = components["schemas"]["ServerPackageMaterialCreate"];
type Asset = components["schemas"]["ServerPackageAssetCreate"];
type ExpectedArtifact =
  components["schemas"]["ServerPackageExpectedArtifactCreate"];
type Task = components["schemas"]["ServerPackageTaskCreate"];
type Pending = { body: Create; owner: string; project: string };
const initial: Selection = {
  brief_id: "",
  archive_version_id: null,
  label: "",
  run_instructions: null,
  resource_limits: null,
  materials: [],
  assets: [],
  expected_artifacts: [],
  tasks: [],
};
const statuses = {
  SAVING: "正在保存",
  READY: "已保存",
  FAILED: "保存失败",
  NEEDS_ATTENTION: "保存结果待核查",
};
const note =
  "仅生成本地交接文件（LOCAL_ONLY）；执行授权为 false。包不会执行命令、调用 AI 或提交服务器。代码字节不在 ZIP 中，服务器需获取并核对固定私有版本；依赖、数据和资源均由本人声明，尚未经服务器验证。";
function message(cause: unknown) {
  return cause instanceof Error ? cause.message : "请求失败";
}
// Sample the clock only after an explicit detail request, never during render.
function inspectionTimestamp() {
  return Date.now();
}
function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="grid gap-1 text-sm">
      {label}
      {children}
    </label>
  );
}
function Files({ files }: { files: Preview["files"] }) {
  return (
    <div className="space-y-2">
      {files.map((file) => (
        <details
          key={file.path}
          className="rounded-md border border-[var(--border)] p-3"
        >
          <summary className="cursor-pointer break-all text-sm">
            {file.path} · {file.size_bytes} 字节 · {file.role}
          </summary>
          <p className="my-2 break-all text-xs text-[var(--muted)]">
            SHA-256：{file.sha256}
          </p>
          {file.path.endsWith(".md") ? (
            <MarkdownViewer content={file.content} label={file.path} />
          ) : (
            <pre className="markdown-raw">{file.content}</pre>
          )}
        </details>
      ))}
    </div>
  );
}

export default function ServerHandoffPage() {
  const { id } = useParams<{ id: string }>();
  const endpoint = `/projects/${id}/server-task-packages`;
  const [options, setOptions] = useState<Options | null>(null);
  const [selection, setSelection] = useState<Selection>(initial);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [history, setHistory] = useState<History | null>(null);
  const [detail, setDetail] = useState<Package | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [ackUnknown, setAckUnknown] = useState(false);
  const [abandon, setAbandon] = useState(false);
  const [inspectedAt, setInspectedAt] = useState(0);
  const key = options
    ? `researchos:server-package:${options.owner_id}:${id}`
    : null;

  const loadHistory = useCallback(
    async (cursor?: string) => {
      const value = await api.get<History>(
        `${endpoint}?limit=20${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`,
      );
      setHistory(value);
    },
    [endpoint],
  );
  const load = useCallback(async () => {
    try {
      const [opts, saved] = await Promise.all([
        api.get<Options>(`${endpoint}/options`),
        api.get<History>(`${endpoint}?limit=20`),
      ]);
      setOptions(opts);
      setHistory(saved);
      setError("");
      try {
        const raw = sessionStorage.getItem(
          `researchos:server-package:${opts.owner_id}:${id}`,
        );
        const recovered = raw ? (JSON.parse(raw) as Pending) : null;
        if (
          recovered &&
          recovered.owner === opts.owner_id &&
          recovered.project === id &&
          recovered.body?.approve_package === true &&
          typeof recovered.body.idempotency_key === "string" &&
          /^[0-9a-f]{64}$/.test(recovered.body.expected_preview_sha256) &&
          recovered.body.selection?.brief_id
        ) {
          setPending(recovered);
          setSelection(recovered.body.selection);
        }
      } catch {
        /* Current-page recovery stays available if browser storage is unavailable. */
      }
    } catch (cause) {
      setError(message(cause));
    } finally {
      setLoading(false);
    }
  }, [endpoint, id]);
  useEffect(() => {
    void Promise.resolve().then(load);
  }, [load]);

  function change(patch: Partial<Selection>) {
    setSelection((value) => ({ ...value, ...patch }));
    setPreview(null);
    setConfirmed(false);
  }
  async function loadMoreOptions(kind: "brief" | "archive") {
    if (!options) return;
    const cursor =
      kind === "brief"
        ? options.brief_page.next_cursor
        : options.archive_page.next_cursor;
    if (!cursor) return;
    setBusy(true);
    setError("");
    try {
      const next = await api.get<Options>(
        `${endpoint}/options?limit=20&${kind}_cursor=${encodeURIComponent(cursor)}`,
      );
      setOptions((current) => {
        if (!current) return next;
        if (kind === "brief")
          return {
            ...current,
            briefs: [
              ...current.briefs,
              ...next.briefs.filter(
                (item) => !current.briefs.some((old) => old.id === item.id),
              ),
            ],
            brief_page: next.brief_page,
          };
        return {
          ...current,
          archive_versions: [
            ...current.archive_versions,
            ...next.archive_versions.filter(
              (item) =>
                !current.archive_versions.some((old) => old.id === item.id),
            ),
          ],
          archive_page: next.archive_page,
        };
      });
    } catch (cause) {
      setError(message(cause));
    } finally {
      setBusy(false);
    }
  }
  function clearPending() {
    if (key) {
      try {
        sessionStorage.removeItem(key);
      } catch {
        /* Optional browser storage. */
      }
    }
    setPending(null);
    setAbandon(false);
  }
  async function makePreview() {
    setBusy(true);
    setError("");
    setPreview(null);
    setConfirmed(false);
    try {
      setPreview(await api.post<Preview>(`${endpoint}/preview`, selection));
    } catch (cause) {
      setError(message(cause));
    } finally {
      setBusy(false);
    }
  }
  async function save(request: Pending) {
    setPending(request);
    setBusy(true);
    setError("");
    if (key) {
      try {
        sessionStorage.setItem(key, JSON.stringify(request));
      } catch {
        /* Exact request is kept in memory. */
      }
    }
    try {
      const saved = await api.post<Package>(endpoint, request.body);
      setDetail(saved);
      setPreview(null);
      setConfirmed(false);
      clearPending();
      try {
        await loadHistory();
      } catch (cause) {
        setError(`已收到交接包记录，但历史刷新失败：${message(cause)}`);
      }
    } catch (cause) {
      // Only failures known to occur before any package/storage operation release the request.
      if (
        cause instanceof ApiError &&
        [
          "VALIDATION_ERROR",
          "SERVER_PACKAGE_APPROVAL_REQUIRED",
          "SERVER_PACKAGE_BRIEF_INELIGIBLE",
          "SERVER_PACKAGE_REVIEW_INVALID",
          "SERVER_PACKAGE_ARCHIVE_INVALID",
          "SERVER_PACKAGE_MATERIAL_INVALID",
          "SERVER_PACKAGE_RENDER_INVALID",
          "SERVER_PACKAGE_PREVIEW_CHANGED",
          "IDEMPOTENCY_CONFLICT",
          "SERVER_PACKAGE_CREATE_CONFLICT",
        ].includes(cause.code)
      ) {
        clearPending();
        setPreview(null);
        setConfirmed(false);
        setError(`${message(cause)}。请检查材料并重新预览。`);
      } else
        setError(
          `${message(cause)}。保存回执尚待核查；请读取历史或使用保留的同一请求恢复，勿重新生成请求。`,
        );
    } finally {
      setBusy(false);
    }
  }
  async function openPackage(packageId: string) {
    setBusy(true);
    setError("");
    setAckUnknown(false);
    try {
      setDetail(await api.get<Package>(`${endpoint}/${packageId}`));
      setInspectedAt(inspectionTimestamp());
    } catch (cause) {
      setError(message(cause));
    } finally {
      setBusy(false);
    }
  }
  async function retrySave() {
    if (!detail) return;
    setBusy(true);
    setError("");
    try {
      const saved = await api.post<Package>(
        `${endpoint}/${detail.id}/retry-save`,
        {
          expected_preview_sha256: detail.preview_sha256,
          acknowledge_unknown_save: ackUnknown,
        } satisfies components["schemas"]["ServerTaskPackageRetryRequest"],
      );
      setDetail(saved);
      setAckUnknown(false);
      await loadHistory();
    } catch (cause) {
      setError(`${message(cause)}。请刷新此包核查保存事实，不会自动重试。`);
    } finally {
      setBusy(false);
    }
  }
  if (loading) return <LoadingState label="正在加载服务器交接资料…" />;
  if (!options)
    return (
      <ErrorState
        message={error || "无法加载交接资料"}
        onRetry={() => void load()}
      />
    );
  const materials = selection.materials ?? [];
  const assets = selection.assets ?? [];
  const expected = selection.expected_artifacts ?? [];
  const tasks = selection.tasks ?? [];
  const lock = busy || !!pending;
  const latestAttempt = detail?.save_attempts.at(-1);
  const staleSaving =
    detail?.status === "SAVING" &&
    latestAttempt &&
    inspectedAt - Date.parse(latestAttempt.started_at) >= 5 * 60 * 1000;
  return (
    <div className="space-y-5">
      <Link href={`/projects/${id}`} className="text-sm text-[var(--accent)]">
        ← 返回课题
      </Link>
      <h1 className="text-xl font-semibold">
        {options.project_name} · 服务器交接
      </h1>
      <p
        className="rounded-md border border-[var(--border)] bg-[var(--surface)] p-4 text-sm"
        role="note"
      >
        {note}
      </p>
      {error && <ErrorState message={error} />}
      {pending && (
        <Card>
          <CardHeader>
            <h2 className="font-semibold">待核查的保存请求</h2>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-sm">
              刷新页面不会自动保存。同一请求编号：
              <code>{pending.body.idempotency_key}</code>；范围与预览 SHA
              已冻结。
            </p>
            <Button
              disabled={busy}
              onClick={() =>
                void loadHistory().catch((cause) => setError(message(cause)))
              }
            >
              读取最新历史
            </Button>{" "}
            <Button disabled={busy} onClick={() => void save(pending)}>
              用同一请求核查并恢复
            </Button>
            <label className="flex gap-2 text-sm">
              <input
                type="checkbox"
                checked={abandon}
                onChange={(event) => setAbandon(event.target.checked)}
              />
              我理解清除浏览器请求不会删除服务器上可能已保存的记录
            </label>
            <Button
              variant="ghost"
              disabled={busy || !abandon}
              onClick={clearPending}
            >
              仅清除浏览器待核查请求
            </Button>
          </CardContent>
        </Card>
      )}
      <Card>
        <CardHeader>
          <h2 className="font-semibold">交接内容</h2>
        </CardHeader>
        <CardContent>
          {!options.briefs.some((brief) => brief.eligible) && (
            <p className="mb-4 text-sm">
              没有当前有效且本人已接受的完整任务书。
              <Link
                className="text-[var(--accent)]"
                href={`/projects/${id}/brief`}
              >
                准备并审阅研究任务书 →
              </Link>
            </p>
          )}
          <fieldset disabled={lock} className="space-y-4">
            <div className="grid gap-4 md:grid-cols-2">
              <Field label="研究任务书">
                <select
                  className="rounded-md border border-[var(--border)] bg-[var(--background)] p-2"
                  value={selection.brief_id}
                  onChange={(event) => change({ brief_id: event.target.value })}
                >
                  <option value="">选择本人已接受的任务书</option>
                  {options.briefs.map((brief) => (
                    <option
                      key={brief.id}
                      value={brief.id}
                      disabled={!brief.eligible}
                    >
                      {brief.idea} · v{brief.revision}
                      {!brief.eligible ? "（未接受或来源已变化）" : ""}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="独立私有代码版本">
                <select
                  className="rounded-md border border-[var(--border)] bg-[var(--background)] p-2"
                  value={selection.archive_version_id ?? ""}
                  onChange={(event) =>
                    change({ archive_version_id: event.target.value || null })
                  }
                >
                  <option value="">未选择代码版本（交接包将记录缺口）</option>
                  {options.archive_versions.map((version) => (
                    <option key={version.id} value={version.id}>
                      {version.repository} · {version.tag} ·{" "}
                      {version.commit_sha.slice(0, 12)}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
            <p className="text-xs text-[var(--muted)]">
              <Link
                href={`/projects/${id}/archive`}
                className="text-[var(--accent)]"
              >
                管理私有版本 →
              </Link>{" "}
              历史登记与远端验证不证明当前服务器访问权限或复现成功。
            </p>
            <div className="flex flex-wrap gap-2">
              {options.brief_page.next_cursor && (
                <Button
                  variant="secondary"
                  disabled={lock}
                  onClick={() => void loadMoreOptions("brief")}
                >
                  加载更早任务书
                </Button>
              )}
              {options.archive_page.next_cursor && (
                <Button
                  variant="secondary"
                  disabled={lock}
                  onClick={() => void loadMoreOptions("archive")}
                >
                  加载更早私有版本
                </Button>
              )}
            </div>
            <Field label="交接包名称">
              <Input
                value={selection.label}
                maxLength={240}
                onChange={(event) => change({ label: event.target.value })}
              />
            </Field>
            <Field label="服务器运行说明（本人声明）">
              <Textarea
                value={selection.run_instructions ?? ""}
                maxLength={50000}
                placeholder="填写服务器操作步骤、核对方法与停止条件；平台不会执行这些文字。"
                onChange={(event) =>
                  change({ run_instructions: event.target.value || null })
                }
              />
            </Field>
            <Field label="资源限制与停止规则">
              <Textarea
                value={selection.resource_limits ?? ""}
                maxLength={10000}
                placeholder="按实际课题填写 GPU / 时限 / 存储 / 停止规则，未知项保留待决定。"
                onChange={(event) =>
                  change({ resource_limits: event.target.value || null })
                }
              />
            </Field>
            <details open={materials.length > 0}>
              <summary className="cursor-pointer font-medium">
                依赖与配置材料 · {materials.length}
              </summary>
              <div className="mt-3 space-y-3">
                {materials.map((item, index) => (
                  <div
                    key={index}
                    className="space-y-2 rounded border border-[var(--border)] p-3"
                  >
                    <Field label={`材料 ${index + 1} 路径`}>
                      <Input
                        value={item.path}
                        placeholder="例如 requirements.txt 或 config/train.yaml（只填相对路径）"
                        onChange={(event) =>
                          change({
                            materials: materials.map((value, i) =>
                              i === index
                                ? { ...value, path: event.target.value }
                                : value,
                            ),
                          })
                        }
                      />
                    </Field>
                    <Field label={`材料 ${index + 1} 类型`}>
                      <select
                        value={item.role}
                        className="rounded border border-[var(--border)] bg-[var(--background)] p-2"
                        onChange={(event) =>
                          change({
                            materials: materials.map((value, i) =>
                              i === index
                                ? {
                                    ...value,
                                    role: event.target
                                      .value as Material["role"],
                                  }
                                : value,
                            ),
                          })
                        }
                      >
                        {[
                          "DEPENDENCIES",
                          "CONFIG",
                          "ENVIRONMENT",
                          "DOCUMENTATION",
                        ].map((role) => (
                          <option key={role}>{role}</option>
                        ))}
                      </select>
                    </Field>
                    <Field label={`材料 ${index + 1} 内容`}>
                      <Textarea
                        value={item.content}
                        maxLength={100000}
                        onChange={(event) =>
                          change({
                            materials: materials.map((value, i) =>
                              i === index
                                ? { ...value, content: event.target.value }
                                : value,
                            ),
                          })
                        }
                      />
                    </Field>
                    <Button
                      variant="ghost"
                      onClick={() =>
                        change({
                          materials: materials.filter((_, i) => i !== index),
                        })
                      }
                    >
                      移除材料 {index + 1}
                    </Button>
                  </div>
                ))}
                <Button
                  variant="secondary"
                  disabled={lock || materials.length >= 20}
                  onClick={() =>
                    change({
                      materials: [
                        ...materials,
                        { path: "", content: "", role: "DEPENDENCIES" },
                      ],
                    })
                  }
                >
                  添加材料
                </Button>
              </div>
            </details>
            <details open={assets.length > 0}>
              <summary className="cursor-pointer font-medium">
                数据与模型引用 · {assets.length}
              </summary>
              <div className="mt-3 space-y-3">
                {assets.map((item, index) => (
                  <div
                    key={index}
                    className="grid gap-2 rounded border border-[var(--border)] p-3 md:grid-cols-2"
                  >
                    <Field label={`资产 ${index + 1} 类型`}>
                      <select
                        value={item.kind}
                        className="rounded border border-[var(--border)] bg-[var(--background)] p-2"
                        onChange={(event) =>
                          change({
                            assets: assets.map((value, i) =>
                              i === index
                                ? {
                                    ...value,
                                    kind: event.target.value as Asset["kind"],
                                  }
                                : value,
                            ),
                          })
                        }
                      >
                        {["DATASET", "MODEL", "OTHER"].map((kind) => (
                          <option key={kind}>{kind}</option>
                        ))}
                      </select>
                    </Field>
                    {(
                      [
                        "label",
                        "location",
                        "version",
                        "sha256",
                        "license_note",
                      ] as const
                    ).map((field) => (
                      <Field
                        key={field}
                        label={`资产 ${index + 1} ${{ label: "名称", location: "位置或来源", version: "版本", sha256: "SHA-256（已知时填写）", license_note: "许可与访问说明" }[field]}`}
                      >
                        <Input
                          value={item[field] ?? ""}
                          onChange={(event) =>
                            change({
                              assets: assets.map((value, i) =>
                                i === index
                                  ? {
                                      ...value,
                                      [field]:
                                        event.target.value ||
                                        (field === "label" ||
                                        field === "location"
                                          ? ""
                                          : null),
                                    }
                                  : value,
                              ),
                            })
                          }
                        />
                      </Field>
                    ))}
                    <Button
                      variant="ghost"
                      onClick={() =>
                        change({ assets: assets.filter((_, i) => i !== index) })
                      }
                    >
                      移除资产 {index + 1}
                    </Button>
                  </div>
                ))}
                <Button
                  variant="secondary"
                  disabled={lock || assets.length >= 30}
                  onClick={() =>
                    change({
                      assets: [
                        ...assets,
                        {
                          kind: "DATASET",
                          label: "",
                          location: "",
                          version: null,
                          sha256: null,
                          license_note: null,
                        },
                      ],
                    })
                  }
                >
                  添加资产引用
                </Button>
              </div>
            </details>
            <details open={expected.length > 0}>
              <summary className="cursor-pointer font-medium">
                预期产物 · {expected.length}
              </summary>
              <div className="mt-3 space-y-3">
                {expected.map((item, index) => (
                  <div
                    key={index}
                    className="space-y-2 rounded border border-[var(--border)] p-3"
                  >
                    {(["path", "description"] as const).map((field) => (
                      <Field
                        key={field}
                        label={`产物 ${index + 1} ${field === "path" ? "路径" : "说明"}`}
                      >
                        <Input
                          value={item[field]}
                          onChange={(event) =>
                            change({
                              expected_artifacts: expected.map((value, i) =>
                                i === index
                                  ? { ...value, [field]: event.target.value }
                                  : value,
                              ),
                            })
                          }
                        />
                      </Field>
                    ))}
                    <Button
                      variant="ghost"
                      onClick={() =>
                        change({
                          expected_artifacts: expected.filter(
                            (_, i) => i !== index,
                          ),
                        })
                      }
                    >
                      移除产物 {index + 1}
                    </Button>
                  </div>
                ))}
                <Button
                  variant="secondary"
                  disabled={lock || expected.length >= 30}
                  onClick={() =>
                    change({
                      expected_artifacts: [
                        ...expected,
                        {
                          path: "",
                          description: "",
                        } satisfies ExpectedArtifact,
                      ],
                    })
                  }
                >
                  添加预期产物
                </Button>
              </div>
            </details>
            <details open={tasks.length > 0}>
              <summary className="cursor-pointer font-medium">
                保存成功后创建的科研任务 · {tasks.length}
              </summary>
              <div className="mt-3 space-y-3">
                {tasks.map((item, index) => (
                  <div
                    key={index}
                    className="grid gap-2 rounded border border-[var(--border)] p-3 md:grid-cols-2"
                  >
                    <Field label={`任务 ${index + 1} 标题`}>
                      <Input
                        value={item.title}
                        onChange={(event) =>
                          change({
                            tasks: tasks.map((value, i) =>
                              i === index
                                ? { ...value, title: event.target.value }
                                : value,
                            ),
                          })
                        }
                      />
                    </Field>
                    <Field label={`任务 ${index + 1} 说明`}>
                      <Textarea
                        value={item.description ?? ""}
                        onChange={(event) =>
                          change({
                            tasks: tasks.map((value, i) =>
                              i === index
                                ? {
                                    ...value,
                                    description: event.target.value || null,
                                  }
                                : value,
                            ),
                          })
                        }
                      />
                    </Field>
                    <Field label={`任务 ${index + 1} 类别`}>
                      <select
                        value={item.category ?? "research"}
                        className="rounded border border-[var(--border)] bg-[var(--background)] p-2"
                        onChange={(event) =>
                          change({
                            tasks: tasks.map((value, i) =>
                              i === index
                                ? {
                                    ...value,
                                    category: event.target
                                      .value as Task["category"],
                                  }
                                : value,
                            ),
                          })
                        }
                      >
                        {[
                          "reading",
                          "learning",
                          "coding",
                          "experiment",
                          "dataset",
                          "writing",
                          "meeting",
                          "research",
                          "other",
                        ].map((category) => (
                          <option key={category}>{category}</option>
                        ))}
                      </select>
                    </Field>
                    <Field label={`任务 ${index + 1} 优先级`}>
                      <select
                        value={item.priority ?? "medium"}
                        className="rounded border border-[var(--border)] bg-[var(--background)] p-2"
                        onChange={(event) =>
                          change({
                            tasks: tasks.map((value, i) =>
                              i === index
                                ? {
                                    ...value,
                                    priority: event.target
                                      .value as Task["priority"],
                                  }
                                : value,
                            ),
                          })
                        }
                      >
                        {["low", "medium", "high", "urgent"].map((priority) => (
                          <option key={priority}>{priority}</option>
                        ))}
                      </select>
                    </Field>
                    <Button
                      variant="ghost"
                      onClick={() =>
                        change({ tasks: tasks.filter((_, i) => i !== index) })
                      }
                    >
                      移除任务 {index + 1}
                    </Button>
                  </div>
                ))}
                <Button
                  variant="secondary"
                  disabled={lock || tasks.length >= 20}
                  onClick={() =>
                    change({
                      tasks: [
                        ...tasks,
                        {
                          title: "",
                          description: null,
                          category: "research",
                          priority: "medium",
                        },
                      ],
                    })
                  }
                >
                  添加科研任务
                </Button>
              </div>
            </details>
            <Button
              disabled={lock || !selection.brief_id || !selection.label.trim()}
              onClick={() => void makePreview()}
            >
              预览交接包
            </Button>
          </fieldset>
        </CardContent>
      </Card>
      {preview && (
        <Card>
          <CardHeader>
            <h2 className="font-semibold">批准前文件预览</h2>
          </CardHeader>
          <CardContent className="space-y-3">
            <p>
              {preview.readiness === "INCOMPLETE"
                ? "材料不完整 · INCOMPLETE"
                : "待服务器审阅 · READY_FOR_SERVER_REVIEW"}{" "}
              · {preview.bundle_size_bytes} 字节
            </p>
            <p className="break-all text-xs">
              来源 SHA：{preview.source_sha256}
              <br />
              预览 SHA：{preview.preview_sha256}
              <br />
              ZIP SHA：{preview.bundle_sha256}
            </p>
            {preview.gaps.length > 0 && (
              <div className="rounded border border-amber-500 p-3">
                <h3 className="font-medium">待补充缺口</h3>
                <ul className="list-inside list-disc text-sm">
                  {preview.gaps.map((gap) => (
                    <li key={gap}>{gap}</li>
                  ))}
                </ul>
              </div>
            )}
            <Files files={preview.files} />
            <label className="flex gap-2 text-sm">
              <input
                type="checkbox"
                checked={confirmed}
                onChange={(event) => setConfirmed(event.target.checked)}
                disabled={lock}
              />
              我已核对文件和缺口，批准本地保存交接包及所选任务；此批准不授权服务器执行
            </label>
            <Button
              disabled={lock || !confirmed}
              onClick={() =>
                void save({
                  owner: options.owner_id,
                  project: id,
                  body: {
                    selection: preview.selection,
                    expected_preview_sha256: preview.preview_sha256,
                    approve_package: true,
                    idempotency_key: crypto.randomUUID(),
                  },
                })
              }
            >
              批准并保存交接包
            </Button>
          </CardContent>
        </Card>
      )}
      <Card>
        <CardHeader>
          <h2 className="font-semibold">已保存的交接记录</h2>
          <Button
            size="sm"
            variant="ghost"
            disabled={busy}
            onClick={() =>
              void loadHistory().catch((cause) => setError(message(cause)))
            }
          >
            刷新历史
          </Button>
        </CardHeader>
        <CardContent className="space-y-3">
          {history?.items.length ? (
            <ul className="space-y-2">
              {history.items.map((item) => (
                <li key={item.id}>
                  <Button
                    variant="ghost"
                    disabled={busy}
                    onClick={() => void openPackage(item.id)}
                  >
                    {item.label} · {statuses[item.status]} · {item.readiness}
                  </Button>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState
              title="尚无交接包"
              detail="预览并批准后，实际保存事实会出现在此处。"
            />
          )}
          {history?.page.next_cursor && (
            <Button
              variant="secondary"
              disabled={busy}
              onClick={() =>
                void loadHistory(history.page.next_cursor ?? undefined).catch(
                  (cause) => setError(message(cause)),
                )
              }
            >
              下一页交接记录
            </Button>
          )}
          {detail && (
            <section
              aria-label="交接包详情"
              className="space-y-3 border-t border-[var(--border)] pt-4"
            >
              <h3 className="font-medium">
                {detail.label} · {statuses[detail.status]}
              </h3>
              <p className="text-sm">
                {detail.readiness} · {detail.bundle_size_bytes} 字节 ·
                LOCAL_ONLY
              </p>
              <p className="break-all text-xs">
                来源 SHA：{detail.source_sha256}
                <br />
                预览 SHA：{detail.preview_sha256}
                <br />
                ZIP SHA：{detail.bundle_sha256}
              </p>
              {detail.error_message && (
                <p role="alert" className="text-[var(--danger)]">
                  {detail.error_code}：{detail.error_message}
                </p>
              )}
              {detail.gaps.length > 0 && (
                <ul className="list-inside list-disc text-sm">
                  {detail.gaps.map((gap) => (
                    <li key={gap}>{gap}</li>
                  ))}
                </ul>
              )}
              {detail.status === "READY" && detail.attachment_id && (
                <div className="flex flex-wrap gap-4">
                  <a
                    className="text-sm text-[var(--accent)] underline"
                    href={`/api/v1${endpoint}/${detail.id}/download`}
                  >
                    下载实际交接 ZIP
                  </a>
                  <Link
                    className="text-sm text-[var(--accent)] underline"
                    href={`/projects/${id}/results?package=${detail.id}`}
                  >
                    回传结果 →
                  </Link>
                </div>
              )}
              <Files files={detail.files} />
              <h4 className="font-medium">关联任务</h4>
              {detail.tasks.length ? (
                <ul className="text-sm">
                  {detail.tasks.map((task, index) => (
                    <li key={index}>
                      {task.title} ·{" "}
                      {task.task_id ? (
                        <>
                          已创建任务 <code>{task.task_id}</code>
                        </>
                      ) : (
                        "仅为待创建规格，尚无任务记录"
                      )}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-[var(--muted)]">
                  本包未选择创建任务。
                </p>
              )}
              {(detail.status === "FAILED" ||
                detail.status === "NEEDS_ATTENTION" ||
                staleSaving) && (
                <div className="space-y-2 rounded border border-amber-500 p-3">
                  <p className="text-sm">
                    恢复仅保存本包已冻结的文件，不重新调用 AI
                    或执行服务器命令；失败来源需先重新核查。
                  </p>
                  {(detail.status === "NEEDS_ATTENTION" || staleSaving) && (
                    <label className="flex gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={ackUnknown}
                        onChange={(event) =>
                          setAckUnknown(event.target.checked)
                        }
                      />
                      我已核查未知保存结果，明确允许再次保存同一冻结文件
                    </label>
                  )}
                  <Button
                    disabled={
                      busy ||
                      ((detail.status === "NEEDS_ATTENTION" || !!staleSaving) &&
                        !ackUnknown)
                    }
                    onClick={() => void retrySave()}
                  >
                    恢复冻结文件保存
                  </Button>
                </div>
              )}
              {detail.status === "SAVING" && (
                <p className="text-sm text-[var(--muted)]">
                  保存结果尚待核查，等待不证明进程停止。最新尝试满 5
                  分钟后刷新此包，可本人明确确认并恢复冻结文件保存；服务器会再次校验恢复条件。
                </p>
              )}
              <details>
                <summary className="cursor-pointer text-sm">
                  保存尝试记录
                </summary>
                <ul className="text-xs">
                  {detail.save_attempts.map((attempt) => (
                    <li key={attempt.id}>
                      第 {attempt.attempt_number} 次 · {attempt.status} ·{" "}
                      {attempt.error_code ?? "无错误码"}
                    </li>
                  ))}
                </ul>
              </details>
              <Button
                variant="ghost"
                disabled={busy}
                onClick={() => void openPackage(detail.id)}
              >
                刷新此包
              </Button>
            </section>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
