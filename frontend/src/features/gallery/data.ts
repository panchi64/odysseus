import { createResource, type Resource } from "solid-js";
import type { Album, MediaItem } from "./model";
import { mockAlbums, mockMedia } from "./mocks";

async function fetchAlbums(): Promise<Album[]> {
  return mockAlbums;
}

async function fetchMedia(): Promise<MediaItem[]> {
  return mockMedia;
}

export function useAlbums(): Resource<Album[]> {
  const [data] = createResource(fetchAlbums);
  return data;
}

export function useMedia(): Resource<MediaItem[]> {
  const [data] = createResource(fetchMedia);
  return data;
}
