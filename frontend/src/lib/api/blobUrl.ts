import {
  createEffect,
  createResource,
  onCleanup,
  type Resource,
} from "solid-js";
import { api } from "./client";

/**
 * Resolves an auth-gated content path to an object URL suitable for an
 * `<img>` / `<iframe>` `src`. Those elements can't carry a bearer token, so the
 * bytes are fetched through the client and handed over as a blob URL instead.
 * Pass `undefined` to hold (no fetch); the resource stays unresolved.
 *
 * Revocation is driven by the resolved *value*, never from inside the fetcher:
 * every URL we mint is tracked, and once the current one resolves we revoke the
 * rest (superseded or out-of-order fetches) plus everything on cleanup — so a
 * slow earlier fetch can never revoke the URL the view is currently showing
 * (which the old "revoke inside the fetcher" approach did, blanking the image).
 */
export function useAuthedBlobUrl(
  path: () => string | undefined,
): Resource<string | undefined> {
  const minted = new Set<string>();

  const [url] = createResource(path, async (p): Promise<string> => {
    const blob = await api.getBlob(p);
    const objectUrl = URL.createObjectURL(blob);
    minted.add(objectUrl);
    return objectUrl;
  });

  createEffect(() => {
    if (url.state !== "ready") return;
    const current = url();
    for (const u of minted) {
      if (u !== current) {
        URL.revokeObjectURL(u);
        minted.delete(u);
      }
    }
  });

  onCleanup(() => {
    for (const u of minted) URL.revokeObjectURL(u);
    minted.clear();
  });

  return url;
}
