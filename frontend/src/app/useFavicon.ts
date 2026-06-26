import { createEffect } from "solid-js";
import { useTheme } from "~/ui";
import {
  platformStatus,
  type PlatformStatus,
} from "~/lib/stores/platformStatus";

/** Which token carries the status accent on the reticle ring + cardinal ticks. */
const ACCENT_VAR: Record<PlatformStatus, string> = {
  ready: "--accent-nominal", // green — up, at rest
  busy: "--accent-info", // blue — a turn is streaming
  error: "--accent-alert", // red — backend down or a run errored
};

/** The Terminal-HUD reticle, parameterized by the four colors it draws with. Geometry
 *  is kept verbatim in lockstep with `public/favicon.svg` (the static pre-JS / .ico
 *  fallback) — edit both together. Here the colors are token slots so the mark tracks
 *  the active theme and the live platform status. */
function reticleSvg(c: {
  bg: string;
  line: string;
  dim: string;
  accent: string;
}): string {
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="32" height="32" shape-rendering="geometricPrecision">
  <rect width="32" height="32" fill="${c.bg}"/>
  <rect x="1" y="1" width="30" height="30" fill="none" stroke="${c.line}" stroke-width="1"/>
  <g stroke="${c.dim}" stroke-width="1">
    <path d="M4.5 2.6V6.4M2.6 4.5H6.4"/>
    <path d="M27.5 2.6V6.4M25.6 4.5H29.4"/>
    <path d="M4.5 25.6V29.4M2.6 27.5H6.4"/>
    <path d="M27.5 25.6V29.4M25.6 27.5H29.4"/>
  </g>
  <circle cx="16" cy="16" r="8" fill="none" stroke="${c.accent}" stroke-width="2.75"/>
  <g stroke="${c.accent}" stroke-width="2.25" stroke-linecap="butt">
    <path d="M16 2.6V5.6"/>
    <path d="M16 26.4V29.4"/>
    <path d="M2.6 16H5.6"/>
    <path d="M26.4 16H29.4"/>
  </g>
</svg>`;
}

/** The SVG-favicon link declared in `entry-server.tsx`, created on demand if absent. */
function iconLink(): HTMLLinkElement {
  let link = document.querySelector<HTMLLinkElement>(
    'link[rel="icon"][type="image/svg+xml"]',
  );
  if (!link) {
    link = document.createElement("link");
    link.rel = "icon";
    link.type = "image/svg+xml";
    document.head.appendChild(link);
  }
  return link;
}

/**
 * Keeps the browser favicon in sync with the live platform status — green at rest,
 * blue while inferencing, red when the backend is down or a run errored — and with the
 * active theme. Colors are resolved from the design tokens on `<html>` at draw time, so
 * the mark adapts to Phosphor/Paper automatically. Call once at the app root.
 */
export function useFavicon(): void {
  const theme = useTheme();
  createEffect(() => {
    const status = platformStatus();
    // Track the active palette so the effect re-runs on a theme toggle / OS change.
    void theme.resolved;
    // Defer the token read to a microtask. A theme change that triggers this effect
    // (notably the OS flipping under "system" preference, via a raw, un-batched
    // matchMedia listener) writes `data-theme` on the same tick but *after* this effect
    // flushes — reading now would resolve the previous palette. The microtask runs once
    // that attribute write has landed, so getComputedStyle sees the current theme.
    queueMicrotask(() => {
      const cs = getComputedStyle(document.documentElement);
      const tok = (name: string) => cs.getPropertyValue(name).trim();
      const svg = reticleSvg({
        bg: tok("--bg"),
        line: tok("--line"),
        dim: tok("--text-dim"),
        accent: tok(ACCENT_VAR[status]),
      });
      iconLink().href = `data:image/svg+xml,${encodeURIComponent(svg)}`;
    });
  });
}
