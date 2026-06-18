import { createResource, createSignal, type Resource } from "solid-js";
import { api } from "~/lib/api";
import type {
  DocStatus,
  DocVersion,
  DocumentDetail,
  DocumentSummary,
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
): Promise<void> {
  await api.patch(`/documents/${id}`, patch);
  refreshDocuments();
  refreshDocumentDetail();
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
