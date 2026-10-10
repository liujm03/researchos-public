"use client";

import { useEffect, useRef, useState } from "react";
import type { PDFDocumentProxy } from "pdfjs-dist";
import "./text-layer.css";

export function PdfPage({
  document,
  page,
  zoom,
  children,
  onAspectRatio,
}: {
  document: PDFDocumentProxy;
  page: number;
  zoom: number;
  children: React.ReactNode;
  onAspectRatio?: (ratio: number) => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const canvasHost = useRef<HTMLDivElement>(null);
  const textHost = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(700);
  const [size, setSize] = useState({ width: 700, height: 900 });
  const [error, setError] = useState("");
  const [ready, setReady] = useState(false);
  useEffect(() => {
    const element = host.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) =>
      setWidth(Math.max(200, entry.contentRect.width)),
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    let cancelled = false;
    let rendering:
      | ReturnType<Awaited<ReturnType<PDFDocumentProxy["getPage"]>>["render"]>
      | undefined;
    let textLayer: import("pdfjs-dist").TextLayer | undefined;
    queueMicrotask(() => {
      if (!cancelled) {
        setReady(false);
        setError("");
      }
    });
    void document
      .getPage(page)
      .then(async (pdfPage) => {
        if (cancelled || !canvasHost.current || !textHost.current) return;
        const viewport = pdfPage.getViewport({ scale: 1 });
        const view = pdfPage.getViewport({
          scale: (width / viewport.width) * zoom,
        });
        if (
          view.height > 16000 ||
          view.width > 16000 ||
          view.height * view.width > 16000000
        )
          throw new Error("此页尺寸过大，请下载原 PDF 使用独立阅读器。");
        setSize({ width: view.width, height: view.height });
        onAspectRatio?.(view.height / view.width);
        // A fresh node per rendering prevents PDF.js reusing a canvas still being cancelled.
        const target = window.document.createElement("canvas");
        const text = window.document.createElement("div");
        const ratio = Math.min(window.devicePixelRatio || 1, 2);
        target.width = Math.ceil(view.width * ratio);
        target.height = Math.ceil(view.height * ratio);
        target.style.width = `${view.width}px`;
        target.style.height = `${view.height}px`;
        target.setAttribute("aria-label", `PDF 原文第 ${page} 页`);
        text.className = "pdf-selectable-text textLayer";
        text.setAttribute("aria-label", "PDF 原文可选文字");
        text.style.setProperty("--total-scale-factor", String(view.scale));
        text.style.setProperty("--scale-round-x", "1px");
        text.style.setProperty("--scale-round-y", "1px");
        canvasHost.current.replaceChildren(target);
        textHost.current.replaceChildren(text);
        rendering = pdfPage.render({
          canvas: target,
          viewport: view,
          transform: [ratio, 0, 0, ratio, 0, 0],
        });
        await rendering.promise;
        if (cancelled) return;
        setReady(true);
        const { TextLayer } = await import("pdfjs-dist");
        if (cancelled) return;
        textLayer = new TextLayer({
          textContentSource: pdfPage.streamTextContent(),
          container: text,
          viewport: view,
        });
        await textLayer.render();
      })
      .catch((cause: unknown) => {
        if (!cancelled)
          setError(cause instanceof Error ? cause.message : "页面显示失败");
      });
    return () => {
      cancelled = true;
      rendering?.cancel();
      textLayer?.cancel();
    };
  }, [document, page, width, zoom, onAspectRatio]);
  return (
    <div
      ref={host}
      className="overflow-visible"
      aria-label={`PDF 第 ${page} 页显示区`}
    >
      {error && <p role="alert">{error}</p>}
      <div
        className="relative mx-auto bg-white"
        style={{ width: size.width, height: size.height }}
      >
        <div ref={canvasHost} />
        <div ref={textHost} />
        {ready ? (
          children
        ) : (
          <p
            role="status"
            className="absolute left-4 top-4 bg-white p-2 text-black"
          >
            正在显示页面…
          </p>
        )}
      </div>
    </div>
  );
}
