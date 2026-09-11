import { type JSX } from "solid-js";
import { cx } from "~/ui";
import {
  SURFACE_RENDERERS,
  type SurfaceContext,
} from "../viewport/surfaceRenderers";
import type { ViewportLayout, ViewportPane } from "../viewport/layout";
import type { SurfaceId } from "../viewport/surfaces";

/**
 * Renders a layout.
 *
 * The host's whole job is to turn the value `paneTree.ts` describes into boxes, and it
 * takes no position on which layouts are worth building — that policy lives with the
 * operations that construct them. So it renders whatever it is handed, including shapes
 * nothing currently produces: a layout is persisted and outlives the code that wrote it,
 * and a host that could only draw today's arrangements would fail on yesterday's.
 *
 * Strips stack above at their natural height; panels take the rest. A split lays its
 * children out along its axis in its stored proportion. A stack shows its active surface
 * — the tab strip that lets the operator change which belongs with the tiling work, since
 * nothing builds a stack until then.
 *
 * Sizing is `flex` rather than percentages so a child that cannot honour its share gives
 * way to its own minimum instead of overflowing the pane.
 */
export function ViewportHost(props: {
  layout: ViewportLayout;
  ctx: SurfaceContext;
}): JSX.Element {
  // Every surface gets its own filling box rather than being dropped straight into
  // whatever contains it. A surface body sizes itself with `h-full`, which is right
  // inside a block but leaves it sizing to its *content* the moment its parent is a
  // flex row — so the box, not the surface, is what claims the space.
  const renderSurface = (id: SurfaceId): JSX.Element => (
    <div class="min-h-0 min-w-0 flex-1">{SURFACE_RENDERERS[id](props.ctx)}</div>
  );

  const renderPane = (node: ViewportPane): JSX.Element => {
    switch (node.kind) {
      case "leaf":
        return renderSurface(node.surface);
      case "stack":
        return renderSurface(node.active);
      case "split":
        return (
          <div
            class={cx(
              "flex min-h-0 min-w-0 flex-1",
              node.dir === "row" ? "flex-col" : "flex-row",
            )}
          >
            <div
              class="flex min-h-0 min-w-0"
              style={{ flex: `${node.ratio} 1 0%` }}
            >
              {renderPane(node.a)}
            </div>
            <div
              class="flex min-h-0 min-w-0"
              style={{ flex: `${1 - node.ratio} 1 0%` }}
            >
              {renderPane(node.b)}
            </div>
          </div>
        );
    }
  };

  return (
    <div class="flex h-full min-h-0 flex-col">
      {props.layout.strips.map((id) => (
        <div class="shrink-0">{renderSurface(id)}</div>
      ))}
      {props.layout.panels ? (
        <div class="flex min-h-0 flex-1">{renderPane(props.layout.panels)}</div>
      ) : null}
    </div>
  );
}
