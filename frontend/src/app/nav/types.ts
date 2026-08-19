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

/** A top-level destination group. Exactly one area is active at a time, and which
 *  one is derived from the route — never stored — so a deep link, the back
 *  button, and a search jump all reconcile the switcher on their own. */
export interface NavArea {
  id: string;
  /** Switcher label, uppercase. */
  label: string;
  icon: IconName;
  description: string;
  items: NavItem[];
  /** Pin this area's entry point outside the switcher so it's always one click
   *  away: `top` sits under the switcher, `footer` beside OPERATOR/LOCK. */
  anchor?: "top" | "footer";
  /** Which href the pinned row points at, when it isn't the first item. */
  anchorHref?: string;
  /** Label for the pinned row, when it shouldn't read as the area name. */
  anchorLabel?: string;
}

/** An item paired with the area it belongs to — the unit search returns. */
export interface NavMatch {
  item: NavItem;
  area: NavArea;
}
