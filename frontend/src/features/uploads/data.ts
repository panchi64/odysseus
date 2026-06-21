import {
  createEffect,
  createResource,
  createRoot,
  createSignal,
  onCleanup,
  untrack,
  type Accessor,
  type Resource,
} from "solid-js";
import { createStore, produce } from "solid-js/store";
import type { ComposerAttachment, ComposerAttachmentsApi } from "~/ui";
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
  kbExcluded: boolean;
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
  kbExcluded: boolean;
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
    kbExcluded: dto.kbExcluded,
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
    kbExcluded: dto.kbExcluded,
  };
}

/* ── List (the seam) ──────────────────────────────────────────────────────── */

const [listTick, setListTick] = createSignal(0);

async function fetchUploads(): Promise<Upload[]> {
  const rows = await api.get<UploadSummaryOut[]>("/uploads");
  return rows.map(toUpload);
}

// One shared list resource for every consumer (the uploads page, the sent-message
// attachment chips, …) so they don't each spin a duplicate `/uploads` fetch.
// Created under a detached root (like the chat stream) so it outlives any single
// component and stays live across navigation; keyed on `listTick`.
let uploadsResource: Resource<Upload[]> | undefined;

export function useUploads(): Resource<Upload[]> {
  if (!uploadsResource) {
    uploadsResource = createRoot(() => {
      const [data] = createResource(listTick, fetchUploads);
      return data;
    });
  }
  return uploadsResource;
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

/** Include or exclude a file's text from the knowledge base / retrieval corpus. */
export async function setUploadKbExcluded(
  id: string,
  value: boolean,
): Promise<void> {
  await api.patch(`/uploads/${id}`, { kbExcluded: value });
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

/* ── Composer attachments controller ──────────────────────────────────────────
   The shared Composer (`~/ui`) owns the attachment chips but can't reach this
   seam, so it takes this controller from the feature layer. Files upload the
   instant they're picked/dropped via the same `/uploads` pipeline as the uploads
   page; the chat message only references the resulting upload ids. The chip
   reflects extraction progress, mirroring the uploads page's poll-while-in-flight
   behavior on a per-attachment basis. */

/** Map an upload's lifecycle to the chip's coarser status. */
function toAttachmentStatus(
  status: UploadStatus,
): ComposerAttachment["status"] {
  if (status === "done") return "ready";
  if (status === "error") return "error";
  return "extracting";
}

/**
 * Build a Composer attachment controller. `attach` uploads each file immediately
 * and tracks it as a chip; a single interval polls any still-extracting upload
 * until it settles. Toggling KB membership and removing are relayed to the seam.
 * Bind once per composer; the poll cleans itself up with the owning component.
 */
export function createComposerAttachments(): ComposerAttachmentsApi {
  const [items, setItems] = createStore<ComposerAttachment[]>([]);
  // The store proxy is itself reactive; the Composer reads it through this
  // accessor so its `For`/derivations track adds, removes, and field changes.
  const accessor: Accessor<ComposerAttachment[]> = () => items;

  const patch = (id: string, fn: (a: ComposerAttachment) => void): void => {
    setItems(
      produce((list) => {
        const a = list.find((x) => x.id === id);
        if (a) fn(a);
      }),
    );
  };

  // Track extraction off the shared uploads *list* — its summaries already carry
  // `status` with no extracted-text decrypt, so a chip's progress costs the same
  // one cheap list read the uploads page already polls, never a per-file detail
  // GET that would decrypt the whole document just to read a status enum.
  const uploads = useUploads();
  const inFlight = () => items.some((a) => a.status === "extracting");

  // Reconcile each still-extracting chip against the freshest list row whenever
  // the list resolves (re-runs after each `refreshUploads()` below). The list is
  // the only tracked dependency; `items` is read untracked so reconciling a chip
  // doesn't re-trigger this effect off its own write.
  createEffect(() => {
    const rows = uploads();
    if (!rows) return;
    const index = new Map(rows.map((u) => [u.id, u]));
    untrack(() => {
      for (const a of items) {
        if (a.status !== "extracting") continue;
        const row = index.get(a.id);
        if (row)
          patch(a.id, (x) => {
            x.status = toAttachmentStatus(row.status);
            x.kbExcluded = row.kbExcluded ?? false;
          });
      }
    });
  });

  // Drive the list refresh only while something is extracting; the interval is
  // created on demand and torn down the moment every chip settles, so an idle
  // composer issues no polling traffic at all.
  let timer: ReturnType<typeof setInterval> | undefined;
  const stopPolling = () => {
    if (timer) {
      clearInterval(timer);
      timer = undefined;
    }
  };
  const ensurePolling = () => {
    if (timer || !inFlight()) return;
    timer = setInterval(() => {
      if (!inFlight()) {
        stopPolling();
        return;
      }
      refreshUploads();
    }, 1500);
  };
  onCleanup(stopPolling);

  const attach = (files: File[]): void => {
    for (const file of files) {
      // A provisional chip id keyed off the uploading file, swapped for the real
      // upload id once the POST resolves. Lets the chip show "UPLOADING" instantly.
      const tempId = `pending-${Date.now()}-${Math.random().toString(36).slice(2)}`;
      setItems(
        produce((list) =>
          list.push({
            id: tempId,
            name: file.name,
            status: "uploading",
            kbExcluded: false,
          }),
        ),
      );
      void uploadFile(file)
        .then((u) => {
          patch(tempId, (x) => {
            x.id = u.id;
            x.name = u.name;
            x.status = toAttachmentStatus(u.status);
            x.kbExcluded = u.kbExcluded ?? false;
          });
          // A still-extracting upload needs the list poll running to settle it.
          ensurePolling();
        })
        .catch(() => patch(tempId, (x) => (x.status = "error")));
    }
  };

  const remove = (id: string): void => {
    setItems((list) => list.filter((a) => a.id !== id));
  };

  const toggleKbExcluded = (id: string): void => {
    const current = items.find((a) => a.id === id);
    if (!current) return;
    const next = !current.kbExcluded;
    patch(id, (x) => (x.kbExcluded = next)); // optimistic echo
    void setUploadKbExcluded(id, next).catch(() =>
      patch(id, (x) => (x.kbExcluded = current.kbExcluded)),
    );
  };

  const clear = (): void => {
    setItems([]);
  };

  return { items: accessor, attach, remove, toggleKbExcluded, clear };
}
