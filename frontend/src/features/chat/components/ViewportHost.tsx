import { For, Show, onMount, type JSX } from "solid-js";
import { ContextMenu, ResizeHandle, Tabs, cx, type MenuItem } from "~/ui";
import {
  SURFACE_RENDERERS,
  type SurfaceContext,
} from "../viewport/surfaceRenderers";
import {
  surfacesOf,
  type ViewportLayout,
  type ViewportPane,
} from "../viewport/layout";
import { surfaceSpec, type SurfaceId } from "../viewport/surfaces";
import { observePanelBox } from "../viewport/viewportWidth";

/** Where a pane sits in the tree, as the steps taken to reach it. Splits are
 *  addressed this way rather than by id because a split has no identity of its own —
 *  it is a shape the layout happens to be in. */
type PanePath = readonly ("a" | "b")[];

/**
 * Renders a layout.
 *
 * The host turns the value `paneTree.ts` describes into boxes and takes no position on
 * which layouts are worth building — that policy lives with the operations that
 * construct them. So it renders whatever it is handed, including shapes nothing
 * currently produces: a layout is persisted and outlives the code that wrote it, and a
 * host that could only draw today's arrangements would fail on yesterday's.
 *
 * Strips stack above at their natural height; panels take the rest. A split lays its
 * children along its axis in the stored proportion, with a divider between them. A
 * stack is a tabbed pane.
 *
 * **A stack mounts all of its members and hides the inactive ones.** Unmounting on tab
 * change is the ordinary way to build tabs and the wrong way here, for the reason
 * fullscreen no longer remounts: these surfaces hold live previews, scroll positions and
 * fetched trees, and a tab is a thing the operator flicks between. The cost is that a
 * stacked surface stays live while hidden, which for two or three of them is the
 * cheaper half of the trade.
 *
 * **The panel region publishes its own box.** The splitting policy needs to know whether
 * two panes would still be legible before it commits to a split, and the only honest
 * answer comes from the box the panes are actually laid out in — not the row, which the
 * strips and the panel's own chrome have already been taken out of.
 */
export function ViewportHost(props: {
  layout: ViewportLayout;
  ctx: SurfaceContext;
}): JSX.Element {
  const vp = (): SurfaceContext["viewport"] => props.ctx.viewport;

  /** What right-clicking a pane offers. Built when the menu opens, so it describes
   *  the layout as it is at that moment rather than as it was at render. */
  const paneMenu = (id: SurfaceId): MenuItem[] => {
    const open = surfacesOf(props.layout);
    const others = open.filter((o) => o !== id);
    return [
      {
        label: `Close ${surfaceSpec(id).label}`,
        icon: "close",
        onSelect: () => vp().closeSurface(id),
      },
      {
        label: "Close others",
        icon: "layers",
        disabled: others.length === 0,
        onSelect: () => others.forEach((o) => vp().closeSurface(o)),
      },
      {
        label: vp().state().fullscreen ? "Exit full screen" : "Full screen",
        icon: "grid",
        separated: true,
        onSelect: props.ctx.onToggleFullscreen,
      },
      {
        label: "Close panel",
        icon: "panel-right",
        onSelect: props.ctx.onClose,
      },
    ];
  };

  /**
   * One surface in its own filling box.
   *
   * The box rather than the surface claims the space: a surface body sizes itself
   * with `h-full`, which is right inside a block and leaves it sizing to its content
   * the moment its parent is a flex row.
   *
   * `focusin` rather than a click, so reaching a pane by keyboard makes it current
   * too — which is what the surface-scoped bindings gate on.
   */
  const renderSurface = (id: SurfaceId): JSX.Element => (
    <ContextMenu class="flex min-h-0 min-w-0 flex-1" items={() => paneMenu(id)}>
      <div
        class="min-h-0 min-w-0 flex-1"
        onFocusIn={() => vp().setFocusedSurface(id)}
      >
        {SURFACE_RENDERERS[id](props.ctx)}
      </div>
    </ContextMenu>
  );

  const renderStack = (
    node: Extract<ViewportPane, { kind: "stack" }>,
  ): JSX.Element => (
    <div class="flex min-h-0 min-w-0 flex-1 flex-col">
      <Tabs
        fill
        items={node.surfaces.map((s) => ({
          value: s,
          label: surfaceSpec(s).label,
        }))}
        value={node.active}
        onChange={(v) => vp().revealSurface(v as SurfaceId)}
      />
      {/* Every member stays mounted; only the active one is shown. */}
      <div class="relative min-h-0 flex-1">
        <For each={node.surfaces}>
          {(s) => (
            <div
              class={cx(
                "absolute inset-0 flex",
                s !== node.active && "invisible",
              )}
              aria-hidden={s !== node.active}
            >
              {renderSurface(s)}
            </div>
          )}
        </For>
      </div>
    </div>
  );

  const renderSplit = (
    node: Extract<ViewportPane, { kind: "split" }>,
    path: PanePath,
  ): JSX.Element => {
    let el: HTMLDivElement | undefined;
    // The handle speaks in pixels and the layout in proportions, so the container's
    // own size is the conversion. Reading it per move rather than caching it keeps a
    // drag correct across a window resize mid-gesture.
    const onResize = (delta: number): void => {
      if (!el) return;
      const total = node.dir === "col" ? el.clientWidth : el.clientHeight;
      if (total > 0) vp().adjustSplit(path, node.ratio + delta / total);
    };
    return (
      <div
        ref={el}
        class={cx(
          "flex min-h-0 min-w-0 flex-1",
          node.dir === "row" ? "flex-col" : "flex-row",
        )}
      >
        <div
          class="flex min-h-0 min-w-0"
          style={{ flex: `${node.ratio} 1 0%` }}
        >
          {renderPane(node.a, [...path, "a"])}
        </div>
        <ResizeHandle
          aria-label="Resize panes"
          orientation={node.dir === "col" ? "vertical" : "horizontal"}
          divider="hover"
          onResize={onResize}
        />
        <div
          class="flex min-h-0 min-w-0"
          style={{ flex: `${1 - node.ratio} 1 0%` }}
        >
          {renderPane(node.b, [...path, "b"])}
        </div>
      </div>
    );
  };

  const renderPane = (node: ViewportPane, path: PanePath): JSX.Element => {
    switch (node.kind) {
      case "leaf":
        return renderSurface(node.surface);
      case "stack":
        return renderStack(node);
      case "split":
        return renderSplit(node, path);
    }
  };

  return (
    <div class="flex h-full min-h-0 flex-col">
      {/* `For`/`Show` rather than `.map` and a ternary. A ternary's guard does not
          gate its own branches in Solid — the child expression compiles to a
          computation of its own and re-runs when the layout changes, so a panel
          region that has just emptied reaches the renderer as null. */}
      <For each={props.layout.strips}>
        {(id) => <div class="shrink-0">{renderSurface(id)}</div>}
      </For>
      <Show when={props.layout.panels}>
        {(panels) => (
          <div
            ref={(el) => onMount(() => observePanelBox(el))}
            class="flex min-h-0 flex-1"
          >
            {renderPane(panels(), [])}
          </div>
        )}
      </Show>
    </div>
  );
}
