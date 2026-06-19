import { createResource, createSignal, type Resource } from "solid-js";
import { api } from "~/lib/api";
import type { Upload, UploadStatus } from "./model";

/* ── Backend DTOs → seam types ────────────────────────────────────────────── */

interface UploadSummaryOut {
  id: string;
  filename: string;
  mime: string;
  sizeBytes: number;
  status: UploadStatus;
  vision: boolean;
  extractor: string | null;
  hasText: boolean;
  note: string | null;
  createdAt: string;
  updatedAt: string;
}

interface UploadOut {
  id: string;
  filename: string;
  mime: string;
  sizeBytes: number;
  status: UploadStatus;
  vision: boolean;
  extractor: string | null;
  extractedText: string | null;
  note: string | null;
  createdAt: string;
  updatedAt: string;
}

function toUpload(dto: UploadSummaryOut): Upload {
  return {
    id: dto.id,
    name: dto.filename,
    mime: dto.mime,
    sizeBytes: dto.sizeBytes,
    status: dto.status,
    vision: dto.vision,
    extractor: dto.extractor ?? undefined,
    note: dto.note ?? undefined,
  };
}

function toUploadDetail(dto: UploadOut): Upload {
  return {
    id: dto.id,
    name: dto.filename,
    mime: dto.mime,
    sizeBytes: dto.sizeBytes,
    status: dto.status,
    vision: dto.vision,
    extractor: dto.extractor ?? undefined,
    note: dto.note ?? undefined,
    extractedText: dto.extractedText ?? "",
  };
}

/* ── List (the seam) ──────────────────────────────────────────────────────── */

const [listTick, setListTick] = createSignal(0);

async function fetchUploads(): Promise<Upload[]> {
  const rows = await api.get<UploadSummaryOut[]>("/uploads");
  return rows.map(toUpload);
}

export function useUploads(): Resource<Upload[]> {
  const [data] = createResource(listTick, fetchUploads);
  return data;
}

/** Invalidate the list after a mutation (or while polling in-flight extractions). */
export function refreshUploads(): void {
  setListTick((n) => n + 1);
}

/* ── Detail (the seam) — the selected upload's full extracted text ─────────── */

const [detailTick, setDetailTick] = createSignal(0);

async function fetchUploadDetail(id: string): Promise<Upload> {
  return toUploadDetail(await api.get<UploadOut>(`/uploads/${id}`));
}

export function useUploadDetail(
  id: () => string | null,
): Resource<Upload | undefined> {
  const [data] = createResource(
    () => [id(), detailTick()] as const,
    ([uploadId]) =>
      uploadId ? fetchUploadDetail(uploadId) : Promise.resolve(undefined),
  );
  return data;
}

export function refreshUploadDetail(): void {
  setDetailTick((n) => n + 1);
}

/* ── Mutations ────────────────────────────────────────────────────────────── */

/** Upload one file. Returns the created (or recognized-duplicate) upload. */
export async function uploadFile(file: File): Promise<Upload> {
  const form = new FormData();
  form.append("file", file, file.name);
  const dto = await api.postForm<UploadOut>("/uploads", form);
  refreshUploads();
  return toUploadDetail(dto);
}

export async function deleteUpload(id: string): Promise<void> {
  await api.del(`/uploads/${id}`);
  refreshUploads();
}

export async function retryUpload(id: string): Promise<void> {
  await api.post(`/uploads/${id}/retry`);
  refreshUploads();
  refreshUploadDetail();
}

export async function correctUploadText(
  id: string,
  text: string,
): Promise<void> {
  await api.patch(`/uploads/${id}`, { text });
  refreshUploads();
  refreshUploadDetail();
}

/** Trigger a browser download of the original file bytes. */
export async function downloadUpload(id: string, name: string): Promise<void> {
  const blob = await api.getBlob(`/uploads/${id}/content`);
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  anchor.click();
  URL.revokeObjectURL(url);
}
