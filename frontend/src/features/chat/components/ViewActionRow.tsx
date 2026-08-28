import { Show, type JSX } from "solid-js";
import { Button, Tooltip } from "~/ui";
import { activeDownload, downloadBlob } from "../viewerPersistence";

const FONT_MIN = -2;
const FONT_MAX = 2;

/** A text-label toggle (WRAP / EXPAND) — composes `Button`'s `active` state so
 *  brightness carries the pressed state, never color. */
function ToggleAction(props: {
  label: string;
  active: boolean;
  ariaLabel: string;
  onToggle: () => void;
}): JSX.Element {
  return (
    <Button
      variant="ghost"
      size="sm"
      active={props.active}
      aria-label={props.ariaLabel}
      aria-pressed={props.active}
      onClick={props.onToggle}
    >
      {props.label}
    </Button>
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
          <Button
            variant="ghost"
            size="sm"
            leading="pin"
            active={Boolean(props.keeper)}
            aria-label="Toggle keeper"
            aria-pressed={Boolean(props.keeper)}
            onClick={() => props.onKeeper?.()}
          />
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
