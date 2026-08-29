import { createSignal, type JSX } from "solid-js";
import { FramedOverlay } from "~/ui";
import { registerKeymap } from "~/lib/keymap";
import { PaletteBody } from "./palette/PaletteBody";

const [open, setOpen] = createSignal(false);

/** Opened by the rail's search glyph as well as `mod+k`, so the palette isn't
 *  only reachable by a shortcut you have to already know about. */
export function openNavPalette(): void {
  setOpen(true);
}

/**
 * The fast jump — and, now, the fast *change*. It spans all areas and matches
 * descriptions as well as labels, since a page is often known by what it does
 * rather than what it's called, and it indexes the platform's settings beside
 * the pages so a value can be flipped without navigating to the screen that
 * owns it. A keystroke beats expanding a section and scanning its rows.
 *
 * It's an overlay rather than a field in the rail because a permanent input cost
 * a band of vertical space and a third tier of clickable rows for something used
 * occasionally — and because an overlay has room to show the description that
 * makes a match make sense, and the live value that makes a setting actionable.
 *
 * The shell is all that lives here: `FramedOverlay` mounts its children only
 * while open, so `PaletteBody` holding the query, the cursor, and the settings
 * index means all three are born and die with the overlay.
 *
 * It arrives in the same framed container the settings dialog and the chat View
 * use — a place is drawn, then filled. Two overlays reached from the same rail
 * should not have two different ideas of how an overlay appears.
 */
export function NavPalette(): JSX.Element {
  const close = (): void => {
    setOpen(false);
  };

  registerKeymap(() => [{ combo: "mod+k", run: () => setOpen(true) }]);

  return (
    <FramedOverlay open={open()} onClose={close} class="max-w-xl">
      <PaletteBody onClose={close} />
    </FramedOverlay>
  );
}
