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

import { createEffect, createMemo, createSignal, untrack } from "solid-js";
import type { ChatMessage } from "./model";

/** Within this many pixels of the bottom counts as still attached. */
const ATTACHED_PX = 80;
/** Past roughly one screenful the jump-to-latest control appears. */
const JUMP_PX = 240;

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

  const scrollToBottom = () => {
    if (scrollEl) scrollEl.scrollTop = scrollEl.scrollHeight;
  };
  const jumpToLatest = () => {
    setPinned(true);
    setShowJump(false);
    queueMicrotask(scrollToBottom);
  };
  const onScroll = () => {
    if (!scrollEl) return;
    const distance =
      scrollEl.scrollHeight - scrollEl.scrollTop - scrollEl.clientHeight;
    setPinned(distance < ATTACHED_PX);
    setShowJump(distance > JUMP_PX);
  };

  // Ticks on every fragment that grows the in-flight turn — answer + reasoning
  // tokens, tool args/result/status, and host-command output — so the follow
  // effect re-runs as content streams in, not only when a message is added.
  const streamTick = createMemo(() => {
    const last = source.messages[source.messages.length - 1];
    if (!last) return source.messages.length;
    let n = source.messages.length + (last.content?.length ?? 0);
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
        default:
          n += 1; // approval / view chips: a new block is enough
      }
    }
    return n;
  });

  createEffect(() => {
    streamTick();
    // untrack(pinned): only new content drives a scroll, so re-attaching by
    // scrolling down doesn't itself snap — the next fragment catches up.
    if (untrack(pinned)) queueMicrotask(scrollToBottom);
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
