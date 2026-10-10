"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  FileText,
  MessageSquareText,
  ShieldCheck,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { MarkdownViewer } from "@/components/markdown/markdown-viewer";
import { MarkdownContent } from "@/components/markdown/markdown-content";
import { Textarea } from "@/components/ui/input";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state";
import {
  api,
  ApiError,
  getSession,
  type Paper,
  type ResearchNote,
  type ReviewAction,
} from "@/lib/api";
import { NoteSourcePanel } from "@/components/research-notes/source-panel";
import { NoteReviewPanel } from "@/components/research-notes/review-panel";
import { NoteTrashControl } from "@/components/research-notes/trash-control";
import {
  ClassificationEditor,
  ProjectLabels,
  ZoteroSourceLabels,
  type NoteClassification,
} from "@/components/literature/classification";
import {
  feedbackLabel,
  loadPending,
  savePending,
  type PendingFeedback,
} from "@/components/research-notes/feedback";

export default function ResearchNotePage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [note, setNote] = useState<ResearchNote | null>(null);
  const [paper, setPaper] = useState<Paper | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [sourceOpen, setSourceOpen] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const [editingSection, setEditingSection] = useState("");
  const [editAction, setEditAction] = useState<"COMMENT" | "EDIT">("COMMENT");
  const [editText, setEditText] = useState("");
  const [comment, setComment] = useState("");
  const [pending, setPending] = useState<PendingFeedback | null>(null);
  const [ownerId, setOwnerId] = useState<string | null>(null);
  const [trashActive, setTrashActive] = useState(false);
  const [classification, setClassification] =
    useState<NoteClassification | null>(null);
  const [classificationError, setClassificationError] = useState("");
  const saving = useRef(false);
  const loadSequence = useRef(0);
  const classificationSequence = useRef(0);
  const loadClassification = useCallback(() => {
    const sequence = ++classificationSequence.current;
    api
      .get<NoteClassification>(`/research-notes/${id}/classification`)
      .then((value) => {
        if (classificationSequence.current === sequence) {
          setClassification(value);
          setClassificationError("");
        }
      })
      .catch((cause) => {
        if (classificationSequence.current === sequence)
          setClassificationError(
            cause instanceof Error ? cause.message : "分类暂不可用",
          );
      });
  }, [id]);

  const load = useCallback(async () => {
    const sequence = ++loadSequence.current;
    setLoading(true);
    setError("");
    try {
      const loaded = await api.get<ResearchNote>(`/research-notes/${id}`);
      if (loadSequence.current !== sequence) return;
      setNote(loaded);
      // Optional metadata never holds back the saved note itself.
      void api
        .get<Paper>(`/papers/${loaded.paper_id}`)
        .then((value) => {
          if (loadSequence.current === sequence) setPaper(value);
        })
        .catch(() => {
          if (loadSequence.current === sequence) setPaper(null);
        });
    } catch (cause) {
      if (loadSequence.current === sequence)
        setError(cause instanceof Error ? cause.message : "无法加载精读笔记");
    } finally {
      if (loadSequence.current === sequence) setLoading(false);
    }
  }, [id]);
  useEffect(() => {
    let current = true;
    queueMicrotask(() => {
      setNote(null);
      setPaper(null);
      setSourceOpen(false);
      setAdvancedOpen(false);
      setFeedbackOpen(false);
      setPending(null);
      setClassification(null);
      setClassificationError("");
      setOwnerId(null);
      void load();
      loadClassification();
      void getSession()
        .then((owner) => {
          if (!current) return;
          setOwnerId(owner.id);
          const saved = loadPending(owner.id, id);
          if (saved) {
            setPending(saved);
            setFeedbackOpen(true);
            setEditingSection(saved.sectionKey);
            setEditAction(saved.body.action);
            setEditText(saved.body.edited_body_markdown ?? "");
            setComment(saved.body.comment ?? "");
          }
        })
        .catch(() => {
          /* A failed session check must not erase the note. */
        });
    });
    return () => {
      current = false;
      loadSequence.current += 1;
      classificationSequence.current += 1;
    };
  }, [id, load, loadClassification]);

  function openFeedback(sectionKey?: string) {
    if (!note || pending) {
      setFeedbackOpen(true);
      return;
    }
    const section =
      note.sections.find((item) => item.section_key === sectionKey) ??
      note.sections[0];
    setEditingSection(section?.section_key ?? "");
    setEditAction("COMMENT");
    setEditText(section?.body_markdown ?? "");
    setComment("");
    setFeedbackOpen(true);
  }
  function clearPending() {
    if (ownerId) savePending(ownerId, id, null);
    setPending(null);
  }
  function saved(updated: ResearchNote) {
    clearPending();
    setFeedbackOpen(false);
    setComment("");
    setEditText("");
    setMessage(
      updated.id === id
        ? "问题或建议已记录。"
        : "修订已保存为新版本，原笔记保留。",
    );
    if (updated.id !== id) router.push(`/research-notes/${updated.id}`);
    else setNote(updated);
  }
  async function submitFeedback() {
    if (
      !note ||
      !ownerId ||
      pending ||
      !editingSection ||
      saving.current ||
      trashActive
    )
      return;
    saving.current = true;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const before = await api.get<ReviewAction[]>(
        `/research-notes/${id}/reviews`,
      );
      const body = {
        action: editAction,
        comment: comment.trim() || null,
        edited_body_markdown: editAction === "EDIT" ? editText : null,
      };
      const frozen: PendingFeedback = {
        ownerId,
        noteId: id,
        paperId: note.paper_id,
        revision: note.revision,
        sectionKey: editingSection,
        body,
        priorReviewIds: before.map((row) => row.id),
      };
      // This endpoint has no idempotency token. Persist before sending; only read receipts after uncertainty.
      savePending(ownerId, id, frozen);
      setPending(frozen);
      try {
        saved(
          await api.post<ResearchNote>(
            `/research-notes/${id}/sections/${editingSection}/review`,
            body,
          ),
        );
      } catch (cause) {
        if (
          cause instanceof ApiError &&
          [400, 401, 403, 404, 422].includes(cause.status)
        )
          clearPending();
        throw cause;
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "提交结果暂无法确认");
    } finally {
      saving.current = false;
      setBusy(false);
    }
  }
  async function inspectFeedback() {
    if (!pending) return;
    setBusy(true);
    setError("");
    try {
      const matches = (actions: ReviewAction[], revision: number) =>
        actions.filter(
          (row) =>
            !pending.priorReviewIds.includes(row.id) &&
            row.section_key === pending.sectionKey &&
            row.action === pending.body.action &&
            row.comment === pending.body.comment &&
            row.reviewed_revision === revision,
        );
      if (pending.body.action === "COMMENT") {
        const actions = await api.get<ReviewAction[]>(
          `/research-notes/${id}/reviews`,
        );
        if (matches(actions, pending.revision).length === 1) {
          saved(await api.get<ResearchNote>(`/research-notes/${id}`));
          return;
        }
      } else {
        const revisions = await api.get<ResearchNote[]>(
          `/papers/${pending.paperId}/research-notes`,
        );
        const candidates = revisions.filter(
          (row) =>
            row.parent_note_id === id &&
            row.sections.some(
              (section) =>
                section.section_key === pending.sectionKey &&
                section.body_markdown === pending.body.edited_body_markdown,
            ),
        );
        const confirmed: ResearchNote[] = [];
        for (const candidate of candidates) {
          const actions = await api.get<ReviewAction[]>(
            `/research-notes/${candidate.id}/reviews`,
          );
          if (matches(actions, candidate.revision).length === 1)
            confirmed.push(candidate);
        }
        if (confirmed.length === 1) {
          saved(confirmed[0]);
          return;
        }
      }
      setMessage(
        "尚未找到唯一匹配的保存记录。保留当前内容，请稍后核查；系统不会重复提交。",
      );
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "无法核查保存记录");
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <LoadingState label="正在加载精读笔记…" />;
  if (!note)
    return (
      <div className="space-y-4">
        <ErrorState
          message={error || "笔记暂不可用"}
          onRetry={() => void load()}
        />
        <div className="relative flex flex-wrap items-center gap-3">
          <Link href="/note-trash" className="text-sm text-[var(--accent)]">
            查看历史删除记录 →
          </Link>
          <NoteTrashControl noteId={id} ownerId={ownerId} recoveryOnly />
        </div>
      </div>
    );
  const autoReview = note.auto_review;
  return (
    <div className="mx-auto w-full min-w-0 max-w-6xl space-y-4">
      <Link
        href={`/papers/${note.paper_id}/analysis`}
        className="inline-flex items-center gap-2 text-xs text-[var(--muted)] hover:text-[var(--accent)]"
      >
        <ArrowLeft className="h-4 w-4" />
        返回文献
      </Link>
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="mb-1 text-xs text-[var(--accent)]">
            精读笔记 · v{note.revision}
          </p>
          <h1 className="text-xl font-semibold leading-snug">
            {paper?.title || "精读笔记"}
          </h1>
        </div>
        <div className="flex flex-wrap gap-1">
          <NoteTrashControl
            noteId={id}
            ownerId={ownerId}
            blocked={busy || !!pending}
            onActiveChange={setTrashActive}
          />
          <Button
            size="sm"
            variant="secondary"
            aria-expanded={sourceOpen}
            onClick={() => setSourceOpen(!sourceOpen)}
          >
            <FileText className="h-3.5 w-3.5" />
            {sourceOpen ? "收起原文" : "查看原文"}
          </Button>
          <Button
            size="sm"
            variant="secondary"
            aria-expanded={feedbackOpen}
            disabled={trashActive}
            onClick={() =>
              feedbackOpen ? setFeedbackOpen(false) : openFeedback()
            }
          >
            <MessageSquareText className="h-3.5 w-3.5" />
            反馈问题/建议
          </Button>
        </div>
      </header>
      <div className="space-y-2">
        {classification ? (
          <ProjectLabels
            projects={classification.projects}
            mode={classification.mode}
          />
        ) : (
          <p className="text-xs text-[var(--muted)]">
            课题分类{classificationError ? "暂不可用" : "正在加载…"}
          </p>
        )}
        {classificationError && (
          <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--accent)]">
            <span role="alert">{classificationError}</span>
            <Button size="sm" variant="ghost" onClick={loadClassification}>
              刷新分类
            </Button>
          </div>
        )}
        <ClassificationEditor
          key={id}
          paperId={note.paper_id}
          noteId={id}
          blocked={trashActive || busy || !!pending}
          onSaved={loadClassification}
        />
        {paper && (
          <details className="text-xs text-[var(--muted)]">
            <summary className="cursor-pointer">Zotero 来源文件夹</summary>
            <div className="mt-2">
              <ZoteroSourceLabels context={paper.literature_context} />
            </div>
          </details>
        )}
      </div>
      <details
        className={`rounded-md border px-3 py-2 text-xs ${autoReview?.status === "PASSED" ? "border-emerald-500/20 text-emerald-700 dark:text-emerald-300" : "border-amber-500/30 text-amber-800 dark:text-amber-300"}`}
      >
        <summary className="cursor-pointer font-medium">
          {autoReview?.label ?? "自动检查记录不足"}
        </summary>
        <div className="mt-2 space-y-1.5 text-[var(--muted)]">
          {autoReview?.checks.map((check) => (
            <p key={check.key}>
              <span className="font-medium">{check.label}：</span>
              {check.detail}
            </p>
          ))}
          <p>
            系统检查不代表科研结论已证实；有问题可直接反馈，无需逐章确认才能阅读。
          </p>
        </div>
      </details>
      {error && <ErrorState message={error} />}
      {message && (
        <p
          role="status"
          className="rounded border border-[var(--border)] px-3 py-2 text-sm text-[var(--muted)]"
        >
          {message}
        </p>
      )}
      {feedbackOpen && (
        <section
          aria-label="笔记反馈"
          className="space-y-3 rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4"
        >
          <div className="flex flex-wrap justify-between gap-2">
            <h2 className="font-semibold">提出问题或建议</h2>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setFeedbackOpen(false)}
            >
              收起反馈
            </Button>
          </div>
          {note.sections.length ? (
            <>
              <div className="flex flex-wrap items-center gap-3">
                <label className="text-xs">
                  关联内容
                  <select
                    aria-label="反馈关联章节"
                    className="ml-2 rounded border border-[var(--border)] bg-[var(--background)] p-2 text-sm"
                    value={editingSection}
                    disabled={busy || !!pending}
                    onChange={(event) => {
                      setEditingSection(event.target.value);
                      setEditText(
                        note.sections.find(
                          (section) =>
                            section.section_key === event.target.value,
                        )?.body_markdown ?? "",
                      );
                    }}
                  >
                    {note.sections.map((section) => (
                      <option value={section.section_key} key={section.id}>
                        {feedbackLabel(section.section_key)}
                      </option>
                    ))}
                  </select>
                </label>
                <Button
                  size="sm"
                  variant={editAction === "COMMENT" ? "secondary" : "ghost"}
                  disabled={busy || !!pending}
                  onClick={() => setEditAction("COMMENT")}
                >
                  问题/建议
                </Button>
                <Button
                  size="sm"
                  variant={editAction === "EDIT" ? "secondary" : "ghost"}
                  disabled={busy || !!pending}
                  onClick={() => setEditAction("EDIT")}
                >
                  修订正文
                </Button>
              </div>
              {editAction === "EDIT" && (
                <>
                  <Textarea
                    aria-label="修订后的章节内容"
                    className="min-h-72 font-mono"
                    value={editText}
                    disabled={busy || !!pending}
                    onChange={(event) => setEditText(event.target.value)}
                  />
                  <details className="rounded border border-[var(--border)] p-3">
                    <summary className="cursor-pointer text-xs">
                      预览修订内容
                    </summary>
                    <div className="mt-3" aria-label="修订内容只读预览">
                      <MarkdownContent content={editText} />
                    </div>
                  </details>
                </>
              )}
              <Textarea
                aria-label="问题或建议"
                value={comment}
                disabled={busy || !!pending}
                onChange={(event) => setComment(event.target.value)}
                placeholder={
                  editAction === "COMMENT"
                    ? "记录问题、补充信息或改进建议"
                    : "说明修订原因（可选）"
                }
              />
              {pending ? (
                <div className="space-y-2">
                  <p className="text-xs text-amber-700 dark:text-amber-300">
                    上次提交结果待核查，原内容已保留。核查仅读取保存记录，不会重复提交。
                  </p>
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={busy}
                    onClick={() => void inspectFeedback()}
                  >
                    {busy ? "正在核查…" : "核查提交结果"}
                  </Button>
                </div>
              ) : (
                <Button
                  size="sm"
                  disabled={
                    busy ||
                    trashActive ||
                    !ownerId ||
                    (editAction === "COMMENT"
                      ? !comment.trim()
                      : !editText.trim())
                  }
                  onClick={() => void submitFeedback()}
                >
                  {busy
                    ? "正在保存…"
                    : editAction === "EDIT"
                      ? "保存新版本"
                      : "提交建议"}
                </Button>
              )}
            </>
          ) : (
            <EmptyState
              title="此版本没有可关联的笔记内容"
              detail="可返回文献工作区重新提交精读或查看来源。"
            />
          )}
        </section>
      )}
      {sourceOpen && <NoteSourcePanel note={note} />}
      <article
        aria-label="精读笔记正文"
        className="min-w-0 rounded-xl border border-[var(--border)] bg-[var(--surface)] px-4 py-5 sm:px-7 sm:py-7 lg:px-9"
      >
        {note.sections.length ? (
          note.sections.map((section) => (
            <section
              key={section.id}
              className="min-w-0 space-y-2 border-b border-[var(--border)] pb-6 last:border-b-0 last:pb-0 [&+section]:pt-6"
            >
              {section.section_key !== "analytical_note" && (
                <h2 className="text-base font-semibold">
                  {feedbackLabel(section.section_key)}
                </h2>
              )}
              {section.body_markdown ? (
                <MarkdownViewer
                  content={section.body_markdown}
                  label={`科研笔记「${feedbackLabel(section.section_key)}」原文`}
                />
              ) : (
                <p className="text-sm text-[var(--muted)]">
                  本次资料不足，未给出该章节内容。
                </p>
              )}
              {section.uncertainty && (
                <p className="rounded bg-amber-500/8 px-3 py-2 text-xs leading-5 text-amber-800 dark:text-amber-300">
                  需注意：{section.uncertainty}
                </p>
              )}
            </section>
          ))
        ) : (
          <EmptyState title="此版本尚无精读内容" />
        )}
      </article>
      <Button
        variant="ghost"
        size="sm"
        disabled={trashActive}
        aria-expanded={advancedOpen}
        onClick={() => setAdvancedOpen(!advancedOpen)}
      >
        <ShieldCheck className="h-3.5 w-3.5" />
        {advancedOpen ? "收起核实与记录" : "核实与记录（可选）"}
      </Button>
      {advancedOpen && !trashActive && (
        <NoteReviewPanel note={note} onNote={setNote} />
      )}
    </div>
  );
}
