import { api } from "./client";

/**
 * Trigger a browser "save as" for an auth-gated content path. A bare anchor can't
 * carry the bearer token, so the bytes are fetched through the client and handed to
 * a temporary object URL. The URL is revoked on a delayed timer — not synchronously
 * after `click()` — because some browsers (Firefox/Safari) start the download
 * asynchronously and would otherwise read an already-revoked blob (an empty file).
 */
export async function downloadContent(
  path: string,
  filename: string,
): Promise<void> {
  const blob = await api.getBlob(path);
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}
