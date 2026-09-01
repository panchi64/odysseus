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
import { hostLabel, relativeTime } from "~/lib/format";
import { CONTEXT_OVERFLOW_DETAIL } from "~/lib/stream";
import { selectedModelLabel } from "~/lib/stores/models";
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
  /** Open a new conversation carrying history up to this turn. */
  onFork?: () => void;
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
  /** Fold the thread and then resume it — offered beside Continue on the one stop
   *  Continue cannot clear, a request the provider refused as too large. */
  onCompactAndRetry?: () => void;
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
    // Two nodes, deliberately: `ody-message-in` runs with `animation-fill-mode:
    // both`, and an animated opacity outranks a utility class in the cascade —
    // on one element the entry animation would silently cancel `dimmed`. The
    // outer node owns the dim state, the inner one owns the movement.
    <div class={cx(props.dimmed && "opacity-50")}>
      {/* Fires once per mounted turn, so a message glides up as it arrives and a
          streaming turn never re-animates mid-delta (its root element is not
          recreated). Opening a thread mounts its turns together, so the
          transcript settles in as one movement, not a staggered cascade. */}
      <div class="ody-message-in">
        <Switch
          fallback={
            <AssistantTurn
              message={props.message}
              onResolveHostCommands={props.onResolveHostCommands}
              onRegenerate={props.onRegenerate}
              onDelete={props.onDelete}
              onRewind={props.onRewind}
              onFork={props.onFork}
              onSwitchVersion={props.onSwitchVersion}
              onTogglePin={props.onTogglePin}
              onOpenInView={props.onOpenInView}
              onReattach={props.onReattach}
              onContinue={props.onContinue}
              onCompactAndRetry={props.onCompactAndRetry}
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
              onFork={props.onFork}
              onSwitchVersion={props.onSwitchVersion}
              onTogglePin={props.onTogglePin}
              onWithdraw={props.onWithdraw}
              onEditQueued={props.onEditQueued}
              onContinue={props.onContinue}
              onCompactAndRetry={props.onCompactAndRetry}
            />
          </Match>
        </Switch>
      </div>
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
      {/* `ody-fade-in` rather than a `Reveal` wrapper: this sits in a row of
          inline controls, and a block wrapper would change how it lays out. The
          fade matters because version metadata arrives a round-trip *after* the
          answer settles — the cycler would otherwise pop into a header the
          operator has already started reading. On a turn that mounts with
          siblings it just runs alongside the turn's own entry. */}
      <span class="ody-fade-in flex items-center gap-0.5">
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
 *  own message when the bound tripped before any response landed.
 *
 *  **One stop has a remedy of its own, and it is the one Continue cannot fix.** A turn
 *  the provider refused as too large will be refused again the moment it is resumed, so
 *  Continue alone would offer the operator a button that reliably does nothing. Compact
 *  and retry folds the thread first and then continues — the same pair the chassis
 *  attempts by itself, offered by hand for the case where it could not (compaction off
 *  for the thread, no background model, a fold that freed nothing).
 *
 *  Keyed on the exact detail string the backend exports, which is why the constant is
 *  mirrored rather than matched loosely: the same string arrives live on `run.ended` and
 *  is read back from `blocked_reason` on a cold load, so the control is in the same
 *  place before and after a reload. Anything else keys nothing and reads as a plain
 *  bound. */
function BlockedFooter(props: {
  detail: string | undefined;
  onContinue?: () => void;
  onCompactAndRetry?: () => void;
}): JSX.Element {
  const overflowed = () => props.detail === CONTEXT_OVERFLOW_DETAIL;
  return (
    <div class="flex flex-wrap items-center gap-1.5 text-warn">
      <Icon name="warning" size={12} />
      <Text variant="micro" tone="warn">
        Stopped: {props.detail ?? "a run limit was reached"}
      </Text>
      <Show when={overflowed() && props.onCompactAndRetry}>
        <Button
          variant="ghost"
          size="sm"
          leading="layers"
          onClick={() => props.onCompactAndRetry?.()}
        >
          Compact and retry
        </Button>
      </Show>
      <Show when={props.onContinue}>
        <Button
          variant="ghost"
          size="sm"
          leading="play"
          onClick={() => props.onContinue?.()}
        >
          Continue
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
    // `w-fit`, not `w-full`: the bubble shrinks to its content and only stops at
    // the 80% cap. With `w-full` a three-word prompt still reserved 80% of the
    // column, so short turns read as text floating in the middle of an empty
    // block instead of as a compact message pinned to the right.
    <div class="flex w-fit max-w-[80%] flex-col items-end gap-1 self-end">
      <div
        ref={ref}
        class="relative w-full overflow-hidden"
        style={{
          "max-height": expanded()
            ? undefined
            : `calc(${USER_TURN_CLAMP_LINES} * 1.5em)`,
        }}
      >
        {/* `reading`, not `body`: this is conversation content sitting inches
            from a rendered answer on the prose scale. At chrome size the
            operator's own words read as a caption on the model's. */}
        <Text
          variant="reading"
          tone="bright"
          class="whitespace-pre-wrap break-words text-left"
        >
          {props.text}
        </Text>
        {/* Only while clamped, and only when there is genuinely more below. */}
        <Show when={clampable() && !expanded()}>
          <div class="pointer-events-none absolute inset-x-0 bottom-0 h-6 bg-gradient-to-t from-sunken to-transparent" />
        </Show>
      </div>
      <Show when={clampable()}>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded()}
        >
          {expanded() ? "Show less" : "Show more"}
        </Button>
      </Show>
    </div>
  );
}

function UserTurn(props: {
  message: ChatMessage;
  onEditMessage?: (id: string, text: string) => void;
  onDelete?: () => void;
  onFork?: () => void;
  onSwitchVersion?: (id: string, index: number) => void;
  onTogglePin?: () => void;
  onWithdraw?: () => void;
  onEditQueued?: (text: string) => void;
  onContinue?: () => void;
  onCompactAndRetry?: () => void;
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
    // `bg-sunken`, not `bg-surface`. The operator's turn is told apart from the
    // model's by its fill, and `surface` is pure white on Paper — the same value
    // as the page — so on light the two voices were indistinguishable while on
    // dark they read fine. `sunken` is the token that carries a *transcript
    // fill* in both modes rather than a panel's.
    <div class="group flex flex-col items-end gap-1 bg-sunken px-4 py-3">
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
              onFork={props.onFork}
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
              Edit
            </Button>
            <Button
              variant="ghost"
              size="sm"
              leading="close"
              aria-label="Withdraw queued message"
              onClick={() => props.onWithdraw?.()}
            >
              Withdraw
            </Button>
          </Show>
          <Show when={m().queuedPending}>
            <Text variant="label" tone="warn">
              Queued
            </Text>
          </Show>
          <PinMarker message={m()} />
          <VersionCycler
            message={m()}
            onSwitchVersion={props.onSwitchVersion}
          />
          {/* The TIME reveals; the NAME stays. The row is already there holding
              the state markers, so hiding the name buys back no space — it just
              makes the operator hover to learn who said what. It is set `dim` at
              `label` size so it labels the turn without competing with it. */}
          <span class={cx("flex items-center gap-2", TURN_REVEAL_CLASS)}>
            <Text variant="micro" tone="dim">
              {relativeTime(m().createdAt)}
            </Text>
          </span>
          <Text variant="label" tone="dim">
            Operator
          </Text>
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
                onCompactAndRetry={props.onCompactAndRetry}
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
              Cancel
            </Button>
            <Button
              variant="primary"
              size="sm"
              disabled={!draft().trim()}
              onClick={save}
            >
              Save
            </Button>
          </div>
        </div>
      </Show>
    </div>
  );
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
        Sources
      </Text>
      <For each={shown()}>
        {(c, i) => (
          <Chip
            onClick={() => window.open(c.url, "_blank", "noopener,noreferrer")}
          >
            [{i() + 1}] {hostLabel(c.url)}
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
          {expanded() ? "Show less" : `+${hidden()} MORE`}
        </Button>
      </Show>
    </div>
  );
}

function AssistantTurn(props: {
  message: ChatMessage;
  onResolveHostCommands?: MessageItemProps["onResolveHostCommands"];
  onRegenerate?: MessageItemProps["onRegenerate"];
  onDelete?: MessageItemProps["onDelete"];
  onRewind?: MessageItemProps["onRewind"];
  onFork?: MessageItemProps["onFork"];
  onSwitchVersion?: MessageItemProps["onSwitchVersion"];
  onTogglePin?: MessageItemProps["onTogglePin"];
  onOpenInView?: MessageItemProps["onOpenInView"];
  onReattach?: MessageItemProps["onReattach"];
  onContinue?: MessageItemProps["onContinue"];
  onCompactAndRetry?: MessageItemProps["onCompactAndRetry"];
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

  /** Who is speaking: the model that produced the turn.
   *
   *  A turn records its own model, and once the run settles the backend's is
   *  adopted, so that is the answer almost always. The gap is the *first* turn of
   *  a session: the optimistic bubble is stamped from the `main` binding, and if
   *  the operator types and sends before `/models/roles` has resolved there is
   *  nothing to stamp it with — the turn streamed in labelled "Assistant" and
   *  only became the model's name once it ended.
   *
   *  So a streaming turn with no recorded model falls back to the live binding,
   *  which is *what is running* — the same fact from the same source, arriving a
   *  beat later. A settled turn never does: an old turn whose model the backend
   *  didn't record was not necessarily run on today's pick, and naming it would
   *  be a guess wearing the same type as a fact.
   *
   *  Last resort is `LLM`, not `Assistant`. "Assistant" is the wire role, and
   *  putting a protocol word where a model name goes reads as the product not
   *  knowing what it is running. */
  const modelLabel = (): string => {
    const recorded = m().model;
    if (recorded) return recorded;
    return (m().streaming ? selectedModelLabel() : "") || "LLM";
  };

  return (
    <div class="group px-4 py-4">
      <div class="mb-2 flex items-center gap-2">
        {/* WHICH MODEL stays; WHEN reveals. Which model answered is the one
            piece of turn metadata that changes between turns and changes how the
            answer should be read, so it is worth a permanent line — and this row
            already exists to hold the state markers, so keeping it costs no
            space. It is `dim`, not `nominal`: the accent made a label louder
            than the answer under it, and green here means nothing (§5 — color
            carries meaning or stays away). */}
        <Text variant="label" tone="dim">
          {modelLabel()}
        </Text>
        <span class={cx("flex items-center gap-2", TURN_REVEAL_CLASS)}>
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
            onFork={props.onFork}
            onDelete={props.onDelete}
            onTogglePin={props.onTogglePin}
            extraItems={
              hasLayers()
                ? [
                    {
                      label: forceOpen() ? "Collapse all" : "Expand all",
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
        {/* What's happening now. What it took, once settled, is the work log's
            own header — see `WorkLogHeader`. */}
        <TurnProgressRail
          blocks={m().blocks}
          streaming={m().streaming}
          queued={m().queued}
        />
        {/* The turn's ordered, interleaved blocks — the source of truth. */}
        <TurnBlocks
          blocks={m().blocks}
          streaming={m().streaming}
          forceOpen={forceOpen()}
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
            onCompactAndRetry={props.onCompactAndRetry}
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
              Reconnect
            </Button>
          </div>
        </Show>
      </Stack>
    </div>
  );
}
