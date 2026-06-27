import { type JSX } from "solid-js";
import { apiUrl } from "~/lib/config";
import type { ViewLiveRef } from "../model";
import { SandboxedFrame } from "./SandboxedFrame";

/**
 * Mounts the View's live head — a server the agent started in its sandbox. The
 * backend reverse-proxies it under a token-gated path on the API origin; the token
 * *is* the credential, so the iframe needs no auth header. Sandboxed without
 * `allow-same-origin` so the framed (model-generated) app runs in an opaque origin
 * and can't act as the operator against the API. `live.url` already carries the
 * entry path, so the page renders rather than a directory listing.
 */
export function ViewLiveContent(props: {
  live: ViewLiveRef;
  reloadKey?: number;
}): JSX.Element {
  return (
    <SandboxedFrame
      src={apiUrl(props.live.url)}
      title={props.live.title ?? "Live view"}
      reloadKey={props.reloadKey}
    />
  );
}
