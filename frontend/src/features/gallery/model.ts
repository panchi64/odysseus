/** Gallery feature data contracts. */

export type MediaType = "image" | "video";

export interface MediaItem {
  id: string;
  title: string;
  type: MediaType;
  tags: string[];
  favorite: boolean;
  album: string;
  sizeBytes: number;
  createdAt: string;
}

export interface Album {
  id: string;
  name: string;
  count: number;
}
