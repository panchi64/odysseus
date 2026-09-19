import {
  For,
  Show,
  createEffect,
  createSignal,
  untrack,
  type Accessor,
  type JSX,
} from "solid-js";
import { cx } from "../cx";
import { Icon } from "../primitives/Icon";
import { Text } from "../primitives/Text";
import { HIDDEN_FILE_INPUT, useFileDrop } from "../primitives/useFileDrop";
import { AttachmentChip, type ComposerAttachment } from "./AttachmentChip";
import { Button } from "./Button";
import {
  ComposerMenu,
  type ComposerMenuGroup,
  type ComposerMenuItem,
} from "./ComposerMenu";
import {
  replaceToken,
  tokenAt,
  tokenSpans,
  type ComposerToken,
  type ComposerTrigger,
} from "./composerToken";
import { LedEdge } from "./LedEdge";
import { type Rect } from "./popoverPlacement";
import { Tooltip } from "./Tooltip";

// Self-contained guarded storage: the design system does not depend on ~/lib, so
// the Composer keeps its own best-effort draft persistence rather than importing
// the app's storage helper.
const DRAFT_PREFIX = "ody.draft.";

// The docked field grows with its content up to this many lines, then scrolls —
// long prompts stay readable without the bar swallowing the conversation.
const MAX_ROWS = 6;

/* The strip light's two dials, for `edge="led"` only (§10.9). They live here,
   named, because this is the one surface that wants a stronger LED than the
   system default and the pair is meant to be tuned by eye — turning them up in
   `theme.css` instead would brighten every rail in the product.
     INTENSITY multiplies the opacity curve; REACH multiplies how far the light
   throws (1 ~= 90px). The composer sits under a whole transcript, so both run
   above 1: at the default the glow dies inside the card's own top padding. */
const LED_INTENSITY = 1.35;
const LED_REACH = 1.7;

function loadDraft(key?: string): string {
  if (!key) return "";
  try {
    return localStorage.getItem(DRAFT_PREFIX + key) ?? "";
  } catch {
    return "";
  }
}

function saveDraft(key: string, value: string): void {
  try {
    if (value) localStorage.setItem(DRAFT_PREFIX + key, value);
    else localStorage.removeItem(DRAFT_PREFIX + key);
  } catch {
    /* storage unavailable — drafts are best-effort */
  }
}

/**
 * Attachment controller injected by the feature layer. The design system can't
 * reach the uploads data seam, so the Composer owns the *chips* but not the
 * upload/poll — the feature hands it this. The Composer reads `items` to render,
 * drives `attach`/`remove`/`toggleKbExcluded` from the chip controls, reads the
 * ready ids on SEND, and calls `clear` after a send.
 */
export interface ComposerAttachmentsApi {
  items: Accessor<ComposerAttachment[]>;
  attach: (files: File[]) => void;
  remove: (id: string) => void;
  toggleKbExcluded: (id: string) => void;
  clear: () => void;
}

/**
 * The `/` and `@` menu controller, injected by the feature layer — the same split as
 * `ComposerAttachmentsApi` above and for the same reason: the design system cannot reach
 * a data seam, so the Composer owns the *token* and the *keys* and the feature owns what
 * the rows are and what picking one means.
 *
 * The Composer calls `onQuery` whenever the token under the caret changes (and with
 * `null` when there is none), renders `groups`, and routes the navigation keys here
 * before applying its own Enter-sends rule.
 */
export interface ComposerMenuApi {
  /** Rows to show for the current query. Empty closes the menu. */
  groups: Accessor<ComposerMenuGroup[]>;
  /** The token under the caret changed. `null` means there is none — the menu closes. */
  onQuery: (token: { trigger: ComposerTrigger; query: string } | null) => void;
  /** What picking a row inserts in place of the token, **without** its trigger
   *  character (`reviewer`, `src/app.tsx`). Returning null leaves the field alone, for a
   *  row that acts instead of completing — an action command fires its relay and the
   *  composer clears. */
  onPick: (item: ComposerMenuItem) => string | null;
  /** Called after a pick that returned null, so the feature can clear the draft itself
   *  once its relay has fired. */
  onClear?: () => void;
}

export interface ComposerProps {
  /** Receives the trimmed text and the ids of every ready attachment. */
  onSend: (text: string, attachmentIds: string[]) => void;
  disabled?: boolean;
  /** Why this message cannot be sent, or null when it can. SEND is disabled and
   *  carries the reason on hover; the **field stays live**, so a draft already typed
   *  survives and can still be edited while the operator goes and fixes the cause.
   *
   *  Distinct from `disabled`, which means "the composer is not accepting input right
   *  now" (a run owns it). This means "what you have is fine, but it would be refused"
   *  — a blocker the operator can act on, which is why it carries an explanation and
   *  `disabled` doesn't. */
  sendBlocked?: string | null;
  /** A run is generating: a STOP button wired to `onStop` joins the action row,
   *  so the interrupt control sits where the user's focus already is. When the
   *  field itself stays enabled (`disabled` false), SEND remains beside it —
   *  the caller queues the message into the live run (mid-run steering); a
   *  disabled field shows STOP alone. Attaching is unavailable while streaming
   *  either way. */
  streaming?: boolean;
  /** Invoked when STOP is pressed mid-stream (see `streaming`). */
  onStop?: () => void;
  /** What SEND is called. Defaults to "Send".
   *
   *  For the one case where sending this field does something other than message the
   *  agent: the approval dock borrows the composer to collect a request for changes, and
   *  a button reading "Send" beside a plan the operator has just rejected says the wrong
   *  thing about what is about to happen. A label, not a second component — everything
   *  else about the control, and about the field above it, is identical. */
  sendLabel?: string;
  /** Text to insert into the field programmatically (e.g. an undelivered queued
   *  message restored after a cancel). Applied whenever it becomes non-empty —
   *  appended below any current draft — then acknowledged via
   *  `onPrefillConsumed` so the caller can clear it. */
  prefill?: string | null;
  onPrefillConsumed?: () => void;
  placeholder?: string;
  /** `md` = docked input bar (default); `lg` = centered hero field. */
  size?: "md" | "lg";
  /** Sentence-case label shown above the field (hero/`lg` use). */
  title?: string;
  autofocus?: boolean;
  /** Persists the unsent draft to localStorage under this key, reactively —
   *  switching keys (e.g. between conversations) loads that key's draft. */
  storageKey?: string;
  /** Inline controls placed at the **start** of the action row, beside ATTACH —
   *  the settings that describe what this message *is* (its mode, its project). */
  controls?: JSX.Element;
  /** Inline controls placed at the **end** of the action row, immediately before
   *  SEND — what the message is about to be sent *to*, and the state of the thread
   *  it is going into (the model, the context gauge).
   *
   *  Two slots rather than one because the row reads as a sentence toward the send
   *  button: what this is, then the field, then where it's going, then go. A model
   *  picker parked at the left margin next to ATTACH is the same information in the
   *  place the eye leaves rather than the place it arrives. */
  trailing?: JSX.Element;
  /** Drop the surface fill — **the bloom is kept**. The field and its action row
   *  sit directly on whatever is behind them, with the aura still marking them
   *  as the point of action.
   *
   *  For a composer that sits inside another surface (nested in a `Panel`, say):
   *  a fill on a fill is the box-in-a-box §7 exists to stop, and it reads as a
   *  grey slab. The bloom is not part of that problem — it is light, not a
   *  surface, and it is the thing that says "type here". */
  bare?: boolean;
  /** How the composer marks itself as the point of action.
   *
   *  `bloom` (default) is the wide ambient aura — right where the composer is
   *  the whole screen, floating in space (the home launchpad). `led` swaps it
   *  for a lit strip across the **top** edge: inside a
   *  live conversation the aura had ~90px of upward reach and washed over the
   *  last thing the model said, and a rail says "the input starts here" without
   *  spilling onto the transcript. */
  edge?: "bloom" | "led";
  /** File-attachment controller. When supplied, the Composer shows an attach
   *  button + drag-drop and renders the attachment chips; omit to hide them. */
  attachments?: ComposerAttachmentsApi;
  /** `/` and `@` menu controller. Omit and neither character does anything special,
   *  which is what the compare bench and the approval dock want. */
  menu?: ComposerMenuApi;
  class?: string;
}

/**
 * Message input. Enter sends; Shift+Enter inserts a newline. Drafts auto-save to
 * localStorage (per `storageKey`) and restore on return, so an interrupted or
 * resumed message is never lost. Cosmetic difference between the docked bar and
 * the hero field is the `size` prop — never a forked component. When an
 * `attachments` controller is supplied, files can be attached (drop or pick) and
 * ride along with the message; a send needs either text or ≥1 ready attachment.
 */
export function Composer(props: ComposerProps): JSX.Element {
  const [text, setText] = createSignal("");
  let field: HTMLTextAreaElement | undefined;
  // The accent layer behind the field. Held so its scroll can be kept in step with the
  // field's — past `MAX_ROWS` the textarea scrolls, and a layer that stayed put would
  // paint the colours of the first lines over whatever had scrolled into view.
  let highlightRef: HTMLDivElement | undefined;

  // ── The `/` and `@` menu ────────────────────────────────────────────────────────
  // Three pieces of state and no more: the token under the caret, the field's rect to
  // hang the panel off, and which row the keyboard is on. Everything else — what the
  // rows *are*, what picking one means — is the feature's, through `props.menu`.
  const [token, setToken] = createSignal<ComposerToken | null>(null);
  const [anchor, setAnchor] = createSignal<Rect | null>(null);
  const [activeId, setActiveId] = createSignal<string | null>(null);

  const groups = () => props.menu?.groups() ?? [];
  const rows = () => groups().flatMap((group) => group.items);
  // Open only with something to show. A panel that appears empty on the first `/` and
  // then fills in reads as a glitch; one that never appears reads as "no matches".
  const menuOpen = () => token() !== null && rows().length > 0;

  /** Re-read the token under the caret and tell the feature what to fetch.
   *
   *  Driven from input and from selection changes alike, because moving the caret back
   *  into a half-typed `/rev` is the same situation as having just typed it. */
  const syncToken = (): void => {
    if (!props.menu || !field) return;
    const next = tokenAt(field.value, field.selectionStart);
    const current = token();
    if (next?.trigger === current?.trigger && next?.query === current?.query) {
      // Same token, moved: keep the rows, re-measure in case the field grew a line.
      setToken(next);
      setAnchor(field.getBoundingClientRect());
      return;
    }
    setToken(next);
    setAnchor(next ? field.getBoundingClientRect() : null);
    props.menu.onQuery(next && { trigger: next.trigger, query: next.query });
  };

  // Keep the cursor on a row that still exists. A query narrowing under the operator's
  // fingers otherwise leaves the selection pointing at a row that has been filtered
  // away, and Enter would insert nothing.
  createEffect(() => {
    const ids = rows().map((row) => row.id);
    if (ids.length === 0) {
      setActiveId(null);
      return;
    }
    setActiveId((current) =>
      current !== null && ids.includes(current) ? current : ids[0]!,
    );
  });

  const dismissMenu = (): void => {
    setToken(null);
    setAnchor(null);
    props.menu?.onQuery(null);
  };

  const step = (delta: number): void => {
    const ids = rows().map((row) => row.id);
    if (ids.length === 0) return;
    const at = ids.indexOf(activeId() ?? "");
    // Wraps, because a menu of five rows is faster to reach the end of by going up.
    setActiveId(ids[(at + delta + ids.length) % ids.length]!);
  };

  const pick = (item: ComposerMenuItem): void => {
    const current = token();
    if (!props.menu || !current) return;
    const insert = props.menu.onPick(item);
    if (insert === null) {
      // The row acted rather than completed — an action command. The feature clears the
      // draft once its relay has fired; the composer only takes the menu down.
      setText("");
      props.menu.onClear?.();
      dismissMenu();
      field?.focus();
      return;
    }
    const next = replaceToken(text(), current, insert);
    setText(next.text);
    dismissMenu();
    // After the DOM has the new value, or the caret lands at the old length.
    queueMicrotask(() => {
      field?.focus();
      field?.setSelectionRange(next.caret, next.caret);
    });
  };

  /** The navigation keys, taken **before** the Composer's own Enter-sends rule.
   *
   *  They have to be handled here rather than on the panel: focus never leaves this
   *  textarea while the menu is up, and the panel is portalled to `document.body`, so
   *  nothing typed here would ever reach a handler over there. Returns whether the key
   *  was consumed.
   */
  const menuKey = (e: KeyboardEvent): boolean => {
    if (!menuOpen()) return false;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      step(e.key === "ArrowDown" ? 1 : -1);
      return true;
    }
    if (e.key === "Enter" || e.key === "Tab") {
      const row = rows().find((item) => item.id === activeId());
      if (!row) return false;
      e.preventDefault();
      pick(row);
      return true;
    }
    if (e.key === "Escape") {
      // Stopped as well as prevented: the menu is the innermost thing Escape can mean,
      // and letting it through would also close the panel or the room behind it.
      e.preventDefault();
      e.stopPropagation();
      dismissMenu();
      return true;
    }
    return false;
  };

  const items = () => props.attachments?.items() ?? [];
  const readyIds = () =>
    items()
      .filter((a) => a.status === "ready")
      .map((a) => a.id);
  const hasReady = () => readyIds().length > 0;

  const drop = useFileDrop((files) => props.attachments?.attach(files));

  // Load the draft for the active key — runs on mount and whenever the key
  // changes (e.g. switching conversations). This effect is the sole owner of
  // key transitions: it swaps `text` to the incoming key's draft.
  createEffect(() => {
    const key = props.storageKey;
    setText(key ? loadDraft(key) : "");
  });

  // Persist edits back to the active key. Tracks only `text` — the key is read
  // untracked so a key change never writes the outgoing draft under the incoming
  // key (the load effect above already swapped `text`). Tracking the key here
  // would race that load and leak a stale draft across conversations.
  createEffect(() => {
    const value = text();
    const key = untrack(() => props.storageKey);
    if (key) saveDraft(key, value);
  });

  // Focus the field on mount and again whenever the active conversation changes
  // (the key transition), so a freshly opened or newly started chat is ready to
  // type into without a click. Reading `storageKey` tracked makes the refocus
  // fire on switch; `autofocus` is read untracked so only opted-in callers grab
  // focus and a key change alone never enables it.
  createEffect(() => {
    // Returned (rather than discarded) so reading the key counts as a tracked
    // dependency — the refocus then fires on every conversation switch.
    const key = props.storageKey;
    if (untrack(() => props.autofocus)) field?.focus();
    return key;
  });

  // Re-focus when the field re-enables after a run finishes (disabled true →
  // false), so the conversation continues without a click. Gated on `autofocus`
  // — same opt-in as the mount/switch focus above — and only on the enabling
  // edge, so an idle field toggling for any other reason doesn't grab focus.
  let wasDisabled = untrack(() => props.disabled) ?? false;
  createEffect(() => {
    const disabled = props.disabled ?? false;
    if (wasDisabled && !disabled && untrack(() => props.autofocus))
      field?.focus();
    wasDisabled = disabled;
  });

  // Apply a caller-provided prefill (restored undelivered text): append below
  // any current draft, hand focus back, and acknowledge so the caller clears it.
  createEffect(() => {
    const incoming = props.prefill;
    if (!incoming) return;
    setText((current) => (current ? `${current}\n${incoming}` : incoming));
    props.onPrefillConsumed?.();
    field?.focus();
  });

  const canSend = () =>
    !props.disabled &&
    !props.sendBlocked &&
    (Boolean(text().trim()) || hasReady());

  const submit = () => {
    if (!canSend()) return;
    props.onSend(text().trim(), readyIds());
    setText(""); // clears the persisted draft via the effect above
    props.attachments?.clear();
  };

  const onKeyDown = (e: KeyboardEvent) => {
    // The menu gets first refusal. Enter picks a row rather than sending the message —
    // without this the operator's `/rev` would be sent as a literal prompt.
    if (menuKey(e)) return;
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  const lg = () => props.size === "lg";
  const led = () => props.edge === "led";

  // Grow the docked field to fit its content, capped at MAX_ROWS (then scroll).
  // The hero (`lg`) variant keeps its fixed rows. Runs on every text change —
  // typing, draft load, and clear-after-send all reflow the height.
  const autosize = () => {
    const el = field;
    if (!el || lg()) return;
    el.style.height = "auto";
    const cs = getComputedStyle(el);
    const line = parseFloat(cs.lineHeight) || 20;
    const padding = parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom);
    const border =
      parseFloat(cs.borderTopWidth) + parseFloat(cs.borderBottomWidth);
    const max = line * MAX_ROWS + padding + border;
    // `scrollHeight` covers content + padding but not border; the field is
    // border-box, so add the border back or the set height clips by that much.
    const fit = el.scrollHeight + border;
    el.style.height = `${Math.min(fit, max)}px`;
    el.style.overflowY = fit > max ? "auto" : "hidden";
  };
  createEffect(() => {
    text(); // reflow whenever the value changes
    autosize();
  });

  /* The field carries no chrome of its own — no border, no fill, no focus ring.
     The card around it is the control, and it is what lights up on focus, so a
     second bordered box inside it would only add a line (§7). */
  const fieldClass = () =>
    cx(
      /* `text-prose`, the reading scale — the field produces the operator's turn,
         which renders at reading size a few pixels above it. Typing at 13px and
         watching it come back at 16px is the same mismatch, one step earlier. */
      /* `block`, because a textarea is inline-block and carries a baseline descender —
         ~5px of dead space under it inside any block container. It cost nothing in the
         flex column this used to sit in directly, and it is load-bearing now that the
         field shares a wrapper with the accent layer measured against it. */
      "block w-full resize-none border-0 bg-transparent px-1 py-1 text-prose font-sans text-bright placeholder:text-dim outline-none disabled:opacity-40",
      lg() ? "min-h-20" : "min-h-8",
    );

  /** The field's text split into plain runs and accent-coloured tokens.
   *
   *  A textarea cannot colour part of its own value, so the standard arrangement is used:
   *  this layer sits directly behind a text-transparent field, painting the same string
   *  with the same metrics, and the operator sees the caret and selection of the real
   *  control over the colours of this one.
   *
   *  Everything about it is therefore metric-bound to the field, which is why it shares
   *  `fieldClass()` rather than restating the typography: any difference in font, size,
   *  padding or wrapping shows up immediately as the colour drifting off the words. It
   *  also has to render a trailing newline as a space, since a `<div>` collapses one that
   *  a textarea shows — without it the last line scrolls out of step.
   */
  const highlighted = () => {
    const value = text();
    const spans = props.menu ? tokenSpans(value) : [];
    const runs: { text: string; token: boolean }[] = [];
    let at = 0;
    for (const span of spans) {
      if (span.start > at)
        runs.push({ text: value.slice(at, span.start), token: false });
      runs.push({ text: value.slice(span.start, span.end), token: true });
      at = span.end;
    }
    if (at < value.length) runs.push({ text: value.slice(at), token: false });
    return runs;
  };

  const highlightLayer = (
    <Show when={props.menu}>
      <div
        aria-hidden="true"
        ref={(el) => {
          highlightRef = el;
        }}
        class={cx(
          fieldClass(),
          // Behind the field, exactly on top of it, and inert: the real control takes
          // every click, caret move and selection.
          "pointer-events-none absolute inset-0 overflow-hidden whitespace-pre-wrap break-words text-bright",
        )}
      >
        <For each={highlighted()}>
          {(run) => (
            <Show when={run.token} fallback={run.text}>
              <span class="text-accent">{run.text}</span>
            </Show>
          )}
        </For>
        {/* A textarea shows a trailing newline; a div collapses it. */}
        {text().endsWith("\n") ? " " : ""}
      </div>
    </Show>
  );

  const textarea = (
    <textarea
      ref={field}
      value={text()}
      onInput={(e) => {
        setText(e.currentTarget.value);
        syncToken();
      }}
      onKeyDown={onKeyDown}
      // Arrow keys and clicks move the caret without changing the text, and moving back
      // into a half-typed `/rev` is the same situation as having just typed it.
      onKeyUp={syncToken}
      onClick={syncToken}
      // The menu hangs off the field's content, so it goes when the field does. This is
      // also what replaces the backdrop `FloatingPanel` would otherwise draw over the
      // whole screen — see its `passive` prop.
      onBlur={dismissMenu}
      onScroll={(e) => {
        if (highlightRef) highlightRef.scrollTop = e.currentTarget.scrollTop;
      }}
      onPaste={props.attachments ? drop.pasteHandlers.onPaste : undefined}
      rows={lg() ? 3 : 1}
      placeholder={props.placeholder ?? "Message the agent…"}
      disabled={props.disabled}
      role={props.menu ? "combobox" : undefined}
      aria-expanded={props.menu ? menuOpen() : undefined}
      aria-controls={props.menu ? "composer-menu" : undefined}
      // Focus stays here the whole time, so this is the only thing that tells a screen
      // reader which row the arrows are on.
      aria-activedescendant={menuOpen() ? (activeId() ?? undefined) : undefined}
      class={cx(
        fieldClass(),
        // The field's own glyphs go transparent so the coloured layer behind shows
        // through; the caret keeps a colour of its own, or typing would be invisible.
        // `relative` so it stacks above that layer rather than under it.
        props.menu && "relative bg-transparent text-transparent caret-bright",
      )}
    />
  );

  // The attach affordance: a button that opens the picker plus the hidden input
  // the file-drop hook clicks. Only mounted when an attachments controller is
  // wired, so non-attachment surfaces are unchanged.
  //
  // A plus, not a paperclip. The button opens the picker, but what it *means* in
  // the action row is "add something to this message" — and a `+` says that at a
  // glance where a clip says "there is a file convention here". The glyph stops
  // naming the action, so `aria-label` is now the only thing that does; it stays.
  const attachBtn = (
    <Show when={props.attachments}>
      <Button
        variant="ghost"
        size={lg() ? "lg" : "md"}
        leading="plus"
        iconSize={lg() ? 28 : 22}
        aria-label="Attach files"
        disabled={props.disabled || props.streaming}
        onClick={drop.openPicker}
      />
      <input
        ref={drop.bindInput}
        {...HIDDEN_FILE_INPUT}
        {...drop.inputHandlers}
      />
    </Show>
  );

  // Attachment chips, above the field. Each shows status, a KB-membership
  // toggle, and a remove control. The wrapping margin is the docked bar's; the
  // hero stacks it with the field via the column gap.
  const chips = (
    <Show when={props.attachments && items().length > 0}>
      <div class={cx("flex flex-wrap gap-2", !lg() && "mb-2")}>
        <For each={items()}>
          {(a) => (
            <AttachmentChip
              name={a.name}
              status={a.status}
              kbExcluded={a.kbExcluded}
              onToggleKbExcluded={() =>
                props.attachments?.toggleKbExcluded(a.id)
              }
              onRemove={() => props.attachments?.remove(a.id)}
            />
          )}
        </For>
      </div>
    </Show>
  );

  // While a run streams, STOP joins the row so the interrupt sits where the
  // user's focus already is. A caller that keeps the field enabled mid-stream
  // keeps SEND beside it (Enter/SEND then queues into the live run — steering);
  // one that disables the field shows STOP alone, as before.
  // A component, not a JSX value held in a variable: each `<SendButton />` below builds
  // its own element. Sharing one across both arms of the `Show` shares the same DOM
  // node, and Solid tears the tree apart trying to move it between them ("the new child
  // element contains the parent") the first time the block state flips.
  const SendButton = () => (
    <Button
      variant="primary"
      trailing="send"
      disabled={!canSend()}
      onClick={submit}
    >
      {props.sendLabel ?? "Send"}
    </Button>
  );
  // Wrapped only when there is something to say. A tooltip on every SEND would fire on
  // the one control the operator uses most, to tell them nothing.
  const sendBtn = () => (
    <Show when={props.sendBlocked} fallback={<SendButton />}>
      {(reason) => (
        <Tooltip label={reason()} side="top">
          <SendButton />
        </Tooltip>
      )}
    </Show>
  );
  const actionBtn = (
    <Show when={props.streaming} fallback={sendBtn()}>
      <span class="flex items-center gap-2">
        <Show when={!props.disabled}>{sendBtn()}</Show>
        <Button
          variant="default"
          leading="stop"
          onClick={() => props.onStop?.()}
        >
          Stop
        </Button>
      </span>
    </Show>
  );

  // A subtle full-surface highlight while files hover the composer, so the drop
  // target reads clearly without a separate dashed zone.
  const dropOverlay = (
    <Show when={props.attachments && drop.isDragging()}>
      {/* Follows the card's corners, which square off at the top under a strip
          light — an inset overlay with its own radius reads as a second box. */}
      <div
        class={cx(
          "pointer-events-none absolute inset-0 z-10 flex items-center justify-center border border-dashed border-info bg-info/10",
          led() ? "rounded-b-panel" : "rounded-panel",
        )}
      >
        <Text variant="label" tone="info">
          <span class="inline-flex items-center gap-2">
            <Icon name="attach" size={16} />
            Drop to attach
          </span>
        </Text>
      </div>
    </Show>
  );

  /* ONE layout for both sizes. The docked bar and the hero used to be separate
     branches — a bordered field nested inside a bordered bar for `md`, a 2px
     box for `lg` — which is exactly the box-in-a-box the system dropped (§7).
     Now both are the same card: a raised surface on smoothed corners, the field
     transparent inside it, and the controls on their own row beneath. Only
     padding and the field's resting height differ.

     The composer is where the operator's attention belongs on these screens, so
     it carries `shadow-bloom` — the wide ambient accent aura (§6.2) — AT REST,
     not on hover or focus. It is not a focus affordance: the composer is the
     point of the screen whether or not the cursor is in it, and a glow that only
     appears once you have already committed to typing is telling you something
     you no longer need to know.

     `shadow-bloom`, not `shadow-accent`: the tight control-sized shadow reads as
     an edge cutout around something this large.

     `edge="led"` is the other way of saying the same thing — a lit strip on the
     top edge instead of an aura, for the docked case where the composer has a
     transcript directly above it to keep legible. Its corners square off at the
     top so the strip meets the card's own edges instead of overhanging them, and
     it keeps `shadow-1`: the bloom's hairline ring went with it, and in Paper
     that ring is the only thing separating a white card from a white page. */
  // Portalled to the body by `FloatingPanel`, so it sits outside the composer's own
  // stacking context and outside the transcript's `overflow-auto` — the two things that
  // would otherwise clip it. Mounted inside the card only so it shares the card's
  // lifetime.
  const menu = (
    <Show when={props.menu}>
      <ComposerMenu
        open={menuOpen()}
        groups={groups()}
        anchor={anchor}
        activeId={activeId()}
        onPick={pick}
        onActivate={(item) => setActiveId(item.id)}
      />
    </Show>
  );

  const body = (
    <>
      {dropOverlay}
      {menu}
      <Show when={props.title}>
        <Text variant="label" tone="dim">
          {props.title}
        </Text>
      </Show>
      {chips}
      {/* The two are one control: the layer paints the words, the field owns the caret,
          and they must occupy the same box for the colours to land on the right glyphs.
          The gap this wrapper would otherwise add is closed on the field itself (`block`
          in `fieldClass`), not here: a textarea is inline-block, so a block wrapper puts
          ~5px of baseline descender under it where the surrounding flex column never did.
          The layer is `inset-0` of this wrapper, so those 5px made it taller than the
          field, and past six rows the two scrolled by different amounts and the colours
          slid off the words. Closing it with `flex` here instead looked equivalent and is
          not: a stretched flex item breaks the `height:auto` measurement the autosize
          takes, and the field collapses to one row. */}
      <div class="relative">
        {highlightLayer}
        {textarea}
      </div>
      <div class="flex items-center justify-between gap-2">
        <div class="flex min-w-0 items-center gap-1">
          {attachBtn}
          <Show when={props.controls}>{props.controls}</Show>
        </div>
        {/* `gap-3`, wider than the leading group's, because the items here are not the
            same kind of thing. The leading group is buttons, whose own padding carries
            their separation; this row mixes a bare text trigger, a bare gauge and a
            filled button, and a gap tuned to the button leaves the gauge crowding it
            while the trigger's own padding holds it further off. The wider gap is what
            makes the three read as evenly spaced rather than merely equally gapped. */}
        <div class="flex min-w-0 items-center gap-3">
          <Show when={props.trailing}>{props.trailing}</Show>
          {actionBtn}
        </div>
      </div>
    </>
  );

  const rootClass = () =>
    cx(
      "relative flex flex-col gap-2",
      // One class per case rather than `rounded-panel` + `rounded-t-none`: the
      // override only works if Tailwind emits the corner utility after the
      // shorthand, and a silent cascade dependency is not worth the shared word.
      led() ? "rounded-b-panel shadow-1" : "rounded-panel shadow-bloom",
      !props.bare && "bg-surface",
      lg() ? "p-4" : "p-3",
      props.class,
    );

  const dropAttrs = () => (props.attachments ? drop.dropHandlers : {});

  return (
    <Show
      when={led()}
      fallback={
        <div class={rootClass()} {...dropAttrs()}>
          {body}
        </div>
      }
    >
      {/* The strip reports the run. At rest it is neutral white — it is not
          claiming anything is happening, only marking where the operator acts,
          which §6 draws with luminance rather than hue. While the model is
          working it fades to `info`, the same blue the live rail uses beside a
          streaming block, so the composer joins the conversation's live state
          instead of announcing a second vocabulary for it. The fade itself is in
          `.ody-led::before` (§8, ambient). */}
      <LedEdge
        lit
        side="top"
        tone={props.streaming ? "info" : "neutral"}
        intensity={LED_INTENSITY}
        reach={LED_REACH}
        class={rootClass()}
        {...dropAttrs()}
      >
        {body}
      </LedEdge>
    </Show>
  );
}
