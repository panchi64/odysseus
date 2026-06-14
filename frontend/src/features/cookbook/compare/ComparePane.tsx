import { For, Show, createEffect, createMemo, type JSX } from "solid-js";
import { Combobox, EmptyState, StatusFlag, Text, confirm, toast } from "~/ui";
import { MessageItem } from "~/features/chat";
import {
  decodeModelValue,
  encodeModelValue,
  modelPickerGroups,
} from "~/lib/stores/models";
import type { ComparePane } from "./data";

/** One column of the side-by-side compare: a per-pane model picker and the live
 *  transcript for that model. The transcript reuses the chat turn renderer
 *  (`MessageItem`) wired to this pane's stream, so reasoning, tools, host
 *  commands, approvals, artifacts, and previews all render at full fidelity —
 *  and per-turn actions (regenerate / edit / version / pin / delete / rewind)
 *  operate on this pane's own conversation. */
export function ComparePaneView(props: {
  pane: ComparePane;
  label: string;
}): JSX.Element {
  const stream = () => props.pane.stream;

  // Follow the stream: keep the transcript pinned to the bottom as the in-flight
  // turn grows, but yield the moment the operator scrolls up to read back — only
  // re-pin when they return near the bottom. Without this guard every streamed
  // token would yank a reader who scrolled up straight back down.
  let scrollEl: HTMLDivElement | undefined;
  let pinned = true;
  const onScroll = () => {
    if (!scrollEl) return;
    const distance =
      scrollEl.scrollHeight - scrollEl.scrollTop - scrollEl.clientHeight;
    pinned = distance < 80; // within 80px of the bottom counts as attached
  };
  const tick = createMemo(() => {
    const msgs = stream().messages;
    const last = msgs[msgs.length - 1];
    let n = msgs.length + (last?.content?.length ?? 0);
    for (const b of last?.blocks ?? []) {
      if (b.kind === "thinking" || b.kind === "text") n += b.text.length;
      else n += 1;
    }
    return n;
  });
  createEffect(() => {
    tick();
    if (!pinned) return;
    queueMicrotask(() => {
      if (scrollEl) scrollEl.scrollTop = scrollEl.scrollHeight;
    });
  });
  // A new turn re-attaches the follow, so a just-sent answer is tracked even if
  // the operator had scrolled up during the previous one.
  let wasSending = false;
  createEffect(() => {
    const isSending = stream().sending();
    if (isSending && !wasSending) pinned = true;
    wasSending = isSending;
  });

  const value = () => {
    const sel = props.pane.selection();
    return sel ? encodeModelValue(sel) : "";
  };

  return (
    <div class="flex min-h-0 min-w-0 flex-1 flex-col rounded-ctl border border-line">
      <header class="flex items-center justify-between gap-2 border-b border-line p-2">
        <div class="flex min-w-0 items-center gap-2">
          <Text variant="label" tone="dim">
            {props.label}
          </Text>
          <Combobox
            groups={modelPickerGroups()}
            value={value()}
            onChange={(v) => props.pane.setSelection(decodeModelValue(v))}
            leading="cpu"
            placeholder="NO MODEL"
            searchPlaceholder="Search models…"
            emptyHint="NO MODELS — ADD AN ENDPOINT IN SETTINGS"
            aria-label={`Model for ${props.label}`}
          />
        </div>
        <StatusFlag
          status={stream().sending() ? "info" : "idle"}
          dot={stream().sending()}
          pulse={stream().sending()}
        >
          {stream().sending() ? "STREAMING" : "IDLE"}
        </StatusFlag>
      </header>

      <div
        ref={scrollEl}
        onScroll={onScroll}
        class="min-h-0 flex-1 overflow-y-auto"
      >
        <Show
          when={stream().messages.length}
          fallback={
            <EmptyState
              icon="compare"
              message="NO RESPONSE YET"
              hint="Send a message below to compare this model."
            />
          }
        >
          <For each={stream().messages}>
            {(message) => (
              <MessageItem
                message={message}
                onResolveApproval={stream().resolveApproval}
                onResolveHostCommands={stream().resolveHostCommands}
                onRegenerate={() => void stream().regenerate(message.id)}
                onEditMessage={(id, text) => void stream().edit(id, text)}
                onSwitchVersion={(id, i) => void stream().switchVersion(id, i)}
                onTogglePin={() => void stream().toggleMessagePin(message.id)}
                onRewind={() => void stream().rewind(message.id)}
                onDelete={async () => {
                  if (
                    await confirm({
                      title: "Delete this message?",
                      detail: "This removes it and everything after it.",
                      confirmLabel: "DELETE",
                      tone: "alert",
                    })
                  ) {
                    await stream().removeMessage(message.id);
                    toast.success("Message deleted");
                  }
                }}
              />
            )}
          </For>
        </Show>
      </div>
    </div>
  );
}
