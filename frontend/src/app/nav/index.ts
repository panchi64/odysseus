import { AREAS } from "./areas";
import type { NavArea, NavItem, NavMatch } from "./types";

export { AREAS };
export type { NavArea, NavIndicator, NavItem, NavMatch } from "./types";

export const TOP_ANCHORS = AREAS.filter((a) => a.anchor === "top");
export const FOOTER_ANCHORS = AREAS.filter((a) => a.anchor === "footer");

/** The row a pinned area points at: its override, or its first item. */
export function anchorItem(area: NavArea): NavItem {
  const target = area.anchorHref
    ? (area.items.find((i) => i.href === area.anchorHref) ?? area.items[0])
    : area.items[0];
  return area.anchorLabel ? { ...target, label: area.anchorLabel } : target;
}

export function flattenNav(areas: NavArea[] = AREAS): NavMatch[] {
  return areas.flatMap((area) => area.items.map((item) => ({ item, area })));
}

function matchesHref(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}

/** Longest match wins — without that rule `/admin/access-tokens` resolves
 *  through `/admin/tokens`, and every detail route lands on whichever item
 *  happened to be declared first. */
function longestMatch(
  pathname: string,
  areas: NavArea[],
): NavMatch | undefined {
  let best: NavMatch | undefined;
  let bestLen = -1;
  for (const match of flattenNav(areas)) {
    if (
      matchesHref(pathname, match.item.href) &&
      match.item.href.length > bestLen
    ) {
      best = match;
      bestLen = match.item.href.length;
    }
  }
  return best;
}

/** The area a route belongs to, or `undefined` when nothing claims it — `/` and
 *  any unlisted route. The caller renders a neutral state rather than guessing:
 *  naming an area the operator isn't in is worse than naming none. */
export function areaForPath(
  pathname: string,
  areas: NavArea[] = AREAS,
): NavArea | undefined {
  const match = longestMatch(pathname, areas);
  if (!match && pathname !== "/" && import.meta.env.DEV) {
    console.warn(`[nav] no area claims "${pathname}"`);
  }
  return match?.area;
}

/** The item a route sits on or under, so a detail route highlights its parent. */
export function itemForPath(
  pathname: string,
  areas: NavArea[] = AREAS,
): NavItem | undefined {
  return longestMatch(pathname, areas)?.item;
}

/** Whether a route is backed by the real backend. Drives the NOT CONNECTED
 *  overlay. `/` has no nav entry but is connected. A parent of connected
 *  children (`/settings`, which redirects into its first section) counts too, so
 *  the redirect doesn't flash an overlay on the way through. */
export function isConnectedRoute(
  pathname: string,
  areas: NavArea[] = AREAS,
): boolean {
  if (pathname === "/") return true;
  return flattenNav(areas).some(
    ({ item }) =>
      item.connected &&
      (matchesHref(pathname, item.href) ||
        item.href.startsWith(`${pathname}/`)),
  );
}

/** Search across every area — label first, then description, so a surface is
 *  findable by what it does. Spanning all areas is what makes showing one at a
 *  time safe: this is the escape hatch. */
export function searchNav(query: string, areas: NavArea[] = AREAS): NavMatch[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  const byLabel: NavMatch[] = [];
  const byDescription: NavMatch[] = [];
  for (const match of flattenNav(areas)) {
    if (match.item.label.toLowerCase().includes(q)) byLabel.push(match);
    else if (match.item.description.toLowerCase().includes(q))
      byDescription.push(match);
  }
  return [...byLabel, ...byDescription];
}
