import type { components } from "@/lib/generated";

export type GeneratedFileSettings =
  components["schemas"]["GeneratedFileSettingsOut"];
export type NoteDeletionPreview =
  components["schemas"]["NoteDeletionPreviewOut"];
export type NoteDeletionReceipt = components["schemas"]["NoteDeletionOut"];
export type NoteTrashEntry = components["schemas"]["NoteTrashEntryOut"];
export type NoteTrashPreview = components["schemas"]["NoteTrashPreviewOut"];
export type NoteTrashScope = "VERSION" | "READING_RUN";
export const scopeLabel = (scope: NoteTrashScope) =>
  scope === "READING_RUN" ? "本次精读的全部笔记版本" : "旧版单版本记录";
export const fileRetentionMessage =
  "此为旧版回收记录，当时保留了 Markdown 文件。现在确认删除会永久移除系统管理的笔记文件，不可恢复。";
export const permanentDeletionMessage =
  "确认后永久删除本次精读的全部笔记版本及系统管理的 Markdown 文件和副本，不可恢复。原始 PDF 和 Zotero 文献保留；独立备份及手动副本不在范围内。";

export type PendingNoteDeletion = {
  ownerId: string;
  noteId: string;
  key: string;
  previewSha256: string;
};
const keyFor = (owner: string, note: string) =>
  `researchos:note-deletion:${owner}:${note}`;
export function loadPendingDeletion(
  ownerId: string,
  noteId: string,
): PendingNoteDeletion | null {
  try {
    const raw = localStorage.getItem(keyFor(ownerId, noteId));
    if (!raw) return null;
    const value = JSON.parse(raw) as Partial<PendingNoteDeletion>;
    if (
      value.ownerId !== ownerId ||
      value.noteId !== noteId ||
      typeof value.key !== "string" ||
      value.key.length < 1 ||
      value.key.length > 120 ||
      !/^[a-f0-9]{64}$/.test(value.previewSha256 ?? "")
    )
      return null;
    return value as PendingNoteDeletion;
  } catch {
    return null;
  }
}
export function persistDeletion(value: PendingNoteDeletion) {
  localStorage.setItem(
    keyFor(value.ownerId, value.noteId),
    JSON.stringify(value),
  );
}
export function clearPendingDeletion(value: PendingNoteDeletion) {
  localStorage.removeItem(keyFor(value.ownerId, value.noteId));
}
