"use client";

import { useEffect, useRef, useState } from "react";
import type { PDFDocumentProxy } from "pdfjs-dist";
import { api, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  ContinuousPages,
  type ContinuousPagesHandle,
} from "./continuous-pages";
import {
  sameAnnotation,
  type AnnotationCollection,
  type AnnotationGeometry,
  type AnnotationKind,
  type AnnotationWrite,
  type PdfAnnotation,
} from "./types";

type Pending = { id: string; write: AnnotationWrite; deleting?: boolean };
const names: Record<AnnotationKind, string> = {
  HIGHLIGHT: "高亮",
  UNDERLINE: "下划线",
  COMMENT: "批注",
  INK: "画线",
};

export function PdfAnnotationReader({
  paperId,
  attachmentId,
  sourceSha256,
  filename,
  onUnsavedChange,
}: {
  paperId: string;
  attachmentId: string;
  sourceSha256?: string | null;
  filename?: string;
  onUnsavedChange?: (value: boolean) => void;
}) {
  return (
    <Reader
      key={`${paperId}:${attachmentId}:${sourceSha256 ?? ""}`}
      paperId={paperId}
      attachmentId={attachmentId}
      sourceSha256={sourceSha256}
      filename={filename}
      onUnsavedChange={onUnsavedChange}
    />
  );
}

function Reader({
  paperId,
  attachmentId,
  sourceSha256,
  filename,
  onUnsavedChange,
}: {
  paperId: string;
  attachmentId: string;
  sourceSha256?: string | null;
  filename?: string;
  onUnsavedChange?: (value: boolean) => void;
}) {
  const path = `/papers/${encodeURIComponent(paperId)}/attachments/${encodeURIComponent(attachmentId)}`;
  const [collection, setCollection] = useState<AnnotationCollection | null>(
    null,
  );
  const [document, setDocument] = useState<PDFDocumentProxy | null>(null);
  const [page, setPage] = useState(1);
  const [zoom, setZoom] = useState(1);
  const [tool, setTool] = useState<AnnotationKind | "READ">("READ");
  const [color, setColor] = useState("#ffcc00");
  const [selected, setSelected] = useState<PdfAnnotation | null>(null);
  const [draft, setDraft] = useState<PdfAnnotation | null>(null);
  const [drawing, setDrawing] = useState<AnnotationGeometry | null>(null);
  const [drawingPage, setDrawingPage] = useState<number | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [safeRetry, setSafeRetry] = useState(false);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState("正在加载原文和标记…");
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  const gesture = useRef<{
    page: number;
    kind: AnnotationKind;
    color: string;
    start: { x: number; y: number };
    points: { x: number; y: number }[];
  } | null>(null);
  const busy = useRef(false);
  const continuous = useRef<ContinuousPagesHandle>(null);
  const unsaved = pending !== null || draft !== null || saving;
  useEffect(() => {
    onUnsavedChange?.(unsaved);
  }, [unsaved, onUnsavedChange]);
  useEffect(() => {
    if (!unsaved) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
    };
    const preventNavigation = (event: MouseEvent) => {
      const target = event.target;
      const anchor =
        target instanceof Element ? target.closest("a[href]") : null;
      if (
        anchor &&
        !anchor.hasAttribute("download") &&
        anchor.getAttribute("target") !== "_blank"
      ) {
        event.preventDefault();
        event.stopPropagation();
        setError("仍有未保存的 PDF 标记，请先保存或核查结果后再离开。");
      }
    };
    window.addEventListener("beforeunload", warn);
    window.document.addEventListener("click", preventNavigation, true);
    return () => {
      window.removeEventListener("beforeunload", warn);
      window.document.removeEventListener("click", preventNavigation, true);
    };
  }, [unsaved]);

  useEffect(() => {
    let cancelled = false;
    let loading:
      ReturnType<(typeof import("pdfjs-dist"))["getDocument"]> | undefined;
    queueMicrotask(() => {
      if (!cancelled) {
        setError("");
        setDocument(null);
        setCollection(null);
      }
    });
    void (async () => {
      const marks = await api.get<AnnotationCollection>(`${path}/annotations`);
      if (
        marks.attachment_id !== attachmentId ||
        (sourceSha256 && marks.source_sha256 !== sourceSha256)
      )
        throw new Error("原 PDF 版本已变化，请刷新论文后重新打开。");
      if (
        marks.annotations.some(
          (item) =>
            item.attachment_id !== attachmentId ||
            item.source_sha256 !== marks.source_sha256 ||
            item.deleted_at !== null ||
            item.page < 1 ||
            item.page > marks.page_count,
        )
      )
        throw new Error("标记来源或页码与本 PDF 不一致，已停止显示和编辑。");
      const pdfjs = await import("pdfjs-dist");
      pdfjs.GlobalWorkerOptions.workerSrc =
        "/pdfjs/pdf.worker.min.mjs?v=6.4.299";
      if (cancelled) return;
      setStatus("正在读取并核对原 PDF…");
      const response = await fetch(
        `/api/v1/attachments/${encodeURIComponent(attachmentId)}/download`,
        { credentials: "same-origin", cache: "no-store" },
      );
      if (!response.ok || !response.body)
        throw new Error(`PDF 下载失败 (${response.status})`);
      const limit = 64 * 1024 * 1024;
      if (Number(response.headers.get("content-length")) > limit)
        throw new Error("PDF 超过 64 MiB 阅读上限，请在原文阅读器打开。");
      const stream = response.body.getReader();
      const chunks: Uint8Array[] = [];
      let length = 0;
      try {
        while (true) {
          const result = await stream.read();
          if (result.done) break;
          length += result.value.length;
          if (length > limit || cancelled) {
            await stream.cancel();
            throw new Error("PDF 过大或读取已取消");
          }
          chunks.push(result.value);
        }
      } finally {
        stream.releaseLock();
      }
      const bytes = new Uint8Array(length);
      let offset = 0;
      for (const chunk of chunks) {
        bytes.set(chunk, offset);
        offset += chunk.length;
      }
      const digest = Array.from(
        new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)),
        (value) => value.toString(16).padStart(2, "0"),
      ).join("");
      if (digest !== marks.source_sha256)
        throw new Error("下载的 PDF 哈希与对应原文不一致，已停止显示和标记。");
      if (cancelled) return;
      loading = pdfjs.getDocument({
        data: bytes,
        stopAtErrors: true,
        cMapUrl: "/pdfjs/cmaps/",
        cMapPacked: true,
        standardFontDataUrl: "/pdfjs/standard_fonts/",
        wasmUrl: "/pdfjs/wasm/",
      });
      const pdf = await loading.promise;
      if (cancelled) return;
      if (pdf.numPages !== marks.page_count)
        throw new Error("原文页数与标记版本不一致，已停止编辑。");
      setCollection(marks);
      setDocument(pdf);
      setStatus("标记已同步");
    })().catch((cause: unknown) => {
      if (!cancelled) setError(message(cause));
    });
    return () => {
      cancelled = true;
      void loading?.destroy();
    };
  }, [attachmentId, sourceSha256, path, reload]);

  function accept(receipt: PdfAnnotation, operation: Pending) {
    if (
      receipt.id !== operation.id ||
      receipt.attachment_id !== attachmentId ||
      receipt.source_sha256 !== operation.write.source_sha256 ||
      receipt.revision !== operation.write.expected_revision + 1 ||
      (operation.deleting
        ? !receipt.deleted_at
        : receipt.deleted_at !== null ||
          !sameAnnotation(receipt, operation.write))
    )
      throw new Error("保存回执与本次标记不一致，请核查。");
    setCollection(
      (current) =>
        current && {
          ...current,
          annotations: receipt.deleted_at
            ? current.annotations.filter((item) => item.id !== receipt.id)
            : [
                ...current.annotations.filter((item) => item.id !== receipt.id),
                receipt,
              ],
        },
    );
    setPending(null);
    setSafeRetry(false);
    setDraft(null);
    setSelected(receipt.deleted_at ? null : receipt);
    setError("");
    setStatus(operation.deleting ? "标记已删除" : "已保存到对应 PDF");
  }
  async function check(operation: Pending) {
    if (busy.current) return;
    busy.current = true;
    setSaving(true);
    setStatus("正在核查保存结果…");
    try {
      const receipt = await api.get<PdfAnnotation>(
        `${path}/annotations/${operation.id}`,
      );
      if (
        receipt.attachment_id === attachmentId &&
        receipt.source_sha256 === operation.write.source_sha256 &&
        receipt.revision === operation.write.expected_revision &&
        !receipt.deleted_at
      ) {
        setSafeRetry(true);
        setStatus("本次修改尚未保存，可重试");
        setError(
          "只读核查确认原版本未变化，重试仍会检查版本，避免覆盖其他修改。",
        );
      } else accept(receipt, operation);
    } catch (cause) {
      if (
        cause instanceof ApiError &&
        cause.status === 404 &&
        operation.write.expected_revision === 0 &&
        !operation.deleting
      ) {
        setSafeRetry(true);
        setStatus("本次标记尚未保存，可重试");
        setError("只读核查确认此标记尚未创建。");
      } else {
        setSafeRetry(false);
        setError(
          `尚未确认保存结果：${message(cause)}。请保留页面，核查后再重试。`,
        );
        setStatus("尚未确认保存");
      }
    } finally {
      busy.current = false;
      setSaving(false);
    }
  }
  async function writeMark(item: PdfAnnotation, deleting = false) {
    if (!collection || busy.current) return;
    const operation: Pending = {
      id: item.id,
      deleting,
      write: {
        expected_revision: item.revision,
        source_sha256: collection.source_sha256,
        kind: item.kind,
        page: item.page,
        color: item.color,
        body: item.body,
        geometries: item.geometries,
      },
    };
    setPending(operation);
    setSafeRetry(false);
    busy.current = true;
    setSaving(true);
    setError("");
    setStatus("正在保存…");
    try {
      const receipt = deleting
        ? await api
            .delete(
              `${path}/annotations/${item.id}?expected_revision=${item.revision}&source_sha256=${collection.source_sha256}`,
            )
            .then(() =>
              api.get<PdfAnnotation>(`${path}/annotations/${item.id}`),
            )
        : await api.put<PdfAnnotation>(
            `${path}/annotations/${item.id}`,
            operation.write,
          );
      accept(receipt, operation);
    } catch (cause) {
      // A lost response is not permission to submit the same write again.
      setError(
        `保存尚未确认：${message(cause)}。点击「核查保存结果」先只读核对。`,
      );
      setStatus("尚未确认保存");
    } finally {
      busy.current = false;
      setSaving(false);
    }
  }
  const point = (event: React.PointerEvent<SVGSVGElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    return {
      x: Math.min(1, Math.max(0, (event.clientX - box.left) / box.width)),
      y: Math.min(1, Math.max(0, (event.clientY - box.top) / box.height)),
    };
  };
  function begin(
    event: React.PointerEvent<SVGSVGElement>,
    physicalPage: number,
  ) {
    if (tool === "READ" || pending || draft || saving || !collection) return;
    const start = point(event);
    gesture.current = {
      start,
      points: [start],
      page: physicalPage,
      kind: tool,
      color,
    };
    setDrawingPage(physicalPage);
    setPage(physicalPage);
    event.currentTarget.setPointerCapture(event.pointerId);
    setSelected(null);
  }
  function move(event: React.PointerEvent<SVGSVGElement>) {
    if (!gesture.current) return;
    const end = point(event);
    if (gesture.current.kind === "INK" && gesture.current.points.length < 1900)
      gesture.current.points.push(end);
    setDrawing(
      geometry(
        gesture.current.start,
        end,
        gesture.current.kind,
        gesture.current.points,
      ),
    );
  }
  function finish(event: React.PointerEvent<SVGSVGElement>) {
    const active = gesture.current;
    gesture.current = null;
    setDrawing(null);
    setDrawingPage(null);
    if (!active || !collection) return;
    const end = point(event);
    const shape = geometry(active.start, end, active.kind, [
      ...active.points,
      end,
    ]);
    const travelled = [...active.points, end].reduce(
      (total, value, index, points) =>
        index === 0
          ? 0
          : total +
            Math.hypot(
              value.x - points[index - 1].x,
              value.y - points[index - 1].y,
            ),
      0,
    );
    if (
      active.kind === "INK"
        ? travelled < 0.003
        : active.kind !== "COMMENT" &&
          Math.abs(active.start.x - end.x) + Math.abs(active.start.y - end.y) <
            0.003
    )
      return;
    const item: PdfAnnotation = {
      id: crypto.randomUUID(),
      attachment_id: attachmentId,
      revision: 0,
      source_sha256: collection.source_sha256,
      deleted_at: null,
      kind: active.kind,
      color: active.color,
      body: "",
      page: active.page,
      geometries: [shape],
    };
    if (active.kind === "COMMENT") {
      setDraft(item);
      setStatus("填写批注后保存");
    } else void writeMark(item);
  }
  const shown =
    collection?.annotations.filter((item) => item.page === page) ?? [];
  function jump(target: number) {
    if (unsaved) return;
    const next = Math.max(1, Math.min(document?.numPages ?? 1, target));
    continuous.current?.scrollToPage(next);
  }
  function keyboard(event: React.KeyboardEvent<HTMLDivElement>) {
    if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey)
      return;
    if (
      event.target instanceof Element &&
      event.target.closest(
        "input,textarea,select,button,a,[contenteditable='true']",
      )
    )
      return;
    if (!["PageDown", "PageUp", "ArrowRight", "ArrowLeft"].includes(event.key))
      return;
    event.preventDefault();
    if (unsaved) {
      setStatus("请先保存或核查批注；鼠标滚轮仍可继续阅读，未保存页保留。");
      return;
    }
    jump(page + (["PageDown", "ArrowRight"].includes(event.key) ? 1 : -1));
  }
  return (
    <section
      className="pdf-annotation-reader space-y-3"
      aria-label="原 PDF 标记阅读器"
    >
      <div
        className="flex flex-wrap items-center gap-2"
        role="toolbar"
        aria-label="PDF 阅读和标记工具"
      >
        <Button
          variant="secondary"
          disabled={page <= 1 || unsaved}
          onClick={() => jump(page - 1)}
        >
          上一页
        </Button>
        <label>
          第{" "}
          <input
            aria-label="PDF 页码"
            className="w-16 rounded border p-1 text-center"
            type="number"
            min={1}
            max={document?.numPages ?? 1}
            value={page}
            disabled={unsaved || !document}
            onChange={(event) =>
              jump(
                Math.max(
                  1,
                  Math.min(
                    document?.numPages ?? 1,
                    Number(event.target.value) || 1,
                  ),
                ),
              )
            }
          />{" "}
          / {document?.numPages ?? "—"} 页
        </label>
        <Button
          variant="secondary"
          disabled={!document || page >= document.numPages || unsaved}
          onClick={() => jump(page + 1)}
        >
          下一页
        </Button>
        <label>
          缩放{" "}
          <select
            aria-label="PDF 缩放"
            value={zoom}
            disabled={unsaved}
            onChange={(event) => setZoom(Number(event.target.value))}
          >
            {[0.75, 1, 1.25, 1.5, 2].map((value) => (
              <option key={value} value={value}>
                {Math.round(value * 100)}%
              </option>
            ))}
          </select>
        </label>
        <Button
          variant={tool === "READ" ? "default" : "secondary"}
          aria-pressed={tool === "READ"}
          onClick={() => setTool("READ")}
          disabled={unsaved}
        >
          阅读
        </Button>
        {(Object.keys(names) as AnnotationKind[]).map((kind) => (
          <Button
            key={kind}
            variant={tool === kind ? "default" : "secondary"}
            aria-pressed={tool === kind}
            disabled={unsaved || !document}
            onClick={() => setTool(kind)}
          >
            {names[kind]}
          </Button>
        ))}
        <label>
          标记颜色{" "}
          <input
            type="color"
            aria-label="标记颜色"
            value={color}
            onChange={(event) => setColor(event.target.value)}
          />
        </label>
        <a
          className="underline"
          href={`/api/v1${path}/annotated-pdf`}
          download={filename ? `带标记-${filename}` : undefined}
        >
          下载带标记 PDF
        </a>
      </div>
      <p role="status" aria-live="polite">
        {status}
      </p>
      {tool !== "READ" && (
        <p className="text-sm">
          在原文上拖动以添加{names[tool]}
          ；批注也可以点击位置。仅显示“已保存”后可安全离开。
        </p>
      )}
      {error && (
        <div role="alert" className="space-y-2">
          <p>{error}</p>
          {pending ? (
            <>
              <Button
                variant="secondary"
                disabled={saving}
                onClick={() => void check(pending)}
              >
                核查保存结果
              </Button>
              {safeRetry && (
                <Button
                  disabled={saving}
                  onClick={() =>
                    void writeMark(
                      {
                        id: pending.id,
                        attachment_id: attachmentId,
                        revision: pending.write.expected_revision,
                        deleted_at: null,
                        ...pending.write,
                      },
                      pending.deleting,
                    )
                  }
                >
                  重试保存
                </Button>
              )}
            </>
          ) : (
            <Button variant="secondary" onClick={() => setReload(reload + 1)}>
              重新加载 PDF 和标记
            </Button>
          )}
        </div>
      )}
      {document && (
        <ContinuousPages
          ref={continuous}
          document={document}
          zoom={zoom}
          activePage={page}
          onActivePage={setPage}
          pinnedPage={
            draft?.page ?? pending?.write.page ?? drawingPage ?? undefined
          }
          onKeyDown={keyboard}
        >
          {(physicalPage) => (
            <svg
              data-testid="pdf-annotation-overlay"
              data-page={physicalPage}
              className="absolute inset-0 h-full w-full"
              viewBox="0 0 1000 1000"
              preserveAspectRatio="none"
              aria-label={`第 ${physicalPage} 页标记层`}
              style={{
                touchAction: tool === "READ" ? "auto" : "none",
                pointerEvents: tool === "READ" ? "none" : "auto",
                cursor: tool === "READ" ? "default" : "crosshair",
              }}
              onPointerDown={(event) => begin(event, physicalPage)}
              onPointerMove={move}
              onPointerUp={finish}
              onPointerCancel={() => {
                gesture.current = null;
                setDrawing(null);
                setDrawingPage(null);
              }}
            >
              {(
                collection?.annotations.filter(
                  (item) => item.page === physicalPage,
                ) ?? []
              ).map((item) => (
                <g
                  key={item.id}
                  role="button"
                  tabIndex={0}
                  aria-label={`${names[item.kind]}：${item.body || "无文字"}`}
                  onPointerDown={(event) => {
                    if (tool === "READ") event.stopPropagation();
                  }}
                  onClick={() => {
                    if (!unsaved && tool === "READ") setSelected(item);
                  }}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && !unsaved) setSelected(item);
                  }}
                >
                  {item.geometries.map((shape, index) => (
                    <Shape
                      key={index}
                      shape={shape}
                      kind={item.kind}
                      color={item.color}
                      selected={selected?.id === item.id}
                    />
                  ))}
                </g>
              ))}
              {drawing && drawingPage === physicalPage && tool !== "READ" && (
                <Shape
                  shape={drawing}
                  kind={tool}
                  color={color}
                  selected={false}
                />
              )}
            </svg>
          )}
        </ContinuousPages>
      )}
      {(draft || selected) && (
        <div className="space-y-2 rounded-lg border p-3" aria-label="标记详情">
          <p>
            {names[(draft || selected)!.kind]} · 第 {(draft || selected)!.page}{" "}
            页
          </p>
          <label className="block">
            批注内容
            <textarea
              aria-label="批注内容"
              className="mt-2 block min-h-24 w-full rounded border p-2"
              maxLength={10000}
              value={(draft || selected)!.body}
              disabled={saving || pending !== null}
              onChange={(event) => {
                setDraft({ ...(draft || selected)!, body: event.target.value });
                setStatus("有未保存批注");
              }}
            />
          </label>
          <Button
            disabled={
              saving ||
              pending !== null ||
              !draft ||
              (draft.kind === "COMMENT" && !draft.body.trim())
            }
            onClick={() => draft && void writeMark(draft)}
          >
            保存批注
          </Button>
          <Button
            variant="secondary"
            disabled={saving || pending !== null}
            onClick={() => {
              setDraft(null);
              setSelected(null);
              setStatus("已关闭标记详情");
            }}
          >
            放弃编辑
          </Button>
          {selected && (
            <Button
              variant="danger"
              disabled={saving || pending !== null || draft !== null}
              onClick={() => void writeMark(selected, true)}
            >
              删除标记
            </Button>
          )}
        </div>
      )}
      <div className="flex flex-wrap gap-2" aria-label="本页标记列表">
        {shown.map((item) => (
          <Button
            key={item.id}
            variant="secondary"
            disabled={unsaved}
            onClick={() => {
              setTool("READ");
              setSelected(item);
            }}
          >
            {names[item.kind]}
            {item.body ? ` · ${item.body.slice(0, 24)}` : ""}
          </Button>
        ))}
      </div>
    </section>
  );
}
function geometry(
  start: { x: number; y: number },
  end: { x: number; y: number },
  kind: AnnotationKind | "READ",
  points: { x: number; y: number }[],
): AnnotationGeometry {
  if (kind === "INK") return { geometry_kind: "STROKE", points };
  return {
    geometry_kind: "RECT",
    x: Math.min(start.x, end.x, 0.985),
    y: Math.min(start.y, end.y, 0.985),
    width: Math.min(
      1 - Math.min(start.x, end.x, 0.985),
      Math.max(0.008, Math.abs(end.x - start.x)),
    ),
    height: Math.min(
      1 - Math.min(start.y, end.y, 0.985),
      Math.max(0.008, Math.abs(end.y - start.y)),
    ),
    points: [],
  };
}
function Shape({
  shape,
  kind,
  color,
  selected,
}: {
  shape: AnnotationGeometry;
  kind: AnnotationKind;
  color: string;
  selected: boolean;
}) {
  if (shape.geometry_kind === "STROKE")
    return (
      <polyline
        points={shape.points
          .map((point) => `${point.x * 1000},${point.y * 1000}`)
          .join(" ")}
        fill="none"
        stroke={color}
        strokeWidth={selected ? 5 : 3}
        vectorEffect="non-scaling-stroke"
      />
    );
  const x = (shape.x ?? 0) * 1000;
  const y = (shape.y ?? 0) * 1000;
  const w = (shape.width ?? 0) * 1000;
  const h = (shape.height ?? 0) * 1000;
  if (kind === "UNDERLINE")
    return (
      <line
        x1={x}
        y1={y + h}
        x2={x + w}
        y2={y + h}
        stroke={color}
        strokeWidth={selected ? 5 : 3}
        vectorEffect="non-scaling-stroke"
      />
    );
  return (
    <rect
      x={x}
      y={y}
      width={w}
      height={h}
      fill={color}
      fillOpacity={kind === "HIGHLIGHT" ? 0.3 : 0.2}
      stroke={color}
      strokeWidth={selected ? 3 : kind === "COMMENT" ? 2 : 0}
      vectorEffect="non-scaling-stroke"
    />
  );
}
function message(cause: unknown) {
  return cause instanceof Error ? cause.message : "网络请求失败";
}
