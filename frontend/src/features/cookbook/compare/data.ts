/** Side-by-side compare — the data seam for the Cookbook COMPARE tab.
 *
 *  Compare is a thin *view* over the chat engine: each pane is one ordinary chat
 *  conversation pinned to its own model, and a comparison is just the same prompt
 *  fanned to both. No orchestration lives here — every run's lifecycle, tool
 *  dispatch, approval gating, and persistence is backend-owned through the chat
 *  stream controller (`POST /chat` → run SSE). This file only wires two of those
 *  controllers together and broadcasts one prompt to both.
 *
 *  The pane conversations are created **ephemeral**: real, resumable threads the
 *  backend deliberately keeps out of the chat listing (they're scratch, not saved
 *  history). */

import {
  createEffect,
  createMemo,
  createSignal,
  onCleanup,
  type Accessor,
} from "solid-js";
import { api } from "~/lib/api";
import { createChatStream } from "~/features/chat";
import {
  effectiveSelection,
  modelGroups,
  type ModelSelection,
} from "~/lib/stores/models";

export interface ComparePane {
  /** The model this pane's turns run on — locally owned, not the global picker. */
  selection: Accessor<ModelSelection | null>;
  setSelection: (sel: ModelSelection | null) => void;
  /** The ephemeral conversation this pane is bound to; null until the first send. */
  conversationId: Accessor<string | null>;
  /** The live chat stream — one backend Run per turn. */
  stream: ReturnType<typeof createChatStream>;
  /** Send a turn on this pane, tracking it so teardown can await it settling. */
  send: (text: string) => void;
  /** Cancel and return to a fresh ephemeral conversation (keeps the model pick). */
  reset: () => void;
}

export interface CompareController {
  panes: readonly [ComparePane, ComparePane];
  /** Fan the prompt to both panes — one message, two models. */
  send: (text: string) => void;
  /** Cancel both in-flight runs. */
  cancel: () => Promise<void>;
  /** Clear both transcripts and start fresh conversations (models kept). */
  reset: () => void;
  /** True while either pane is streaming. */
  sending: Accessor<boolean>;
  /** True once both panes have a model selected (a send is possible). */
  ready: Accessor<boolean>;
  /** True once either pane has produced a turn (a comparison is underway). */
  started: Accessor<boolean>;
}

/** Every selectable model across all endpoints, flattened — the pool the pane
 *  defaults draw from before the operator picks. */
function flatChoices(): ModelSelection[] {
  return modelGroups().flatMap((g) =>
    g.choices.map((c) => ({ endpointId: c.endpointId, model: c.model })),
  );
}

function sameSelection(
  a: ModelSelection | null,
  b: ModelSelection | null,
): boolean {
  return !!a && !!b && a.endpointId === b.endpointId && a.model === b.model;
}

/** One pane: a locally-owned model pick plus a chat stream bound to a fresh
 *  ephemeral conversation. Seeds its model from `defaultSelection` until the
 *  operator makes an explicit choice (models discover asynchronously, so the
 *  default lands once discovery resolves). */
function createComparePane(
  defaultSelection: () => ModelSelection | null,
): ComparePane {
  const [selection, setSelectionRaw] = createSignal<ModelSelection | null>(
    null,
  );
  // Seed from the computed default until the pane is *committed* — the operator
  // picks a model, or a comparison turn is sent on it. After that the default
  // must not reseed the pane out from under the operator (e.g. the global picker
  // changing elsewhere while a comparison is open would otherwise swap the model).
  let committed = false;
  createEffect(() => {
    if (committed) return;
    const def = defaultSelection();
    if (def) setSelectionRaw(def);
  });
  const setSelection = (sel: ModelSelection | null) => {
    committed = true;
    setSelectionRaw(sel);
  };

  const [conversationId, setConversationId] = createSignal<string | null>(null);
  const stream = createChatStream(() => undefined, conversationId, {
    ephemeral: true,
    selection,
    onConversationStarted: setConversationId,
  });

  // Track the in-flight turn so teardown can wait for it to settle. A new turn's
  // backend conversation id is only adopted in the run's `finally`; tearing down
  // before that resolves would either miss the id (orphan) or fight the late
  // re-bind, so reset/cleanup await this first.
  let inflight: Promise<void> | null = null;
  const send = (text: string) => {
    committed = true; // sending locks the pane's model for this comparison
    inflight = stream.send(text).finally(() => {
      inflight = null;
    });
  };

  // Hard-delete the scratch thread on the backend. Compare conversations are
  // throwaway, so discarding one removes it for real rather than leaving a hidden
  // orphan behind. Best-effort: a failed delete just leaves a listing-hidden row.
  const discard = (id: string | null) => {
    if (id) void api.del(`/conversations/${id}`).catch(() => {});
  };

  // Stop the live run, let its bookkeeping settle so the conversation id is final,
  // then clear the pane and delete the scratch thread. Awaiting the in-flight run
  // is what makes the id stable: without it the run's `finally` re-binds the pane
  // to the conversation we just deleted (and the next send would 404), or — on a
  // first turn whose id hasn't been adopted yet — the discard misses it entirely.
  const teardown = async () => {
    await stream.cancel();
    if (inflight) await inflight.catch(() => {});
    const id = conversationId();
    setConversationId(null);
    discard(id);
  };

  const reset = () => void teardown();
  // Leaving the compare surface discards its scratch threads too — same teardown,
  // triggered by unmount instead of the button. A detached promise still runs to
  // completion on client-side navigation; only a hard tab-close can't be caught.
  onCleanup(() => void teardown());

  return { selection, setSelection, conversationId, stream, send, reset };
}

export function createCompareController(): CompareController {
  const choices = createMemo(flatChoices);
  // Pane A defaults to the operator's active model; pane B to the first model
  // that differs from A, so the two panes start on distinct models when possible.
  const defaultA = createMemo<ModelSelection | null>(
    () => effectiveSelection() ?? choices()[0] ?? null,
  );
  const defaultB = createMemo<ModelSelection | null>(() => {
    const all = choices();
    const a = defaultA();
    return all.find((c) => !sameSelection(c, a)) ?? a ?? null;
  });

  const paneA = createComparePane(defaultA);
  const paneB = createComparePane(defaultB);
  const panes = [paneA, paneB] as const;

  const send = (text: string) => {
    if (!text.trim()) return;
    for (const p of panes) p.send(text);
  };
  const cancel = () =>
    Promise.all(panes.map((p) => p.stream.cancel())).then(() => undefined);
  const reset = () => {
    for (const p of panes) p.reset();
  };

  const sending = createMemo(() => panes.some((p) => p.stream.sending()));
  const ready = createMemo(() => panes.every((p) => p.selection() !== null));
  const started = createMemo(() =>
    panes.some((p) => p.stream.messages.length > 0),
  );

  return { panes, send, cancel, reset, sending, ready, started };
}
