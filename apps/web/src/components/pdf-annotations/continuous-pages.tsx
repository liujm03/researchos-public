"use client";

import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import type { PDFDocumentProxy } from "pdfjs-dist";
import { PdfPage } from "./pdf-page";

export interface ContinuousPagesHandle {
  scrollToPage: (page: number) => void;
}
export const ContinuousPages = forwardRef<
  ContinuousPagesHandle,
  {
    document: PDFDocumentProxy;
    zoom: number;
    pinnedPage?: number;
    activePage: number;
    onActivePage: (page: number) => void;
    onKeyDown: (event: React.KeyboardEvent<HTMLDivElement>) => void;
    children: (page: number) => React.ReactNode;
  }
>(function ContinuousPages(
  { document, zoom, pinnedPage, activePage, onActivePage, onKeyDown, children },
  ref,
) {
  const root = useRef<HTMLDivElement>(null);
  const frames = useRef(new Map<number, HTMLDivElement>());
  const scrollToPage = useCallback(
    (page: number) => {
      const target = frames.current.get(page);
      const container = root.current;
      if (target && container) {
        container.scrollTop +=
          target.getBoundingClientRect().top -
          container.getBoundingClientRect().top -
          8;
        onActivePage(page);
      }
    },
    [onActivePage],
  );
  useImperativeHandle(ref, () => ({ scrollToPage }), [scrollToPage]);
  const updateActive = () => {
    const container = root.current;
    if (!container) return;
    const middle =
      container.getBoundingClientRect().top +
      Math.min(container.clientHeight * 0.35, 180);
    for (const [number, target] of frames.current) {
      const box = target.getBoundingClientRect();
      if (box.top <= middle && box.bottom > middle) {
        if (number !== activePage) onActivePage(number);
        break;
      }
    }
  };
  return (
    <div
      ref={root}
      role="region"
      aria-label="PDF 连续阅读区"
      tabIndex={0}
      data-testid="pdf-continuous-scroll"
      className="space-y-4 overflow-auto rounded-lg bg-black/20 p-2 outline-offset-2"
      style={{
        height: "min(76dvh, 1100px)",
        minHeight: 360,
        overscrollBehavior: "contain",
      }}
      onScroll={updateActive}
      onKeyDown={onKeyDown}
    >
      {Array.from({ length: document.numPages }, (_, index) => index + 1).map(
        (number) => (
          <LazyPage
            key={number}
            root={root}
            document={document}
            page={number}
            zoom={zoom}
            pinned={pinnedPage === number}
            frameRef={(node) => {
              if (node) frames.current.set(number, node);
              else frames.current.delete(number);
            }}
          >
            {children(number)}
          </LazyPage>
        ),
      )}
    </div>
  );
});

function LazyPage({
  root,
  document,
  page,
  zoom,
  pinned,
  frameRef,
  children,
}: {
  root: React.RefObject<HTMLDivElement | null>;
  document: PDFDocumentProxy;
  page: number;
  zoom: number;
  pinned: boolean;
  frameRef: (node: HTMLDivElement | null) => void;
  children: React.ReactNode;
}) {
  const frame = useRef<HTMLDivElement>(null);
  const [near, setNear] = useState(page === 1);
  const [ratio, setRatio] = useState(4 / 3);
  useEffect(() => {
    const target = frame.current;
    if (!target || !root.current) return;
    const observer = new IntersectionObserver(
      ([entry]) => setNear(entry.isIntersecting),
      { root: root.current, rootMargin: "300px" },
    );
    observer.observe(target);
    return () => observer.disconnect();
  }, [root]);
  return (
    <div
      ref={(node) => {
        frame.current = node;
        frameRef(node);
      }}
      data-pdf-page={page}
      aria-label={`PDF 第 ${page} 页容器`}
    >
      <p className="mb-1 text-sm">第 {page} 页</p>
      {near || pinned ? (
        <PdfPage
          document={document}
          page={page}
          zoom={zoom}
          onAspectRatio={setRatio}
        >
          {children}
        </PdfPage>
      ) : (
        <div
          className="mx-auto bg-white/90"
          aria-label={`第 ${page} 页待显示`}
          style={{ width: `${zoom * 100}%`, aspectRatio: `1 / ${ratio}` }}
        />
      )}
    </div>
  );
}
