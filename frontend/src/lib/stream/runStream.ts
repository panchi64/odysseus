/**
 * Consume a run's Server-Sent Events stream.
 *
 * Uses `fetch` + a body reader rather than the native `EventSource`, because we
 * need a bearer header and a `Last-Event-ID` *request* header — neither of which
 * `EventSource` supports. Frames are parsed from the `text/event-stream` body;
 * the last seen `seq` drives reconnect-with-replay if the transport drops before
 * a terminal event. Resolves when the run ends, the caller aborts, or reconnects
 * are exhausted.
 */
import { API_BASE } from "~/lib/config";
import { getToken } from "~/lib/api/token";
import { isTerminal, type RunEvent } from "./events";

export interface RunStreamOptions {
  onEvent: (event: RunEvent) => void;
  signal?: AbortSignal;
  /** Resume from after this seq (e.g. when re-opening a known run). */
  fromSeq?: number;
}

const MAX_RECONNECTS = 6;
const RECONNECT_DELAY_MS = 500;

function delay(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const id = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => {
      clearTimeout(id);
      resolve();
    });
  });
}

/** Parse one SSE frame (the lines between blank lines) into an event. */
function parseFrame(frame: string): RunEvent | null {
  const data = frame
    .split("\n")
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trimStart())
    .join("\n");
  if (!data) return null;
  try {
    return JSON.parse(data) as RunEvent;
  } catch {
    return null;
  }
}

export async function streamRun(
  runId: string,
  { onEvent, signal, fromSeq }: RunStreamOptions,
): Promise<void> {
  let lastSeq: number | null = fromSeq ?? null;
  let failures = 0;

  while (!signal?.aborted) {
    try {
      const headers: Record<string, string> = { Accept: "text/event-stream" };
      const token = getToken();
      if (token) headers["Authorization"] = `Bearer ${token}`;
      if (lastSeq != null) headers["Last-Event-ID"] = String(lastSeq);

      const res = await fetch(`${API_BASE}/runs/${runId}/events`, {
        headers,
        credentials: "omit",
        signal,
      });
      if (res.status === 404) return; // run is gone — nothing to stream
      if (!res.ok || !res.body) throw new Error(`stream HTTP ${res.status}`);

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let sep: number;
        while ((sep = buffer.indexOf("\n\n")) >= 0) {
          const frame = buffer.slice(0, sep);
          buffer = buffer.slice(sep + 2);
          const event = parseFrame(frame);
          if (!event) continue;
          failures = 0; // a real frame resets the reconnect budget
          lastSeq = event.seq;
          onEvent(event);
          if (isTerminal(event)) return;
        }
      }
      // Body ended without a terminal event → the connection dropped; reconnect
      // from lastSeq to replay anything missed.
    } catch (err) {
      if (signal?.aborted) return;
      failures += 1;
      if (failures > MAX_RECONNECTS) throw err;
      await delay(RECONNECT_DELAY_MS, signal);
    }
  }
}
