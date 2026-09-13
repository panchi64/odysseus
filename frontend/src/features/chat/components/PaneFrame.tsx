import { children, Show, Suspense, type JSX } from "solid-js";
import { Button, Icon, LoadingText, Text, Tooltip } from "~/ui";
import { surfaceSpec, type SurfaceId } from "../viewport/surfaces";

/**
 * What every pane wears, drawn by the host rather than by the surface inside it.
 *
 * A pane could be dismissed three ways — the header button that opened it, a right-click,
 * or `shift+w` — and **none of them was visible from the pane itself**. Only the View
 * carried a close control, because the View was the whole panel back when the panel held
 * exactly one thing. A region the operator cannot see how to shut is one they stop
 * opening, so the affordance belongs on every pane; and since the host is the one place
 * that knows a pane's identity (`surfaceSpec`) and how to close it (`closeSurface`), it is
 * the host that draws it. A surface does not get to forget.
 *
 * **The label is the host's, so a surface must not print its own.** Tasks, Agents and
 * Files each drew a title row of their own, which is why those rows are gone: two headings
 * an inch apart saying the same word is worse than either alone. What is left of those
 * rows — a progress figure, a count — arrives here as `meta`, opaque JSX the frame places
 * and never inspects. That is the whole of what keeps this component surface-agnostic.
 *
 * **`header={false}` is for a pane inside a stack**, where the tab strip is already the
 * label and the close rides at its end. The frame still wraps the body, so the box a
 * stacked surface is laid out in is the same box a leaf gets.
 */
export function PaneFrame(props: {
  id: SurfaceId;
  /** Right-aligned, before the close button — the surface's own figures. */
  meta?: JSX.Element;
  /** Draw the header. Default true; false inside a tabbed stack. */
  header?: boolean;
  onClose: () => void;
  children: JSX.Element;
}): JSX.Element {
  const spec = () => surfaceSpec(props.id);
  // Resolved once: a slot prop is a getter, so guarding on it and then rendering it
  // builds the same elements twice.
  const meta = children(() => props.meta);
  // No height of its own: the frame is a flex child of the box the host lays panes out
  // in, so it stretches to that. An `h-full` here would be a percentage of a strip's
  // content-sized parent — the one case where it means nothing.
  return (
    <div class="flex min-h-0 min-w-0 flex-1 flex-col">
      <Show when={props.header !== false}>
        <div class="flex shrink-0 items-center gap-2 px-3 py-2">
          <Icon name={spec().icon} class="shrink-0 text-dim" />
          <Text variant="label" tone="bright">
            {spec().label}
          </Text>
          <div class="ml-auto flex shrink-0 items-center gap-2">
            <Show when={meta()}>{meta()}</Show>
            <PaneCloseButton label={spec().label} onClose={props.onClose} />
          </div>
        </div>
      </Show>
      {/* A COLUMN, holding one child, and the direction is the whole point: a
          surface body sizes itself with `h-full` and no width of its own, so in a
          flex *row* it shrank to its own max-content — the View rendered its
          preview in a column the width of its PREVIEW/CODE tabs and left the rest
          of the pane empty. A column stretches its child across instead, which is
          the box claiming the space rather than every surface remembering to. */}
      {/* **A pane's own fetches stop here, and that is the point.** Every one of
          these surfaces reads a resource straight into its markup — a file list,
          an artifact's bytes, a diff — and in Solid a read of a *pending* resource
          suspends the nearest boundary, wherever that happens to be. The nearest
          one was the shell's, around the whole route: opening a pane for the first
          time fetched, suspended, and blanked the entire room — header, transcript
          and composer — to the shell's "Loading" line for as long as the pane's
          own request took. Every surface already carries a local loading arm it
          never got to render.

          So the boundary belongs to the pane, at the same box the surface is laid
          out in, and it is drawn here rather than in each surface for the reason
          the header is: the host is what guarantees a pane wears this, so a
          surface cannot forget it and a new one gets it for nothing. */}
      <div class="flex min-h-0 min-w-0 flex-1 flex-col">
        <Suspense fallback={<LoadingText class="px-3 py-2" />}>
          {props.children}
        </Suspense>
      </div>
    </div>
  );
}

/** The close itself, shared with the tab strip a stacked pane wears instead of a
 *  header — one button in two places, so they cannot drift into two gestures. */
export function PaneCloseButton(props: {
  /** The surface's label, spoken to a screen reader: "Close Changes". */
  label: string;
  onClose: () => void;
}): JSX.Element {
  return (
    <Tooltip label="Close" side="bottom">
      <Button
        variant="ghost"
        size="sm"
        leading="close"
        aria-label={`Close ${props.label}`}
        onClick={() => props.onClose()}
      />
    </Tooltip>
  );
}
