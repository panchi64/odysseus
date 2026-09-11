import type { IconName, Status } from "~/ui";

/** Ambient activity on a nav item (unread mail, a degraded service). The shared
 *  `Status` union, not a nav-local one, so the state→accent mapping can't fork. */
export type NavIndicator = Status;

export interface NavItem {
  label: string;
  href: string;
  icon: IconName;
  /** One-line capability description. Hover tooltip on the row, subtitle in the
   *  switcher, and matched by search — so a surface hidden behind its area is
   *  still findable by what it does. */
  description: string;
  indicator?: NavIndicator;
  /** Whether this surface is wired to the backend. Unconnected surfaces are
   *  marked in the rail and overlaid with a NOT CONNECTED banner. */
  connected?: boolean;
}

/** A group of pages. Every area's header is always visible in the rail; which
 *  section is expanded follows the route — derived, never stored — so a deep
 *  link, the back button, and a search jump all reconcile the rail on their
 *  own. */
export interface NavArea {
  id: string;
  /** Switcher label, uppercase. */
  label: string;
  icon: IconName;
  description: string;
  items: NavItem[];
}

/** A destination kept outside the switcher, always one click away. A pin is a
 *  single page, not a group — that is why it isn't an area with one item: the
 *  switcher lists groups, and a lone page in that list has nothing to switch to. */
/**
 * One row the rail draws, and where.
 *
 * A row is *placement only*. It says nothing about whether a surface exists —
 * that is what the surface lists themselves say, and the two are deliberately
 * separate declarations. Deleting a row removes a row and nothing else.
 *
 * It carries the surface rather than an href, so a row pointing at a page that
 * does not exist cannot be written down.
 */
export interface RailRow {
  /** `top` above the switcher, `footer` above COMMS. */
  slot: "top" | "footer";
  /** The surface this row opens. It may be one an area already owns, in which
   *  case the area still owns it and the row is only a shortcut. */
  item: NavItem;
}

/** An item paired with the area that owns it — the unit search returns. A pin
 *  with no area of its own (Chat) matches with `area` undefined. */
export interface NavMatch {
  item: NavItem;
  area?: NavArea;
}

/* ── Settings index ──────────────────────────────────────────────────────────
   Presentation metadata for a platform setting the palette can change without
   navigating to its page. An entry is a *pointer* to an existing seam, never a
   second home for the value: `read` reads whatever the feature's `data.ts` (or a
   theme/storage helper) already exposes, and `write` calls that seam's own
   action. Nothing here validates, decides, or persists on its own — the backend
   re-validates every write and stays the authority. */

export type SettingKind = "toggle" | "number" | "choice";

/** One option of a `choice` setting. `value` is the seam's own vocabulary; `label`
 *  is what the row shows. */
export interface SettingChoice {
  value: string;
  label: string;
}

interface SettingBase {
  /** Stable identity, `group.thing` — the row key, and what a test names. */
  id: string;
  label: string;
  /** Extra terms the row is findable by, beyond its label — the words an
   *  operator reaches for rather than the ones the label happens to use. */
  keywords: string[];
  /** The section the row files under, uppercase. Doubles as a search term. */
  group: string;
}

export interface ToggleSetting extends SettingBase {
  kind: "toggle";
  /** `undefined` while the seam behind it hasn't loaded. */
  read: () => boolean | undefined;
  write: (next: boolean) => void | Promise<void>;
}

export interface NumberSetting extends SettingBase {
  kind: "number";
  read: () => number | undefined;
  write: (next: number) => void | Promise<void>;
  /** Suffix shown after the value (`%`, `s`). Presentation only. */
  unit?: string;
  /** Bounds for the inline field's immediate feedback. NOT enforcement — the
   *  backend re-validates and can reject a value these would have allowed. */
  min?: number;
  max?: number;
}

export interface ChoiceSetting extends SettingBase {
  kind: "choice";
  options: readonly SettingChoice[];
  read: () => string | undefined;
  write: (next: string) => void | Promise<void>;
}

export type SettingEntry = ToggleSetting | NumberSetting | ChoiceSetting;

/** What a `read()` can return, across the three kinds. */
export type SettingValue = boolean | number | string | undefined;

/** One palette result. The palette spans two kinds of thing — a page you go to
 *  and a setting you change where it stands — so the row it renders, the key it
 *  answers to, and what Enter does all follow from this tag. */
export type PaletteHit =
  { kind: "nav"; nav: NavMatch } | { kind: "setting"; setting: SettingEntry };
