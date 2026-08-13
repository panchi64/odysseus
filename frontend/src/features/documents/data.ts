import { createResource, createSignal, type Resource } from "solid-js";
import { api } from "~/lib/api";
import type {
  DocStatus,
  DocVersion,
  DocumentDetail,
  DocumentSummary,
  SuggestionOutcome,
  SuggestionSet,
} from "./model";

/* ── Backend DTOs → seam types ────────────────────────────────────────────── */

interface DocumentSummaryOut {
  id: string;
  title: string;
  snippet: string;
  wordCount: number;
  archived: boolean;
  createdAt: string;
  updatedAt: string;
}

interface DocumentOut {
  id: string;
  title: string;
  body: string;
  docType: string;
  language: string | null;
  archived: boolean;
  createdAt: string;
  updatedAt: string;
  /** The version this write minted — set on the edit (PATCH) response, absent on reads. */
  version?: number;
}

interface DocumentVersionOut {
  id: string;
  version: number;
  origin: string;
  title: string;
  body: string;
  createdAt: string;
}

/** First line of the body, trimmed to a short preview (presentation-only). */
function snippetOf(body: string): string {
  const firstLine = body.split("\n").find((l) => l.trim()) ?? "";
  return firstLine.length > 140 ? `${firstLine.slice(0, 140)}…` : firstLine;
}

/** Word count derived from the body (presentation-only). */
function wordsOf(body: string): number {
  const trimmed = body.trim();
  return trimmed ? trimmed.split(/\s+/).length : 0;
}

function statusOf(archived: boolean): DocStatus {
  return archived ? "archived" : "active";
}

function toSummary(dto: DocumentSummaryOut): DocumentSummary {
  return {
    id: dto.id,
    title: dto.title,
    snippet: dto.snippet,
    updatedAt: dto.updatedAt,
    words: dto.wordCount,
    status: statusOf(dto.archived),
  };
}

function toVersion(dto: DocumentVersionOut): DocVersion {
  return {
    id: dto.id,
    version: dto.version,
    label: `Version ${dto.version}`,
    author: dto.origin.toUpperCase(),
    createdAt: dto.createdAt,
    body: dto.body,
  };
}

function toDetail(
  dto: DocumentOut,
  versions: DocumentVersionOut[],
): DocumentDetail {
  // The detail response carries the full body, so derive the summary fields from it
  // rather than refetching the list row.
  return {
    id: dto.id,
    title: dto.title,
    snippet: snippetOf(dto.body),
    updatedAt: dto.updatedAt,
    words: wordsOf(dto.body),
    status: statusOf(dto.archived),
    body: dto.body,
    versions: versions.map(toVersion),
  };
}

/* ── List (the seam) ──────────────────────────────────────────────────────── */

const [listTick, setListTick] = createSignal(0);

async function fetchDocuments(): Promise<DocumentSummary[]> {
  // Pull both active and archived so the library's tabs can filter client-side.
  const rows = await api.get<DocumentSummaryOut[]>(
    "/documents?include_archived=true",
  );
  return rows.map(toSummary);
}

export function useDocuments(): Resource<DocumentSummary[]> {
  const [data] = createResource(listTick, fetchDocuments);
  return data;
}

/** Invalidate the list after a mutation. */
export function refreshDocuments(): void {
  setListTick((n) => n + 1);
}

/* ── Detail (the seam) ────────────────────────────────────────────────────── */

const [detailTick, setDetailTick] = createSignal(0);

async function fetchDocumentDetail(id: string): Promise<DocumentDetail> {
  const [doc, versions] = await Promise.all([
    api.get<DocumentOut>(`/documents/${id}`),
    api.get<DocumentVersionOut[]>(`/documents/${id}/versions`),
  ]);
  return toDetail(doc, versions);
}

export function useDocumentDetail(id: () => string): Resource<DocumentDetail> {
  const [data] = createResource(
    () => [id(), detailTick()] as const,
    ([docId]) => fetchDocumentDetail(docId),
  );
  return data;
}

/** Invalidate the open document's detail after a mutation. */
export function refreshDocumentDetail(): void {
  setDetailTick((n) => n + 1);
}

/* ── Mutations ────────────────────────────────────────────────────────────── */

/** Create a document and return its id (for navigating straight to the editor). */
export async function createDocument(
  title: string,
  body = "",
): Promise<string> {
  const dto = await api.post<DocumentOut>("/documents", { title, body });
  refreshDocuments();
  return dto.id;
}

export async function saveDocument(
  id: string,
  patch: { title?: string; body?: string },
): Promise<DocumentOut> {
  const dto = await api.patch<DocumentOut>(`/documents/${id}`, patch);
  refreshDocuments();
  refreshDocumentDetail();
  return dto;
}

export async function archiveDocument(id: string): Promise<void> {
  await api.post(`/documents/${id}/archive`);
  refreshDocuments();
}

export async function unarchiveDocument(id: string): Promise<void> {
  await api.post(`/documents/${id}/restore`);
  refreshDocuments();
}

export async function deleteDocument(id: string): Promise<void> {
  await api.del(`/documents/${id}`);
  refreshDocuments();
}

export async function restoreDocumentVersion(
  id: string,
  version: number,
): Promise<void> {
  await api.post(`/documents/${id}/versions/${version}/restore`);
  refreshDocuments();
  refreshDocumentDetail();
}

/* ── AI suggestions (DOC-3) ───────────────────────────────────────────────── */

/** The accept response. `document` is the document as it now stands — the backend is the
 *  authority on the resulting body, so the screen adopts it rather than re-deriving it. */
interface SuggestionAppliedOut {
  document: DocumentOut;
  version: number | null;
  accepted: string[];
  skipped: string[];
}

const [suggestionTick, setSuggestionTick] = createSignal(0);

/** Invalidate a document's pending suggestions after a decision. */
export function refreshSuggestions(): void {
  setSuggestionTick((n) => n + 1);
}

/** The AI's still-undecided proposals for a document, newest set first. Fully reviewed
 *  sets are omitted by the backend — this asks only for outstanding decisions. */
export function useDocumentSuggestions(
  id: () => string,
): Resource<SuggestionSet[]> {
  const [data] = createResource(
    () => [id(), suggestionTick()] as const,
    ([docId]) => api.get<SuggestionSet[]>(`/documents/${docId}/suggestions`),
  );
  return data;
}

function toOutcome(dto: SuggestionAppliedOut): SuggestionOutcome {
  return {
    body: dto.document.body,
    version: dto.version,
    accepted: dto.accepted,
    skipped: dto.skipped,
  };
}

/** Apply one proposed change. This is the only call here that changes the document — the
 *  backend mints the version and returns the resulting body. */
export async function acceptSuggestion(
  documentId: string,
  changeId: string,
): Promise<SuggestionOutcome> {
  const dto = await api.post<SuggestionAppliedOut>(
    `/documents/${documentId}/suggestion-changes/${changeId}/accept`,
  );
  refreshSuggestions();
  refreshDocuments();
  refreshDocumentDetail();
  return toOutcome(dto);
}

/** Decline one proposed change — no version, no edit. */
export async function rejectSuggestion(
  documentId: string,
  changeId: string,
): Promise<void> {
  await api.post(
    `/documents/${documentId}/suggestion-changes/${changeId}/reject`,
  );
  refreshSuggestions();
}

/** Apply every still-pending change in a set as one version. */
export async function acceptAllSuggestions(
  documentId: string,
  setId: string,
): Promise<SuggestionOutcome> {
  const dto = await api.post<SuggestionAppliedOut>(
    `/documents/${documentId}/suggestions/${setId}/accept-all`,
  );
  refreshSuggestions();
  refreshDocuments();
  refreshDocumentDetail();
  return toOutcome(dto);
}
