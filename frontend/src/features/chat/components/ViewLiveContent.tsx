import {
  createEffect,
  createSignal,
  onCleanup,
  Show,
  type JSX,
} from "solid-js";
import { api } from "~/lib/api";
import { apiUrl } from "~/lib/config";
import { EmptyState } from "~/ui";
import type { ViewLiveRef } from "../model";
import { SandboxedFrame } from "./SandboxedFrame";

/** How often to ask the backend whether this head is still running. Well under the
 *  sandbox's own idle window, so a warm tab left open notices a reap in a bounded
 *  time rather than only on its next reload. */
const STATUS_POLL_MS = 20_000;

/** The `token` segment of a live head's proxied URL (`/previews/{token}/…`) — the
 *  one thing `/views/live/status` needs to ask whether it's still running. */
function tokenFromUrl(url: string): string | null {
  const match = /^\/previews\/([^/]+)\//.exec(url);
  return match ? match[1] : null;
}

/**
 * Mounts the View's live head — a server the agent started in its sandbox. The
 * backend reverse-proxies it under a token-gated path on the API origin; the token
 * *is* the credential, so the iframe needs no auth header. Sandboxed without
 * `allow-same-origin` so the framed (model-generated) app runs in an opaque origin
 * and can't act as the operator against the API. `live.url` already carries the
 * entry path, so the page renders rather than a directory listing.
 *
 * The sandbox's idle reaper can kill this server out from under the iframe with no
 * event to catch (no run is active at reap time) — the proxy just starts 404ing.
 * Rather than render a dead frame forever, this polls the head's own status (keyed
 * off the token already in `live.url`, no extra plumbing) and swaps to a plain
 * stopped notice the moment the backend confirms it's gone.
 */
export function ViewLiveContent(props: {
  live: ViewLiveRef;
  /** Manual reload nonce — bumping it reloads the running server's page in place. */
  reloadKey: number;
}): JSX.Element {
  const [stopped, setStopped] = createSignal(false);

  createEffect(() => {
    const token = tokenFromUrl(props.live.url);
    setStopped(false);
    if (!token) return; // an unrecognized URL shape — nothing to poll, just render it

    let live = true;
    const check = async (): Promise<void> => {
      try {
        const res = await api.get<{ status: string }>(
          `/views/live/status?token=${encodeURIComponent(token)}`,
        );
        if (live && res.status !== "running") {
          setStopped(true);
          live = false; // verdict reached — stop polling
        }
      } catch {
        // A transient/backend hiccup isn't a verdict — keep the iframe up and
        // retry on the next tick rather than flashing a false "stopped" state.
      }
    };
    void check();
    const interval = setInterval(() => {
      if (live) void check();
    }, STATUS_POLL_MS);

    onCleanup(() => {
      live = false;
      clearInterval(interval);
    });
  });

  return (
    <Show
      when={!stopped()}
      fallback={
        <EmptyState
          icon="warning"
          message="LIVE PREVIEW STOPPED"
          hint="Live preview stopped (sandbox went idle) — ask the assistant to serve it again."
        />
      }
    >
      <SandboxedFrame
        src={apiUrl(props.live.url)}
        title={props.live.title ?? "Live view"}
        reloadKey={props.reloadKey}
      />
    </Show>
  );
}
