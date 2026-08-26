import {
  For,
  Match,
  Show,
  Switch,
  createSignal,
  onMount,
  type JSX,
} from "solid-js";
import { Button, Chip, Icon, Stack, Text, Textarea, cx } from "~/ui";
import { relativeTime } from "~/lib/format";
import type { ApprovalDecision, ChatMessage, Citation } from "../model";
import { hasLayers as turnHasLayers } from "../blocks";
import type { ViewItem } from "../viewport";
import { CompactionDivider } from "./CompactionDivider";
import { MessageActions, TURN_REVEAL_CLASS } from "./MessageActions";
import { MessageAttachments } from "./MessageAttachments";
import { TurnBlocks } from "./TurnBlocks";
import { TurnProgressRail } from "./TurnProgressRail";

export interface MessageItemProps {
  message: ChatMessage;
  /** Decide a turn's pending approvals (wired from the stream controller). */
  onResolveApproval?: (
    messageId: string,
    decisions: ApprovalDecision[],
  ) => void | Promise<void>;
  /** Decide a turn's pending host-command approvals (terminal blocks). */
  onResolveHostCommands?: (
    messageId: string,
    decisions: ApprovalDecision[],
  ) => void | Promise<void>;
  /** Re-answer this assistant turn with the current model selection. */
  onRegenerate?: () => void;
  /** Re-ask an edited user turn as a new version. */
  onEditMessage?: (id: string, text: string) => void;
  /** Delete this turn and everything after it. */
  onDelete?: () => void;
  /** Rewind the thread to (and including) this turn. */
  onRewind?: () => void;
  /** Switch this turn to a sibling version (branch). */
  onSwitchVersion?: (id: string, index: number) => void;
  /** Pin/unpin this turn (backend-owned flag). */
  onTogglePin?: () => void;
  /** Withdraw this still-queued steering message before the run consumes it. */
  onWithdraw?: () => void;
  /** Rewrite this still-queued steering message in place (it keeps its spot in
   *  the queue) — the queued counterpart of `onEditMessage`. */
  onEditQueued?: (text: string) => void;
  /** Open a View item (a version or the live head) in the side viewport, by key. */
  onOpenInView?: (key: string) => void;
  /** Re-attach to this turn's run after its transport detached (reconnect
   *  budget exhausted) — the run may still be alive server-side. */
  onReattach?: () => void;
  /** Resume a turn a bound stopped by sending a fresh "Continue." turn on the
   *  same conversation. Shown next to the persistent "Stopped:" marker. */
  onContinue?: () => void;
  /** The conversation's consolidated View list — read-only here, so inline
   *  transcript chips (`TurnBlocks`) can show the same version/time/NEW
   *  metadata `ViewTimelineRail` shows for the same item. */
  viewItems?: () => ViewItem[];
  /** The key of the newest View item the operator has seen — items after it in
   *  `viewItems()` render their inline chip tagged NEW. */
  seenKey?: () => string | null;
  /** This turn sits above the newest compaction divider: still in the operator's
   *  transcript, no longer in what the model replays. Rendered as a dim pass over
   *  the whole turn — the divider says it in words, this says it at a glance.
   *  Derived by the transcript (presentation only); a turn can't know it alone. */
  dimmed?: boolean;
}

/** A single chat turn. User turns fill the row with a distinct `surface`
 *  background and right-aligned content; assistant turns sit on the base
 *  background with reasoning, tool calls, then a markdown-formatted answer and a
 *  streaming caret while in flight. A compaction entry is neither — it is a
 *  full-width divider marking where the thread's earlier turns were folded into a
 *  summary, with no actions and no bubble. */
export function MessageItem(props: MessageItemProps): JSX.Element {
  return (
    <div class={cx(props.dimmed && "opacity-50")}>
      <Switch
        fallback={
          <AssistantTurn
            message={props.message}
            onResolveApproval={props.onResolveApproval}
            onResolveHostCommands={props.onResolveHostCommands}
            onRegenerate={props.onRegenerate}
            onDelete={props.onDelete}
            onRewind={props.onRewind}
            onSwitchVersion={props.onSwitchVersion}
            onTogglePin={props.onTogglePin}
            onOpenInView={props.onOpenInView}
            onReattach={props.onReattach}
            onContinue={props.onContinue}
            viewItems={props.viewItems}
            seenKey={props.seenKey}
          />
        }
      >
        <Match when={props.message.role === "compaction"}>
          <CompactionDivider message={props.message} />
        </Match>
        <Match when={props.message.role === "user"}>
          <UserTurn
            message={props.message}
            onEditMessage={props.onEditMessage}
            onDelete={props.onDelete}
            onSwitchVersion={props.onSwitchVersion}
            onTogglePin={props.onTogglePin}
            onWithdraw={props.onWithdraw}
            onEditQueued={props.onEditQueued}
            onContinue={props.onContinue}
          />
        </Match>
      </Switch>
    </div>
  );
}

/** Compact `‹ n/total ›` cycler shown when a turn has sibling versions. */
function VersionCycler(props: {
  message: ChatMessage;
  onSwitchVersion?: (id: string, index: number) => void;
}): JSX.Element {
  const count = () => props.message.versionCount ?? 1;
  const index = () => props.message.versionIndex ?? 0;
  const go = (next: number) => {
    const clamped = Math.max(0, Math.min(count() - 1, next));
    if (clamped !== index()) props.onSwitchVersion?.(props.message.id, clamped);
  };
  return (
    <Show when={count() > 1}>
      <span class="flex items-center gap-0.5">
        <Button
          variant="ghost"
          size="sm"
          leading="chevron-left"
          aria-label="Previous version"
          disabled={index() <= 0}
          onClick={() => go(index() - 1)}
        />
        <Text variant="micro" tone="dim">
          {index() + 1}/{count()}
        </Text>
        <Button
          variant="ghost"
          size="sm"
          leading="chevron-right"
          aria-label="Next version"
          disabled={index() >= count() - 1}
          onClick={() => go(index() + 1)}
        />
      </span>
    </Show>
  );
}

/** Small marker shown in a turn header when the operator has pinned it. */
function PinMarker(props: { message: ChatMessage }): JSX.Element {
  return (
    <Show when={props.message.pinned}>
      <span class="text-nominal" aria-label="Pinned" title="Pinned">
        <Icon name="pin" size={12} />
      </span>
    </Show>
  );
}

/** The persistent "Stopped:" marker for a turn a bound stopped (a time/cancel
 *  bound, a usage/context/loop limit), with a "Continue." button that resumes it by
 *  sending a fresh "Continue." turn. Shown on whichever message carries the turn's
 *  `blocked_reason` — the assistant's answer when one was produced, or the operator's
 *  own message when the bound tripped before any response landed. */
function BlockedFooter(props: {
  detail: string | undefined;
  onContinue?: () => void;
}): JSX.Element {
  return (
    <div class="flex items-center gap-1.5 text-warn">
      <Icon name="warning" size={12} />
      <Text variant="micro" tone="warn">
        Stopped: {props.detail ?? "a run limit was reached"}
      </Text>
      <Show when={props.onContinue}>
        <Button
          variant="ghost"
          size="sm"
          leading="play"
          onClick={() => props.onContinue?.()}
        >
          CONTINUE
        </Button>
      </Show>
    </div>
  );
}

/** Longer than this and the turn collapses behind a SHOW MORE. Twelve lines is
 *  roughly a screenful of composer: enough that a normal question is never clipped,
 *  low enough that a pasted log or spec doesn't cost the whole scrollback. */
const USER_TURN_CLAMP_LINES = 12;

/** A user turn's text: placed right, read left.
 *
 *  The bubble stays right-aligned — that is what marks it as the operator's — but the
 *  text inside is `text-left`, because right-aligned prose with any internal structure
 *  (a list, a pasted snippet, anything with leading indentation) reads as ragged and
 *  wrong. Alignment of the block and alignment of the words are separate decisions and
 *  only the first one carries meaning here.
 *
 *  A long turn clamps to a fixed height with a fade and a SHOW MORE. Presentation-only
 *  state, deliberately not persisted: it is a way of skimming *this* scrollback right
 *  now, not a preference about the message. */
function UserText(props: { text: string }): JSX.Element {
  const [expanded, setExpanded] = createSignal(false);
  const [clampable, setClampable] = createSignal(false);
  let ref: HTMLDivElement | undefined;

  // Measured, not counted: a wrapped long line takes more rows than its newlines
  // suggest, so counting "\n" would leave a wall of text unclamped.
  onMount(() => {
    if (ref) setClampable(ref.scrollHeight > ref.clientHeight + 1);
  });

  return (
    <div class="flex w-full max-w-[80%] flex-col items-end gap-1 self-end">
      <div
        ref={ref}
        class="relative w-full overflow-hidden"
        style={{
          "max-height": expanded()
            ? undefined
            : `calc(${USER_TURN_CLAMP_LINES} * 1.5em)`,
        }}
      >
        <Text
          variant="body"
          tone="bright"
          class="whitespace-pre-wrap break-words text-left"
        >
          {props.text}
        </Text>
        {/* Only while clamped, and only when there is genuinely more below. */}
        <Show when={clampable() && !expanded()}>
          <div class="pointer-events-none absolute inset-x-0 bottom-0 h-6 bg-gradient-to-t from-surface to-transparent" />
        </Show>
      </div>
      <Show when={clampable()}>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded()}
        >
          {expanded() ? "SHOW LESS" : "SHOW MORE"}
        </Button>
      </Show>
    </div>
  );
}

function UserTurn(props: {
  message: ChatMessage;
  onEditMessage?: (id: string, text: string) => void;
  onDelete?: () => void;
  onSwitchVersion?: (id: string, index: number) => void;
  onTogglePin?: () => void;
  onWithdraw?: () => void;
  onEditQueued?: (text: string) => void;
  onContinue?: () => void;
}): JSX.Element {
  const m = () => props.message;
  const [editing, setEditing] = createSignal(false);
  const [draft, setDraft] = createSignal("");
  const startEdit = () => {
    setDraft(m().content);
    setEditing(true);
  };
  const save = () => {
    const text = draft().trim();
    // Route by the bubble's state *at save time*: a still-queued message edits
    // in place on the live run; a delivered one re-asks as a new version (so a
    // bubble injected mid-edit falls through to the normal edit path).
    if (text) {
      if (m().queuedPending) props.onEditQueued?.(text);
      else props.onEditMessage?.(m().id, text);
    }
    setEditing(false);
  };

  return (
    <div class="group flex flex-col items-end gap-1 border-b border-line bg-surface px-4 py-3">
      <div class="flex w-full items-center justify-between gap-2">
        {/* Left: actions reveal on hover. Right: identity + metadata. */}
        <div class="flex items-center gap-2">
          {/* A queued (not-yet-delivered) steering message isn't a real turn yet:
              no delete/pin/version actions — only the edit + withdraw
              affordances on the right. */}
          <Show when={!editing() && !m().queuedPending}>
            <MessageActions
              message={m()}
              onEdit={startEdit}
              onDelete={props.onDelete}
              onTogglePin={props.onTogglePin}
            />
          </Show>
        </div>
        <div class="flex items-center gap-2">
          <Show when={m().queuedPending && !editing()}>
            <Button
              variant="ghost"
              size="sm"
              leading="pen"
              aria-label="Edit queued message"
              onClick={startEdit}
            >
              EDIT
            </Button>
            <Button
              variant="ghost"
              size="sm"
              leading="close"
              aria-label="Withdraw queued message"
              onClick={() => props.onWithdraw?.()}
            >
              WITHDRAW
            </Button>
          </Show>
          <Show when={m().queuedPending}>
            <Text variant="label" tone="warn">
              QUEUED
            </Text>
          </Show>
          <PinMarker message={m()} />
          <VersionCycler
            message={m()}
            onSwitchVersion={props.onSwitchVersion}
          />
          {/* Same reveal as the assistant turn's model/time line: the bubble's
              own alignment and surface already say whose turn this is. */}
          <span class={cx("flex items-center gap-2", TURN_REVEAL_CLASS)}>
            <Text variant="micro" tone="dim">
              {relativeTime(m().createdAt)}
            </Text>
            <Text variant="label" tone="default">
              OPERATOR
            </Text>
          </span>
        </div>
      </div>
      <Show
        when={editing()}
        fallback={
          <>
            <Show when={m().content}>
              <UserText text={m().content} />
            </Show>
            <Show when={m().attachmentIds?.length}>
              <MessageAttachments ids={m().attachmentIds!} />
            </Show>
            {/* Sets the expectation the QUEUED badge alone doesn't: the run hands
                this to the model at its next model call, so a reply already being
                written finishes first and this lands after it — not woven into the
                text mid-sentence. Without saying so, an answer that streams on
                past the message reads as the steering having been ignored. */}
            <Show when={m().queuedPending}>
              <Text variant="micro" tone="dim" class="max-w-[80%] text-right">
                Goes to the model at its next step — after the current reply if
                it finishes first.
              </Text>
            </Show>
            {/* A bound that tripped before any response landed stamps the stop on
                this message (the turn's own prompt) — show the marker + Continue
                here, where the operator's own words sit. */}
            <Show when={m().blocked}>
              <BlockedFooter
                detail={m().blockedDetail}
                onContinue={props.onContinue}
              />
            </Show>
          </>
        }
      >
        <div class="w-full max-w-[80%]">
          <Textarea
            value={draft()}
            rows={3}
            onInput={(e) => setDraft(e.currentTarget.value)}
            aria-label="Edit message"
          />
          <div class="mt-1 flex justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={() => setEditing(false)}>
              CANCEL
            </Button>
            <Button
              variant="primary"
              size="sm"
              disabled={!draft().trim()}
              onClick={save}
            >
              SAVE
            </Button>
          </div>
        </div>
      </Show>
    </div>
  );
}

/** The base domain of a URL (host, minus a leading `www.`) for a compact
 *  citation label — falls back to the raw URL if it doesn't parse. */
function citationHost(url: string): string {
  try {
    return new URL(url).host.replace(/^www\./, "");
  } catch {
    return url;
  }
}

const SOURCES_PREVIEW_COUNT = 3;

/** The web sources a turn's `web_search`/`web_fetch` calls surfaced, as a compact
 *  row of chips beneath the answer — each opens its source in a new tab. Chips
 *  show base domains rather than full titles to stay compact, and collapse behind
 *  a toggle past SOURCES_PREVIEW_COUNT so a research-heavy turn doesn't dominate
 *  the transcript. */
function SourcesRow(props: { citations: Citation[] }): JSX.Element {
  const [expanded, setExpanded] = createSignal(false);
  const hidden = () =>
    Math.max(props.citations.length - SOURCES_PREVIEW_COUNT, 0);
  const shown = () =>
    expanded()
      ? props.citations
      : props.citations.slice(0, SOURCES_PREVIEW_COUNT);

  return (
    <div class="flex flex-wrap items-center gap-2">
      <Text variant="label" tone="dim">
        SOURCES
      </Text>
      <For each={shown()}>
        {(c, i) => (
          <Chip
            onClick={() => window.open(c.url, "_blank", "noopener,noreferrer")}
          >
            [{i() + 1}] {citationHost(c.url)}
          </Chip>
        )}
      </For>
      <Show when={hidden() > 0}>
        <Button
          variant="ghost"
          size="sm"
          leading={expanded() ? "chevron-up" : "chevron-down"}
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded() ? "SHOW LESS" : `+${hidden()} MORE`}
        </Button>
      </Show>
    </div>
  );
}

function AssistantTurn(props: {
  message: ChatMessage;
  onResolveApproval?: MessageItemProps["onResolveApproval"];
  onResolveHostCommands?: MessageItemProps["onResolveHostCommands"];
  onRegenerate?: MessageItemProps["onRegenerate"];
  onDelete?: MessageItemProps["onDelete"];
  onRewind?: MessageItemProps["onRewind"];
  onSwitchVersion?: MessageItemProps["onSwitchVersion"];
  onTogglePin?: MessageItemProps["onTogglePin"];
  onOpenInView?: MessageItemProps["onOpenInView"];
  onReattach?: MessageItemProps["onReattach"];
  onContinue?: MessageItemProps["onContinue"];
  viewItems?: MessageItemProps["viewItems"];
  seenKey?: MessageItemProps["seenKey"];
}): JSX.Element {
  const m = () => props.message;
  // Tri-state: undefined = each layer keeps its own default; true/false = force
  // every layer open/closed at once. Toggling sets the opposite of its last
  // explicit state (first press expands).
  const [forceOpen, setForceOpen] = createSignal<boolean | undefined>(
    undefined,
  );
  const hasLayers = () => turnHasLayers(m().blocks);
  const toggleAll = () => setForceOpen((v) => !v);

  return (
    <div class="group border-b border-line px-4 py-4">
      <div class="mb-2 flex items-center gap-2">
        {/* Which model and when: true of every turn, and so rarely the question
            being asked that always-on it reads as chrome. Revealed by the same
            hover/focus gesture as the actions opposite it. */}
        <span class={cx("flex items-center gap-2", TURN_REVEAL_CLASS)}>
          <Text variant="label" tone="nominal">
            {m().model ?? "ASSISTANT"}
          </Text>
          <Text variant="micro" tone="dim">
            {relativeTime(m().createdAt)}
          </Text>
        </span>
        <PinMarker message={m()} />
        <VersionCycler message={m()} onSwitchVersion={props.onSwitchVersion} />
        <span class="ml-auto">
          <MessageActions
            message={m()}
            onRegenerate={props.onRegenerate}
            onRewind={props.onRewind}
            onDelete={props.onDelete}
            onTogglePin={props.onTogglePin}
            extraItems={
              hasLayers()
                ? [
                    {
                      label: forceOpen() ? "COLLAPSE ALL" : "EXPAND ALL",
                      icon: "layers",
                      onSelect: toggleAll,
                    },
                  ]
                : undefined
            }
          />
        </span>
      </div>

      <Stack gap={3}>
        {/* What's happening now (streaming) / what it took (settled — and only
            while the work log it summarizes is folded away). */}
        <TurnProgressRail
          blocks={m().blocks}
          streaming={m().streaming}
          queued={m().queued}
          collapsed={forceOpen() !== true}
        />
        {/* The turn's ordered, interleaved blocks — the source of truth. */}
        <TurnBlocks
          blocks={m().blocks}
          streaming={m().streaming}
          forceOpen={forceOpen()}
          onResolveApproval={(decisions) =>
            props.onResolveApproval?.(m().id, decisions)
          }
          onResolveHostCommands={(decisions) =>
            props.onResolveHostCommands?.(m().id, decisions)
          }
          onOpenInView={props.onOpenInView}
          viewItems={props.viewItems}
          seenKey={props.seenKey}
        />
        <Show when={m().citations?.length}>
          <SourcesRow citations={m().citations!} />
        </Show>
        <Show when={m().blocked}>
          <BlockedFooter
            detail={m().blockedDetail}
            onContinue={props.onContinue}
          />
        </Show>
        <Show when={m().detached}>
          <div class="flex items-center gap-2 text-alert">
            <Icon name="warning" size={12} />
            <Text variant="micro" tone="alert">
              Connection lost — the response may still be running.
            </Text>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => props.onReattach?.()}
            >
              RECONNECT
            </Button>
          </div>
        </Show>
      </Stack>
    </div>
  );
}
