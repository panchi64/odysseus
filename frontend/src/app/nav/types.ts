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
export interface NavPin {
  /** `top` sits above the switcher, `footer` beside OPERATOR/LOCK. */
  slot: "top" | "footer";
  /** The page the pin opens. It may point at a page that also lives in an area
   *  (Settings opens the first SYSTEM page), in which case the area still owns
   *  it and the pin is only a shortcut. */
  item: NavItem;
}

/** An item paired with the area that owns it — the unit search returns. A pin
 *  with no area of its own (Chat) matches with `area` undefined. */
export interface NavMatch {
  item: NavItem;
  area?: NavArea;
}
