import {
  For,
  Show,
  createEffect,
  createMemo,
  createSignal,
  type JSX,
} from "solid-js";
import {
  Collapse,
  Icon,
  REVEAL_BASE,
  StatusFlag,
  Text,
  copyToClipboard,
} from "~/ui";
import { num } from "~/lib/format";
import type { ToolInvocation } from "../model";
import { toolPresentation } from "../toolPresentation";
import { ProcessRow, Sep } from "./ProcessRow";

/** The family glyph carries the call's state as well as its kind, so a column of
 *  rows reads at a glance by shape and tone before a word is parsed.
 *
 *  This is now one of only two things that report a running call — the other is
 *  the lit rail beside it. A single call used to say "running" five ways at once:
 *  the turn's tempo line, the rail's light, this glyph, a RUNNING flag at the far
 *  right, and a throbber in the middle of the row. Five dialects of one fact is
 *  what made a turn read as a console dump, and it spent the accent budget (§5)
 *  on the most ambient state there is. */
const iconTone: Record<ToolInvocation["status"], string> = {
  running: "text-info",
  ok: "text-dim",
  error: "text-alert",
};

/** The elapsed figure is rendered whether or not it has landed, so the copy button
 *  beside it doesn't jump sideways the moment a call returns.
 *
 *  Six characters, not five: `num(s, 2)` plus the `S` suffix is `0.38S` for a fast
 *  call but `12.34S` for anything over ten seconds, and a shell command or a
 *  research call is routinely over ten seconds. Reserving five put the shift back
 *  exactly where the reservation was supposed to remove it. (A call over 100s
 *  still gains a character; at that point the operator has not had a pointer
 *  resting on the row for two minutes.) */
const ELAPSED_WIDTH = "min-w-[6ch]";

/** Inline record of a single tool invocation inside an assistant message.
 *
 *  The collapsed row is `glyph · Label · what it was about · what came back` —
 *  the namespaced registry name (`files_read_file`) and the full argument dump
 *  move into the expanded body, where an operator who wants them is already
 *  looking. A turn is a dozen of these rows, and the row has to be scannable
 *  without being read.
 *
 *  **Only failure gets a word.** `StatusFlag` renders for `error` and nothing
 *  else. §10.5 gives warn/alert the accent on the label precisely because those
 *  are the two states that must interrupt; OK and Running are ambient, already
 *  said by the glyph and the rail, and a row that announces its own success on
 *  every line is a row that has stopped meaning anything. Colour is never the
 *  sole carrier of the failure either (§12) — the word "Failed" is there beside
 *  the alert-toned glyph.
 *
 *  `open` makes expand/collapse controlled (expand-all/collapse-all); when
 *  undefined the card keeps its default behavior (auto-open on error). */
export function ToolCallCard(props: {
  tool: ToolInvocation;
  open?: boolean;
}): JSX.Element {
  // Auto-expand error cards so the reason is immediately visible.
  const [open, setOpen] = createSignal(props.tool.status === "error");
  createEffect(() => {
    if (props.open !== undefined) setOpen(props.open);
  });
  const shown = createMemo(() => toolPresentation(props.tool.name));
  // The salient argument when one stood out, else the full summary — never
  // nothing, so a row is always about something.
  const detail = () => props.tool.detail ?? props.tool.args;
  // Copy the most useful payload available: result, else error, else the args.
  const copyTool = (e: MouseEvent): void => {
    e.stopPropagation();
    copyToClipboard(
      props.tool.result ?? props.tool.error ?? props.tool.args,
      "Tool result",
    );
  };
  return (
    <div class="group/tool overflow-hidden rounded-panel bg-surface shadow-1">
      <ProcessRow
        open={open()}
        onToggle={() => setOpen((v) => !v)}
        icon={shown().icon}
        iconClass={iconTone[props.tool.status]}
        label={shown().label}
        title={props.tool.name}
        class="hover:bg-raised"
        trailing={
          <>
            {/* Rendered unconditionally at a fixed width, holding a hard space
                until the figure exists. A `Show` here meant the whole cluster
                grew by five characters the instant a call returned, nudging the
                copy button sideways under a pointer already on it. */}
            <Text
              variant="micro"
              tone="dim"
              class={`${ELAPSED_WIDTH} text-right tabular-nums`}
            >
              {props.tool.elapsedMs === undefined
                ? " "
                : `${num(props.tool.elapsedMs / 1000, 2)}S`}
            </Text>
            <Show when={props.tool.status === "error"}>
              <StatusFlag status="alert">Failed</StatusFlag>
            </Show>
            {/* Running has no visible word by design — the rail's light and the
                glyph's tone carry it, and that is the whole point of thinning the
                chorus. But both of those are COLOUR, and §12 does not allow an
                accent to be the sole carrier of a state. With parallel calls the
                turn's tempo line only says "Running 3 tools", so without this a
                screen reader cannot tell which of six identical-reading rows is
                still out. Costs nothing visually and restores the fact. */}
            <Show when={props.tool.status === "running"}>
              <span class="sr-only">Running</span>
            </Show>
            <button
              type="button"
              aria-label="Copy tool result"
              onClick={copyTool}
              class={`${REVEAL_BASE} text-dim hover:text-bright group-hover/tool:opacity-100`}
            >
              <Icon name="copy" size={12} />
            </button>
          </>
        }
      >
        <Show
          when={props.tool.status === "running" && props.tool.progress}
          fallback={
            <Show when={detail()}>
              <Sep />
              <Text variant="micro" tone="dim" class="min-w-0 truncate">
                {detail()}
              </Text>
            </Show>
          }
        >
          <Sep />
          {/* A progress note is information — what the wait is actually doing —
              not a restatement of "running", so it survives the cull. */}
          <Text variant="micro" tone="info" class="min-w-0 truncate">
            {props.tool.progress}
          </Text>
        </Show>
        <Show when={props.tool.status === "ok" && props.tool.outcome}>
          <Sep />
          <Text variant="micro" tone="default" class="min-w-0 truncate">
            {props.tool.outcome}
          </Text>
        </Show>
      </ProcessRow>
      {/* What the call saw, on the card rather than behind it: a screenshot is the
          whole point of the call that took it, and a picture the operator has to
          expand a row to find is a picture they will not look at. It sits *outside*
          the Collapse and grows when the card opens, so the bytes are in the DOM once
          — at rest it is a strip tall enough to recognise the page, opened it is the
          frame at the card's full width. */}
      <Show when={props.tool.images?.length}>
        <div class="flex flex-col gap-1 px-2 pb-1.5">
          <For each={props.tool.images}>
            {(image, index) => (
              <img
                /* Top-anchored: a page is recognised by its header, so a strip that
                   cropped from the middle would show the operator the least
                   identifying part of it. */
                class="w-full rounded-ctl border border-line object-cover object-top"
                classList={{ "max-h-28": !open() }}
                src={`data:${image.mediaType};base64,${image.data}`}
                alt={`What ${props.tool.name} saw${
                  (props.tool.images?.length ?? 0) > 1 ? `, ${index() + 1}` : ""
                }`}
              />
            )}
          </For>
        </div>
      </Show>
      <Collapse open={open()}>
        <div class="flex flex-col gap-1 px-2 py-1.5">
          {/* The registry name and every argument — what the collapsed row trades
              away for scannability, restored the moment the operator asks.
              Height-capped and scrollable: `formatArgs` does not truncate, and a
              `code_execute` call's arguments ARE its script, which would
              otherwise push the result the operator opened the card for off the
              bottom of the screen. */}
          <Text
            as="div"
            variant="micro"
            tone="dim"
            class="max-h-24 overflow-y-auto break-words"
          >
            <span class="text-text">{props.tool.name}</span>
            {props.tool.args ? ` ${props.tool.args}` : ""}
          </Text>
          <Show
            when={props.tool.status === "error" && props.tool.error}
            fallback={
              <Show when={props.tool.result}>
                <Text
                  variant="micro"
                  tone="dim"
                  class="whitespace-pre-wrap break-words"
                >
                  {props.tool.result}
                </Text>
              </Show>
            }
          >
            <Text
              variant="micro"
              tone="alert"
              class="whitespace-pre-wrap break-words"
            >
              {props.tool.error}
            </Text>
          </Show>
          <Show
            when={
              props.tool.status === "error" &&
              !props.tool.error &&
              !props.tool.result
            }
          >
            <Text variant="micro" tone="alert">
              Tool failed with no additional detail.
            </Text>
          </Show>
        </div>
      </Collapse>
    </div>
  );
}
