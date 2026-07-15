import { Show, type JSX } from "solid-js";
import { Button, Icon, Text, Tooltip, cx } from "~/ui";
import { activeDownload, downloadBlob } from "../viewerPersistence";

const FONT_MIN = -2;
const FONT_MAX = 2;

/** A bespoke text-label toggle (WRAP / EXPAND) — brightness carries the active
 *  state, never color, and it's a plain button (not `Button`) so the active tone
 *  isn't fighting the component's own fixed ghost-variant color class. */
function ToggleAction(props: {
  label: string;
  active: boolean;
  ariaLabel: string;
  onToggle: () => void;
}): JSX.Element {
  return (
    <button
      type="button"
      onClick={props.onToggle}
      aria-label={props.ariaLabel}
      aria-pressed={props.active}
      class="flex h-6 items-center px-2 transition-colors hover:text-bright"
    >
      <Text variant="label" tone={props.active ? "bright" : "dim"}>
        {props.label}
      </Text>
    </button>
  );
}

/** The viewer's action row — one flex row of ghost controls mounted in the
 *  panel header: DOWNLOAD, the KEEPER pin, font size, soft-wrap, REFRESH, the
 *  fullscreen toggle, and COLLAPSE. Presentation-only: every control relays
 *  operator intent through props or the shared viewer-persistence seam; nothing
 *  here decides anything. */
export function ViewActionRow(props: {
  /** Rendered only when provided — P5 wires the backend keeper flip. */
  keeper?: boolean;
  onKeeper?: () => void;
  fontStep: number;
  onFontStep: (step: number) => void;
  softWrap: boolean;
  onToggleWrap: () => void;
  /** Reuses the panel's existing reload nonce; absent hides the control (PREVIEW
   *  only — CODE is an immutable snapshot tree, same as before). */
  onRefresh?: () => void;
  fullscreen: boolean;
  onToggleFullscreen: () => void;
  onClose: () => void;
}): JSX.Element {
  const download = () => activeDownload();
  const triggerDownload = () => {
    const d = download();
    if (!d) return;
    void (async () => downloadBlob(d.name, await d.getBlob()))();
  };
  const decFont = () =>
    props.onFontStep(Math.max(FONT_MIN, props.fontStep - 1));
  const incFont = () =>
    props.onFontStep(Math.min(FONT_MAX, props.fontStep + 1));

  return (
    <div class="flex shrink-0 items-center gap-1">
      <Tooltip label="Download" side="bottom">
        <Button
          variant="ghost"
          size="sm"
          leading="download"
          aria-label="Download"
          disabled={!download()}
          onClick={triggerDownload}
        />
      </Tooltip>
      <Show when={props.onKeeper}>
        <Tooltip
          label={props.keeper ? "Unmark keeper" : "Mark as keeper"}
          side="bottom"
        >
          <button
            type="button"
            onClick={() => props.onKeeper?.()}
            aria-label="Toggle keeper"
            aria-pressed={Boolean(props.keeper)}
            class={cx(
              "flex h-6 w-6 items-center justify-center transition-colors hover:text-bright",
              props.keeper ? "text-bright" : "text-dim",
            )}
          >
            <Icon name="pin" size={12} />
          </button>
        </Tooltip>
      </Show>
      <Tooltip label="Smaller text" side="bottom">
        <Button
          variant="ghost"
          size="sm"
          aria-label="Decrease font size"
          disabled={props.fontStep <= FONT_MIN}
          onClick={decFont}
        >
          A-
        </Button>
      </Tooltip>
      <Tooltip label="Larger text" side="bottom">
        <Button
          variant="ghost"
          size="sm"
          aria-label="Increase font size"
          disabled={props.fontStep >= FONT_MAX}
          onClick={incFont}
        >
          A+
        </Button>
      </Tooltip>
      <ToggleAction
        label="WRAP"
        active={props.softWrap}
        ariaLabel="Toggle soft wrap"
        onToggle={props.onToggleWrap}
      />
      <Show when={props.onRefresh}>
        <Tooltip label="Reload" side="bottom">
          <Button
            variant="ghost"
            size="sm"
            leading="refresh"
            aria-label="Reload view"
            onClick={() => props.onRefresh?.()}
          />
        </Tooltip>
      </Show>
      <ToggleAction
        label="EXPAND"
        active={props.fullscreen}
        ariaLabel="Toggle fullscreen"
        onToggle={props.onToggleFullscreen}
      />
      <Tooltip label="Collapse" side="bottom">
        <Button
          variant="ghost"
          size="sm"
          leading="panel-right"
          aria-label="Collapse viewport"
          onClick={props.onClose}
        />
      </Tooltip>
    </div>
  );
}
