/**
 * Following the stream — the transcript's one piece of genuinely stateful behaviour.
 *
 * Keep the view pinned to the bottom while an answer arrives, yield the moment the operator
 * scrolls up to read back, and re-attach when they scroll near the bottom again. A floating
 * control jumps back down once they have scrolled far up.
 *
 * **Why a tick rather than a message count.** A turn streams for a long time without the
 * message list ever changing length: tokens land inside the last message's blocks. So the
 * follow effect is driven by a memo that sums everything that can grow — answer and
 * reasoning text, a tool's args/result/status, a host command's output — and re-runs on
 * every fragment rather than only when a turn starts or ends. The exact number is
 * meaningless; only that it changes matters.
 *
 * **Why `pinned` is untracked in the effect.** Only *new content* may scroll the view.
 * Reading `pinned` reactively would make re-attaching (by scrolling down) snap the view
 * itself, which takes the scroll away from the operator at the moment they were using it;
 * the next arriving fragment catches up instead.
 */

import {
  createEffect,
  createMemo,
  createSignal,
  onCleanup,
  untrack,
} from "solid-js";
import type { ChatMessage } from "./model";

/** Within this many pixels of the bottom counts as still attached. */
const ATTACHED_PX = 80;
/** Past roughly one screenful the jump-to-latest control appears. */
const JUMP_PX = 240;

/**
 * Everything in the in-flight turn that can grow, added up.
 *
 * Pure and exported so the one thing that can silently break — a block kind whose
 * *mutations* aren't counted — is checkable without a DOM. The exact number is
 * meaningless; only that it changes when the turn does.
 *
 * **A block kind whose fields are filled in later needs a case of its own.** The
 * fallback arm adds a flat 1, which covers a block that arrives complete and never
 * changes again, and covers nothing else: a `review.completed` filling in the verdict on
 * a row `review.started` already pushed leaves the sum untouched, and the transcript sits
 * still while the row it is pinned to the bottom of grows underneath the fold.
 */
export function streamTick(messages: ChatMessage[]): number {
  const last = messages[messages.length - 1];
  if (!last) return messages.length;
  let n = messages.length + (last.content?.length ?? 0);
  for (const b of last.blocks ?? []) {
    switch (b.kind) {
      case "thinking":
      case "text":
        n += b.text.length;
        break;
      case "tool":
        n +=
          b.tool.status.length +
          b.tool.args.length +
          (b.tool.result?.length ?? 0) +
          (b.tool.error?.length ?? 0);
        break;
      case "host_command":
        n +=
          b.command.phase.length +
          (b.command.stdout?.length ?? 0) +
          (b.command.stderr?.length ?? 0);
        break;
      case "review":
        // The row opens on `review.started` with only a summary and fills in on
        // `review.completed` — a mutation, not a push — so every field the verdict
        // arrives in has to be part of the sum or the expanded row never scrolls
        // into view.
        n +=
          b.review.summary.length +
          (b.review.decision?.length ?? 0) +
          (b.review.stage?.length ?? 0) +
          (b.review.reason?.length ?? 0) +
          (b.review.risk?.length ?? 0) +
          (b.review.authorization?.length ?? 0) +
          (b.review.correctness?.length ?? 0);
        break;
      case "context":
        // Pushed complete, but its text is what sets the row's height when the fold
        // is open — counting it keeps a long injection from landing unnoticed.
        n += b.injection.text.length;
        break;
      default:
        n += 1; // approval / view chips: a new block is enough
    }
  }
  return n;
}

export interface TranscriptFollow {
  /** `ref` for the scrolling transcript container. */
  ref: (el: HTMLDivElement) => void;
  /** `onScroll` for the same container. */
  onScroll: () => void;
  /** True once the operator has scrolled far enough up to want a way back. */
  showJump: () => boolean;
  /** Re-attach the follow and scroll to the newest turn. */
  jumpToLatest: () => void;
  /** The container itself, for the keymap's focus targets. */
  element: () => HTMLDivElement | undefined;
}

export function createTranscriptFollow(source: {
  messages: ChatMessage[];
  sending: () => boolean;
  /** The open thread; a switch re-attaches and jumps to the latest message. */
  conversationId: () => string | null;
}): TranscriptFollow {
  let scrollEl: HTMLDivElement | undefined;
  const [pinned, setPinned] = createSignal(true);
  const [showJump, setShowJump] = createSignal(false);

  // At most one scroll per frame.
  //
  // `scrollTop = scrollHeight` reads a value the browser can only answer by laying the
  // whole transcript out, then writes back into that same layout — so scheduling one per
  // *token* made every fragment of a long answer force a synchronous reflow of every
  // turn above it. A frame is the finest granularity the operator can perceive anyway,
  // and tokens arrive several to a frame, so coalescing here costs nothing visible and
  // takes the flush off the delta path.
  let frame: number | null = null;
  const followBottom = () => {
    if (frame !== null) return;
    frame = requestAnimationFrame(() => {
      frame = null;
      if (scrollEl) scrollEl.scrollTop = scrollEl.scrollHeight;
    });
  };
  onCleanup(() => {
    if (frame !== null) cancelAnimationFrame(frame);
  });
  const jumpToLatest = () => {
    setPinned(true);
    setShowJump(false);
    followBottom();
  };
  const onScroll = () => {
    if (!scrollEl) return;
    const distance =
      scrollEl.scrollHeight - scrollEl.scrollTop - scrollEl.clientHeight;
    setPinned(distance < ATTACHED_PX);
    setShowJump(distance > JUMP_PX);
  };

  // Ticks on every fragment that grows the in-flight turn, so the follow effect
  // re-runs as content streams in, not only when a message is added.
  const tick = createMemo(() => streamTick(source.messages));

  createEffect(() => {
    tick();
    // untrack(pinned): only new content drives a scroll, so re-attaching by
    // scrolling down doesn't itself snap — the next fragment catches up.
    if (untrack(pinned)) followBottom();
  });

  // The operator initiating a turn (send / regenerate / edit) re-attaches the
  // follow, so the new answer is tracked even if they had scrolled up.
  let wasSending = false;
  createEffect(() => {
    const sending = source.sending();
    if (sending && !wasSending) jumpToLatest();
    wasSending = sending;
  });

  // Switching threads re-attaches and jumps to the latest message.
  createEffect(() => {
    source.conversationId();
    jumpToLatest();
  });

  return {
    ref: (el) => {
      scrollEl = el;
    },
    onScroll,
    showJump,
    jumpToLatest,
    element: () => scrollEl,
  };
}
