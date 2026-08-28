/** The aggregate platform status — a pure derivation over the existing presentation
 *  echoes, with no state of its own. Used to tint the favicon (see `app/useFavicon`),
 *  and reusable for any future system-status surface.
 *
 *  Precedence is error > busy > ready: a lost backend or a failed run reads as down even
 *  mid-stream, since that's the more urgent signal. */
import { chatBusy, runErrored } from "./chatActivity";
import { backendReachable } from "./connectivity";

export type PlatformStatus = "ready" | "busy" | "error";

export function platformStatus(): PlatformStatus {
  if (!backendReachable() || runErrored()) return "error";
  if (chatBusy()) return "busy";
  return "ready";
}
