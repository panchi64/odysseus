import {
  For,
  Match,
  Show,
  Switch,
  createMemo,
  createSignal,
  onMount,
  type Accessor,
  type JSX,
} from "solid-js";
import {
  ContextMenu,
  createContextMenu,
  ResizeHandle,
  Tabs,
  cx,
  type MenuItem,
} from "~/ui";
import {
  SURFACE_RENDERERS,
  type SurfaceContext,
} from "../viewport/surfaceRenderers";
import {
  isSurfaceId,
  surfacesOf,
  type ViewportLayout,
  type ViewportPane,
} from "../viewport/layout";
import { clampRatio } from "../viewport/paneTree";
import { surfaceSpec, type SurfaceId } from "../viewport/surfaces";
import { observePanelBox } from "../viewport/viewportWidth";

/** Where a pane sits in the tree, as the steps taken to reach it. Splits are
 *  addressed this way rather than by id because a split has no identity of its own —
 *  it is a shape the layout happens to be in. */
type PanePath = readonly ("a" | "b")[];

type StackPane = Extract<ViewportPane, { kind: "stack" }>;
type SplitPane = Extract<ViewportPane, { kind: "split" }>;
type LeafPane = Extract<ViewportPane, { kind: "leaf" }>;

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
 * **Every pane is rendered from an accessor, not from a node.** A layout is an
 * immutable value, so *any* change to it — a divider moved a pixel, a tab brought to
 * the front — produces a whole new tree. Rendering `renderPane(layout.panels)` inside a
 * JSX expression makes that one reactive expression over everything, and Solid rebuilds
 * the lot on each new value: a drag would tear down and remount every pane sixty times
 * a second, reloading live previews and losing scroll positions, which is the very
 * thing fullscreen stopped doing. Handing each level an accessor and branching on the
 * node's *kind* means the DOM survives anything that does not change the shape — the
 * proportions and the active tab are then ordinary reactive reads.
 *
 * **A stack mounts all of its members and hides the inactive ones.** Unmounting on tab
 * change is the ordinary way to build tabs and the wrong way here, for the same reason:
 * these surfaces hold live previews, scroll positions and fetched trees, and a tab is a
 * thing the operator flicks between. The cost is that a stacked surface stays live while
 * hidden, which for two or three of them is the cheaper half of the trade.
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

  /** One menu for every pane, keyed by the surface that opened it — the panel holds
   *  two or three panes, and a menu each would be a backdrop and an Escape listener
   *  each for a thing only one of them can be showing. */
  const menu = createContextMenu();

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
   *
   * The right-click goes through the one menu the host owns, keyed by surface: the
   * deepest pane wins, which is what `stopPropagation` buys — a pane inside the
   * panel offers its own actions and the panel behind it must not answer the same
   * gesture.
   */
  const renderSurface = (id: Accessor<SurfaceId>): JSX.Element => (
    <div
      class="flex min-h-0 min-w-0 flex-1"
      onContextMenu={(e) => {
        e.stopPropagation();
        menu.openAt(e, id());
      }}
      onFocusIn={() => vp().setFocusedSurface(id())}
    >
      {SURFACE_RENDERERS[id()](props.ctx)}
    </div>
  );

  const renderStack = (node: Accessor<StackPane>): JSX.Element => (
    <div class="flex min-h-0 min-w-0 flex-1 flex-col">
      <Tabs
        fill
        items={node().surfaces.map((s) => ({
          value: s,
          label: surfaceSpec(s).label,
        }))}
        value={node().active}
        onChange={(v) => vp().revealSurface(v as SurfaceId)}
      />
      {/* Every member stays mounted; only the active one is shown. */}
      <div class="relative min-h-0 flex-1">
        <For each={node().surfaces}>
          {(s) => (
            <div
              class={cx(
                "absolute inset-0 flex",
                s !== node().active && "invisible",
              )}
              aria-hidden={s !== node().active}
            >
              {renderSurface(() => s)}
            </div>
          )}
        </For>
      </div>
    </div>
  );

  const renderSplit = (
    node: Accessor<SplitPane>,
    path: PanePath,
  ): JSX.Element => {
    let el: HTMLDivElement | undefined;
    // The proportion while a drag is in flight, held here rather than written
    // through the layout on every move — the panel's own edge has done it this way
    // since there was one, and for the same two reasons: the persisted record is
    // rewritten on each write, and a settled value is what a preference is.
    const [live, setLive] = createSignal<number | null>(null);
    const ratio = (): number => live() ?? node().ratio;
    // The handle speaks in pixels and the layout in proportions, so the container's
    // own size is the conversion. Reading it per move rather than caching it keeps a
    // drag correct across a window resize mid-gesture.
    const onResize = (delta: number): void => {
      if (!el) return;
      const total = node().dir === "col" ? el.clientWidth : el.clientHeight;
      if (total > 0) setLive(clampRatio(ratio() + delta / total));
    };
    const onResizeEnd = (): void => {
      const settled = live();
      setLive(null);
      if (settled !== null) vp().adjustSplit(path, settled);
    };
    return (
      <div
        ref={el}
        class={cx(
          "flex min-h-0 min-w-0 flex-1",
          node().dir === "row" ? "flex-col" : "flex-row",
        )}
      >
        <div class="flex min-h-0 min-w-0" style={{ flex: `${ratio()} 1 0%` }}>
          {renderPane(() => node().a, [...path, "a"])}
        </div>
        <ResizeHandle
          aria-label="Resize panes"
          orientation={node().dir === "col" ? "vertical" : "horizontal"}
          divider="hover"
          onResize={onResize}
          onResizeEnd={onResizeEnd}
        />
        <div
          class="flex min-h-0 min-w-0"
          style={{ flex: `${1 - ratio()} 1 0%` }}
        >
          {renderPane(() => node().b, [...path, "b"])}
        </div>
      </div>
    );
  };

  /** Branching on the *kind* is what keeps a pane's DOM alive across a layout that
   *  is a new value every time it changes — see the module note. */
  const renderPane = (
    node: Accessor<ViewportPane>,
    path: PanePath,
  ): JSX.Element => {
    const kind = createMemo(() => node().kind);
    // Which surface, as its own memo, so what mounts it tracks *the id* and not
    // the node it was read off. Reading `node().surface` straight into the
    // renderer would make the surface's whole subtree a dependent of the layout:
    // every ratio nudge would rebuild it, and rebuilding a surface re-creates its
    // resources — five refetches and a `Suspense` fallback flashed over the entire
    // room for a divider moved four pixels. It keeps the last id rather than going
    // undefined, so the branch on its way out is never asked to render nothing.
    const surface = createMemo<SurfaceId | undefined>((prev) =>
      node().kind === "leaf" ? (node() as LeafPane).surface : prev,
    );
    return (
      <Switch>
        <Match when={kind() === "leaf"}>
          {renderSurface(() => surface() as SurfaceId)}
        </Match>
        <Match when={kind() === "stack"}>
          {renderStack(() => node() as StackPane)}
        </Match>
        <Match when={kind() === "split"}>
          {renderSplit(() => node() as SplitPane, path)}
        </Match>
      </Switch>
    );
  };

  return (
    <div class="flex h-full min-h-0 flex-col">
      {/* Portalled, so it renders nothing where it sits. The items are read when it
          opens, from whichever surface opened it. */}
      <ContextMenu
        api={menu}
        items={() => {
          const id = menu.openKey();
          return id !== null && isSurfaceId(id) ? paneMenu(id) : [];
        }}
      />
      {/* `For`/`Show` rather than `.map` and a ternary. A ternary's guard does not
          gate its own branches in Solid — the child expression compiles to a
          computation of its own and re-runs when the layout changes, so a panel
          region that has just emptied reaches the renderer as null. */}
      <For each={props.layout.strips}>
        {(id) => <div class="shrink-0">{renderSurface(() => id)}</div>}
      </For>
      <Show when={props.layout.panels}>
        {(panels) => (
          <div
            ref={(el) => onMount(() => observePanelBox(el))}
            class="flex min-h-0 flex-1"
          >
            {renderPane(panels, [])}
          </div>
        )}
      </Show>
    </div>
  );
}
