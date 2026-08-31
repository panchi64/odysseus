/**
 * The mode context — which kind of work the operator is currently looking at.
 *
 * One signal doing three jobs, because they are one fact: it decides what the *next new*
 * conversation will be, which threads the rail lists, and which signature accent the whole
 * window paints. Opening an existing thread points it at that thread, so the three can
 * never disagree with what is on screen.
 *
 * **It lives in `lib/stores/` rather than in the chat feature for the same reason
 * `lib/modes.ts` does.** The app shell and the theme layer read it, and a store owned by a
 * feature and imported by the design system would be a dependency pointing the wrong way.
 * Chat is the only surface that *writes* it today; that is a fact about the product, not a
 * reason to bury it there.
 *
 * The document-root stamp lives here too, and deliberately: it is a DOM write against
 * `<html>`, which no component owns, so the alternative is every consumer remembering to
 * do it. Held under its own never-disposed root, like the other app-wide stores — the mode
 * outlives any screen that happens to be mounted.
 */

import {
  createEffect,
  createRoot,
  createSignal,
  type Accessor,
} from "solid-js";
import { DEFAULT_SESSION_MODE, type SessionMode } from "~/lib/modes";
import { applySessionMode } from "~/ui";

interface SessionModeStore {
  mode: Accessor<SessionMode>;
  setMode: (mode: SessionMode) => void;
  /** The project a *code* thread would open against. Only meaningful while the mode is
   *  `code`, but held beside it rather than inside a branch: the operator's last choice
   *  should survive a detour through Normal and back. */
  codeProjectId: Accessor<string | undefined>;
  setCodeProjectId: (id: string | undefined) => void;
}

const store: SessionModeStore = createRoot(() => {
  const [mode, setMode] = createSignal<SessionMode>(DEFAULT_SESSION_MODE);
  const [codeProjectId, setCodeProjectId] = createSignal<string | undefined>(
    undefined,
  );
  // Stamped on the document root so the cascade paints the signature accent for the
  // mode — the same shape `applyTheme` has for the other axis.
  createEffect(() => applySessionMode(mode()));
  return { mode, setMode, codeProjectId, setCodeProjectId };
});

export const sessionModeContext = store;
export const activeSessionMode = store.mode;
export const setActiveSessionMode = store.setMode;
export const codeProjectId = store.codeProjectId;
export const setCodeProjectId = store.setCodeProjectId;
