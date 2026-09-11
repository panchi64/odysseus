/**
 * The one place a surface id becomes a component.
 *
 * `surfaces.ts` says what exists and in what order; this says what each entry renders,
 * and nothing else knows both — so adding a surface is one row in each file. The map is
 * keyed by `SurfaceId`, which is itself derived from the registry array, so a surface
 * declared without a renderer is a **compile error** rather than a pane that mounts
 * blank. (The settings dialog's equivalent map settles for a dev-time warning, because
 * importing it constructs sixteen features' resources; these are chat components already
 * in the bundle, so the type error is free and strictly better.)
 *
 * Every value is a **thunk**, not an element. Solid evaluates JSX eagerly, so a map of
 * elements would construct every surface — and every resource behind it — the moment this
 * module is read, rather than when one is actually on screen.
 *
 * A renderer takes the context and reaches into it for what its own surface needs. That
 * is deliberately not a per-surface prop bag: the context carries what is true of *any*
 * surface, and a surface's own data is its business to fetch from the facade.
 */

import type { JSX } from "solid-js";
import { AgentsSurface } from "../components/AgentsSurface";
import { DiffSurface } from "../components/DiffSurface";
import { FilesSurface } from "../components/FilesSurface";
import { PlanSurface } from "../components/PlanSurface";
import { ViewportPanel } from "../components/ViewportPanel";
import type { ChatViewport } from "../useChatViewport";
import { SURFACE_BY_ID, type SurfaceId } from "./surfaces";

/** What every surface is handed. Generic on purpose — see the module note. */
export interface SurfaceContext {
  viewport: ChatViewport;
  /** Dismiss the panel from this surface's close control. The mount supplies it,
   *  because leaving the aside and leaving the full-screen sheet are different acts. */
  onClose: () => void;
  onToggleFullscreen: () => void;
}

export const SURFACE_RENDERERS: Record<
  SurfaceId,
  (ctx: SurfaceContext) => JSX.Element
> = {
  plan: (ctx) => {
    const spec = SURFACE_BY_ID.plan;
    return (
      <PlanSurface
        items={ctx.viewport.plan}
        maxRows={spec.shape === "strip" ? spec.maxRows : 8}
      />
    );
  },
  agents: (ctx) => {
    const spec = SURFACE_BY_ID.agents;
    return (
      <AgentsSurface
        runs={ctx.viewport.subagents}
        maxRows={spec.shape === "strip" ? spec.maxRows : 6}
      />
    );
  },
  diff: (ctx) => (
    <DiffSurface
      branch={ctx.viewport.branch}
      onChanged={ctx.viewport.refetchBranch}
      fontStep={ctx.viewport.state().fontStep}
      softWrap={ctx.viewport.state().softWrap}
    />
  ),
  files: (ctx) => (
    <FilesSurface
      items={ctx.viewport.items}
      fontStep={ctx.viewport.state().fontStep}
      softWrap={ctx.viewport.state().softWrap}
    />
  ),
  view: (ctx) => (
    <ViewportPanel
      items={ctx.viewport.items()}
      selectedKey={ctx.viewport.viewState().pinnedKey}
      onSelect={ctx.viewport.selectView}
      activeTab={ctx.viewport.viewState().activeTab}
      onSelectTab={ctx.viewport.requestTab}
      fontStep={ctx.viewport.state().fontStep}
      onFontStep={(step) => ctx.viewport.patch({ fontStep: step })}
      softWrap={ctx.viewport.state().softWrap}
      onToggleWrap={() =>
        ctx.viewport.patch({ softWrap: !ctx.viewport.state().softWrap })
      }
      fullscreen={ctx.viewport.state().fullscreen}
      onToggleFullscreen={ctx.onToggleFullscreen}
      // A pane's own collapse closes *that pane*, not the panel — the same act
      // its context menu offers. Closing the last one closes the panel anyway,
      // so the single-surface case reads exactly as it did.
      onClose={() => ctx.viewport.closeSurface("view")}
      onKeeper={ctx.viewport.toggleKeeper}
      panelRef={ctx.viewport.panelRef}
    />
  ),
};
