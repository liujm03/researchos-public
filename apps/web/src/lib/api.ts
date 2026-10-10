import type { components } from "./generated";

export type SessionUser = components["schemas"]["SessionOut"];
export type Project = components["schemas"]["ProjectOut"];
export type ProjectQuestion = components["schemas"]["QuestionOut"];
export type ProjectPaper = components["schemas"]["ProjectPaperSummary"];
export type Paper = components["schemas"]["PaperOut"];
export type Note = components["schemas"]["NoteOut"];
export type Task = components["schemas"]["TaskOut"];
export type Journal = components["schemas"]["JournalOut"];
export type Dashboard = components["schemas"]["DashboardOut"];
export type Analytics = components["schemas"]["AnalyticsOverview"];
export type Heatmap = components["schemas"]["HeatmapOut"];
export type SearchResult = components["schemas"]["SearchPage"];
export type ZoteroStatus = components["schemas"]["StatusOut"];
export type ZoteroItem = components["schemas"]["ReferenceItemOut"];
export type ZoteroCatalogPage = components["schemas"]["ZoteroCatalogPage"];
export type ZoteroCollection = components["schemas"]["CollectionOut"];
export type ZoteroAttachment = components["schemas"]["AttachmentOut"];
export type ZoteroFulltext = components["schemas"]["IndexedTextOut"];
export type ZoteroImport = components["schemas"]["ImportItemOut"];
export type CopiedPdf = components["schemas"]["CopiedPdfOut"];
export type PaperAttachment = components["schemas"]["PaperAttachmentOut"];
export type ParseJob = components["schemas"]["ParseJobOut"];
export type PdfUpload = components["schemas"]["PdfUploadOut"];
export type ParsedDocument = components["schemas"]["ParsedDocumentOut"];
export type AnalysisJob = components["schemas"]["AnalysisJobOut"];
export type PDFReadingJobCreate =
  components["schemas"]["ApprovedReadingCreate"];
export type ReadingPlanCreate = components["schemas"]["ReadingPlanCreate"];
export type ReadingPlan = components["schemas"]["ReadingPlanOut"];
export type CanonicalNote = components["schemas"]["CanonicalNoteOut"];
export type PDFReadingSource = components["schemas"]["PDFReadingSourceOut"];
export type AnalysisResultIssue =
  components["schemas"]["AnalysisResultIssueOut"];
export type ResearchNote = components["schemas"]["ResearchNoteOut"];
export type ReviewAction = components["schemas"]["ReviewActionOut"];
export type InboxItem = components["schemas"]["InboxOut"];
export type PaperContext = components["schemas"]["PaperLiteratureContextOut"];
export type ClassificationOptions = components["schemas"]["LiteratureClassificationOptionsOut"];
export type NoteProjectContext = components["schemas"]["NoteProjectContextOut"];
export type AutomationSettings = components["schemas"]["AutomationSettingsOut"];
export type AICapabilities = components["schemas"]["AICapabilitiesOut"];
export type AIUsage = components["schemas"]["AIUsageOut"];
export type ConfigurationReport = components["schemas"]["ConfigurationReport"];
export type ZoteroSyncJob = components["schemas"]["SyncJobOut"];
export type ZoteroSyncJobPage = components["schemas"]["SyncJobPage"];
export type ZoteroSyncItemPage = components["schemas"]["SyncItemPage"];
export type ZoteroSyncRequest = components["schemas"]["SyncRequest"];
export type LiteratureJob = components["schemas"]["IngestJobOut"];
export type ClearLiteratureJobsOut = components["schemas"]["ClearIngestsOut"];
export type PaperReproductionPreviewRequest =
  components["schemas"]["PaperReproductionPreviewRequest"];
export type PaperReproductionCreateRequest =
  components["schemas"]["PaperReproductionCreateRequest"];
export type PaperReproductionPreview =
  components["schemas"]["PaperReproductionPreviewOut"];
export type ReproductionSource = components["schemas"]["ReproductionSourceOut"];
export type ReproductionSourceContent =
  components["schemas"]["ReproductionSourceContentOut"];
export type ReproductionSourcePage =
  components["schemas"]["ReproductionSourcePage"];
export type ReproductionExcerptRange =
  components["schemas"]["ReproductionExcerptRange"];
export type ArxivPreviewRequest = components["schemas"]["ArxivPreviewRequest"];
export type ArxivPreview = components["schemas"]["ArxivPreviewOut"];
export type ArxivConfirmRequest = components["schemas"]["ArxivConfirmRequest"];
export type ArxivConfirm = components["schemas"]["ArxivConfirmOut"];
export type LiteratureProvider = components["schemas"]["LiteratureProviderOut"];
export type LiteratureProviders =
  components["schemas"]["LiteratureProvidersOut"];
export type Page<T> = {
  items: T[];
  page: { limit: number; next_cursor: string | null; total?: number | null };
};

const base = process.env.NEXT_PUBLIC_API_BASE_PATH ?? "/api/v1";
let csrfToken: string | null = null;

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: unknown,
  ) {
    super(message);
  }
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  version?: number,
  skipCsrf = false,
): Promise<T> {
  const mutating = !["GET", "HEAD"].includes(method);
  if (mutating && !skipCsrf && !csrfToken) await getSession();
  const headers = new Headers();
  const multipart = typeof FormData !== "undefined" && body instanceof FormData;
  // The browser supplies the multipart boundary; JSON requests keep their current contract.
  if (body !== undefined && !multipart)
    headers.set("Content-Type", "application/json");
  if (mutating && !skipCsrf && csrfToken)
    headers.set("X-CSRF-Token", csrfToken);
  if (version !== undefined) headers.set("If-Match", String(version));
  const response = await fetch(`${base}${path}`, {
    method,
    headers,
    credentials: "same-origin",
    cache: "no-store",
    body:
      body === undefined ? undefined : multipart ? body : JSON.stringify(body),
  });
  if (!response.ok) {
    let payload: {
      error?: { code?: string; message?: string; details?: unknown };
    } = {};
    try {
      payload = await response.json();
    } catch {
      /* network/proxy error body */
    }
    const validation = Array.isArray(payload.error?.details)
      ? payload.error.details
          .map(
            (detail: { loc?: (string | number)[]; msg?: string }) =>
              `${detail.loc?.slice(1).join(".") || "字段"}: ${detail.msg || "格式不正确"}`,
          )
          .join("；")
      : undefined;
    throw new ApiError(
      response.status,
      payload.error?.code ?? "HTTP_ERROR",
      validation || payload.error?.message || `请求失败 (${response.status})`,
      payload.error?.details,
    );
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body),
  postForm: <T>(path: string, body: FormData) => request<T>("POST", path, body),
  put: <T>(path: string, body: unknown, version?: number) =>
    request<T>("PUT", path, body, version),
  patch: <T>(path: string, body: unknown, version?: number) =>
    request<T>("PATCH", path, body, version),
  delete: (path: string) => request<void>("DELETE", path),
};

export async function getSession(): Promise<SessionUser> {
  const session = await request<SessionUser>("GET", "/auth/session");
  csrfToken = session.csrf_token ?? null;
  return session;
}

export async function login(
  email: string,
  password: string,
): Promise<SessionUser> {
  const session = await request<SessionUser>(
    "POST",
    "/auth/login",
    { email, password },
    undefined,
    true,
  );
  csrfToken = session.csrf_token ?? null;
  return session;
}

export async function setup(
  setupToken: string,
  email: string,
  displayName: string,
  password: string,
) {
  return request<SessionUser>(
    "POST",
    "/auth/setup",
    { setup_token: setupToken, email, display_name: displayName, password },
    undefined,
    true,
  );
}

export async function logout() {
  await request<void>("POST", "/auth/logout");
  csrfToken = null;
}
