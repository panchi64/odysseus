import { createResource, createSignal, type Resource } from "solid-js";
import { api, downloadContent } from "~/lib/api";
import type { Album, MediaItem } from "./model";

/* ── Backend DTOs → seam types ────────────────────────────────────────────────
   /gallery and /uploads speak camelCase (CamelModel), so the mappers are near
   identity — they exist only to pin the seam and absorb any future drift. */

interface MediaOut {
  id: string;
  title: string;
  type: "image";
  tags: string[];
  favorite: boolean;
  kbExcluded: boolean;
  albumIds: string[];
  sizeBytes: number;
  createdAt: string;
}

interface AlbumOut {
  id: string;
  name: string;
  count: number;
  system: boolean;
}

function toMedia(dto: MediaOut): MediaItem {
  return {
    id: dto.id,
    title: dto.title,
    type: dto.type,
    tags: dto.tags,
    favorite: dto.favorite,
    kbExcluded: dto.kbExcluded,
    albumIds: dto.albumIds,
    sizeBytes: dto.sizeBytes,
    createdAt: dto.createdAt,
  };
}

function toAlbum(dto: AlbumOut): Album {
  return { id: dto.id, name: dto.name, count: dto.count, system: dto.system };
}

/* ── Media list (the seam) ────────────────────────────────────────────────── */

const [mediaTick, setMediaTick] = createSignal(0);

async function fetchMedia(): Promise<MediaItem[]> {
  const rows = await api.get<MediaOut[]>("/gallery/media");
  return rows.map(toMedia);
}

export function useMedia(): Resource<MediaItem[]> {
  const [data] = createResource(mediaTick, fetchMedia);
  return data;
}

/** Re-pull the media list after a mutation that changed any image. */
export function refetchMedia(): void {
  setMediaTick((n) => n + 1);
}

/* ── Album list (the seam) ────────────────────────────────────────────────── */

const [albumsTick, setAlbumsTick] = createSignal(0);

async function fetchAlbums(): Promise<Album[]> {
  const rows = await api.get<AlbumOut[]>("/gallery/albums");
  return rows.map(toAlbum);
}

export function useAlbums(): Resource<Album[]> {
  const [data] = createResource(albumsTick, fetchAlbums);
  return data;
}

/** Re-pull the album list after a membership/album mutation (counts change). */
export function refetchAlbums(): void {
  setAlbumsTick((n) => n + 1);
}

/* ── Mutations (pure API calls — the screen drives the refetch) ────────────── */

/** Import one image into the gallery via the shared uploads pipeline. */
export async function importImage(file: File): Promise<void> {
  const form = new FormData();
  form.append("file", file, file.name);
  await api.postForm("/uploads", form);
}

/** Hard-delete an image. The backend also detaches it from any chat message that
 *  had it attached, so no conversation strands a dangling reference. */
export async function deleteMedia(id: string): Promise<void> {
  await api.del(`/uploads/${id}`);
}

export async function setFavorite(id: string, value: boolean): Promise<void> {
  await api.patch(`/uploads/${id}`, { favorite: value });
}

/** Include or exclude the image from the knowledge-base / retrieval corpus. */
export async function setKbExcluded(id: string, value: boolean): Promise<void> {
  await api.patch(`/uploads/${id}`, { kbExcluded: value });
}

export async function createAlbum(name: string): Promise<Album> {
  return toAlbum(await api.post<AlbumOut>("/gallery/albums", { name }));
}

export async function renameAlbum(id: string, name: string): Promise<Album> {
  return toAlbum(await api.patch<AlbumOut>(`/gallery/albums/${id}`, { name }));
}

export async function deleteAlbum(id: string): Promise<void> {
  await api.del(`/gallery/albums/${id}`);
}

export async function addToAlbum(
  albumId: string,
  uploadId: string,
): Promise<void> {
  await api.post(`/gallery/albums/${albumId}/items`, { uploadId });
}

export async function removeFromAlbum(
  albumId: string,
  uploadId: string,
): Promise<void> {
  await api.del(`/gallery/albums/${albumId}/items/${uploadId}`);
}

/** Trigger a browser download of the original image bytes (auth-gated). */
export async function downloadImage(id: string, name: string): Promise<void> {
  await downloadContent(`/uploads/${id}/content`, name);
}

/* ── Content paths (fed to useAuthedBlobUrl by the image components) ───────── */

/** Cached WebP thumbnail for grid tiles. */
export const thumbnailPath = (id: string): string => `/uploads/${id}/thumbnail`;

/** Full-resolution image bytes for the lightbox / detail view. Read via the
 *  client (object URL), so the response's disposition is moot. */
export const fullImagePath = (id: string): string => `/uploads/${id}/content`;
