import { splitProps, type JSX } from "solid-js";
import { cx } from "../cx";

export interface DeepFieldProps {
  class?: string;
}

/** The licensed moment (§11.1) — a graticule, the limb of something large, and a
 *  scatter of stars, drawn behind a region that has nothing else in it.
 *
 *  **One per screen, and only where nothing competes**: an empty state, the auth
 *  screens, the launchpad hero, a lightbox. Never behind a transcript, never inside a
 *  panel holding data, never as an app-wide backdrop — that last one is the
 *  "atmosphere in the reading path" failure §11 exists to prevent, and it does not
 *  stop being that failure because the atmosphere is pretty.
 *
 *  **It loses every fight it picks.** On the launchpad it sits behind the composer,
 *  which already carries `shadow-bloom`; two attention devices in the same 200px means
 *  this one has to be the quieter. The neutral marks run at single-digit alpha and only
 *  the limb takes `--accent`, at 22% — enough that the figure follows the session mode
 *  and any operator accent override, not enough to spend the accent budget (§5.4).
 *
 *  Static by construction. A drifting starfield would be decoration that moves, which
 *  is the one thing worse than decoration, and it would put the human motion register
 *  somewhere the operator is trying to read. Nothing here animates, so there is nothing
 *  for `prefers-reduced-motion` to collapse.
 *
 *  Purely decorative, so `aria-hidden` and `pointer-events-none`: it must never take a
 *  click meant for the composer sitting on top of it.
 */
export function DeepField(props: DeepFieldProps): JSX.Element {
  const [local] = splitProps(props, ["class"]);
  return (
    <svg
      class={cx("ody-deep-field text-bright", local.class)}
      viewBox="0 0 1056 320"
      preserveAspectRatio="xMidYMid slice"
      aria-hidden="true"
    >
      {/* Graticule — the 4px grid's own ancestor, at the scale of a survey chart. */}
      <g stroke="currentColor" stroke-opacity="0.05" stroke-width="1">
        <path d="M0 40h1056M0 80h1056M0 120h1056M0 160h1056M0 200h1056M0 240h1056M0 280h1056" />
        <path d="M88 0v320M176 0v320M264 0v320M352 0v320M440 0v320M528 0v320M616 0v320M704 0v320M792 0v320M880 0v320M968 0v320" />
      </g>

      {/* The limb: a body far too large to see the whole of. The ellipse is mostly
          off-canvas on purpose — what makes a horizon read as enormous is that its
          curvature is barely perceptible across the width of the frame. */}
      <ellipse
        cx="528"
        cy="700"
        rx="900"
        ry="470"
        fill="none"
        stroke="var(--accent)"
        stroke-opacity="0.22"
        stroke-width="1"
      />
      <ellipse
        cx="528"
        cy="718"
        rx="900"
        ry="470"
        fill="none"
        stroke="currentColor"
        stroke-opacity="0.05"
        stroke-width="1"
      />

      {/* An orbital track crossing it. Dashed, because a predicted path is not a
          thing you can see — it is a thing that has been computed. */}
      <path
        d="M-40 286C240 150 816 150 1096 286"
        fill="none"
        stroke="currentColor"
        stroke-opacity="0.09"
        stroke-width="1"
        stroke-dasharray="3 5"
      />

      <g fill="currentColor">
        <circle cx="96" cy="44" r="1" fill-opacity="0.34" />
        <circle cx="212" cy="86" r="0.8" fill-opacity="0.20" />
        <circle cx="304" cy="30" r="1.2" fill-opacity="0.28" />
        <circle cx="398" cy="104" r="0.8" fill-opacity="0.16" />
        <circle cx="486" cy="52" r="1" fill-opacity="0.24" />
        <circle cx="604" cy="36" r="0.8" fill-opacity="0.30" />
        <circle cx="712" cy="92" r="1.1" fill-opacity="0.20" />
        <circle cx="822" cy="46" r="0.9" fill-opacity="0.28" />
        <circle cx="928" cy="98" r="1" fill-opacity="0.18" />
        <circle cx="1004" cy="58" r="0.8" fill-opacity="0.26" />
        <circle cx="150" cy="148" r="0.8" fill-opacity="0.14" />
        <circle cx="880" cy="152" r="0.8" fill-opacity="0.14" />
        <circle cx="56" cy="94" r="0.7" fill-opacity="0.18" />
        <circle cx="1040" cy="126" r="0.7" fill-opacity="0.16" />
      </g>

      {/* A reticle on one of them, bracketing nothing in particular — the instrument
          is pointed at something whether or not the operator asked it to be. */}
      <g
        stroke="currentColor"
        stroke-opacity="0.16"
        stroke-width="1"
        fill="none"
      >
        <circle cx="928" cy="98" r="9" />
        <path d="M928 83v6M928 107v-6M913 98h6M943 98h-6" />
      </g>
    </svg>
  );
}
