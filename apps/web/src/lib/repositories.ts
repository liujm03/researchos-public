import type { components } from "./generated";

export type RepositoryImport = components["schemas"]["RepositoryImportOut"];
export type RepositoryImportPage =
  components["schemas"]["RepositoryImportPage"];
export type RepositoryCandidate =
  components["schemas"]["RepositoryCandidateOut"];
export type RepositorySource = components["schemas"]["RepositorySourceOut"];
export type RepositoryProviders =
  components["schemas"]["RepositoryProviderCatalogOut"];
export type RepositoryPreviewRequest =
  components["schemas"]["RepositoryPreviewRequest"];
export type RepositoryConfirmRequest =
  components["schemas"]["RepositoryConfirmRequest"];

export const repositoryKindLabels: Record<string, string> = {
  code: "代码仓库",
  model: "模型",
  dataset: "数据集",
  space: "Space",
};

export function repositoryTargetHref(kind: string | null, id: string | null) {
  if (!id) return null;
  if (kind === "model") return `/models/${encodeURIComponent(id)}`;
  if (kind === "dataset") return `/datasets/${encodeURIComponent(id)}`;
  return null;
}

export function publicRepositoryHref(value: string) {
  try {
    const url = new URL(value);
    if (
      url.protocol === "https:" &&
      ["github.com", "huggingface.co"].includes(url.hostname) &&
      !url.username &&
      !url.password &&
      !url.port
    )
      return url.href;
  } catch {
    /* External source URLs remain plain text when malformed. */
  }
  return null;
}
