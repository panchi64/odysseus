import { legacySettingsHref } from "~/app/settings-dialog/legacy";
import { AREAS, PINS } from "./areas";
import { searchSettings } from "./settings-search";
import type {
  NavArea,
  NavItem,
  NavMatch,
  PaletteHit,
  SettingEntry,
} from "./types";

export { AREAS, PINS };
export type {
  NavArea,
  NavIndicator,
  NavItem,
  NavMatch,
  NavPin,
  PaletteHit,
  SettingEntry,
  SettingChoice,
  SettingKind,
  SettingValue,
  ChoiceSetting,
  NumberSetting,
  ToggleSetting,
} from "./types";
export {
  searchSettings,
  formatSettingValue,
  nextChoiceValue,
  parseSettingNumber,
  isChoiceSetting,
  isNumberSetting,
} from "./settings-search";

export const TOP_PINS = PINS.filter((p) => p.slot === "top").map((p) => p.item);

/** Every page in the nav, area-owned or not. A pin that only shortcuts into an
 *  area is skipped — its page is already here under its own label, and listing
 *  it twice would give search two rows for one destination. */
export function flattenNav(areas: NavArea[] = AREAS): NavMatch[] {
  const owned = areas.flatMap((area) =>
    area.items.map((item) => ({ item, area })),
  );
  const hrefs = new Set(owned.map((m) => m.item.href));
  return [
    ...owned,
    ...PINS.filter((p) => !hrefs.has(p.item.href)).map((p) => ({
      item: p.item,
    })),
  ];
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

/** The area a route belongs to, or `undefined` when no area owns it — `/`, a
 *  pinned page like `/chat`, and any unlisted route. The caller renders a neutral
 *  state rather than guessing: naming an area the operator isn't in is worse than
 *  naming none. */
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
  // A path that only forwards into the settings dialog is connected by virtue of
  // where it lands. The forward is instant, but the shell reads this on the way
  // through, and a NOT CONNECTED banner flashing over a redirect would be a lie
  // told very briefly.
  if (legacySettingsHref(pathname)) return true;
  return flattenNav(areas).some(
    ({ item }) =>
      item.connected &&
      (matchesHref(pathname, item.href) ||
        item.href.startsWith(`${pathname}/`)),
  );
}

/** Search across every area — label first, then description, so a surface is
 *  findable by what it does. The fast jump: a keystroke beats expanding a
 *  section and scanning its rows. */
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

/* ── The palette's two-kind result list ─────────────────────────────────────── */

/** What the palette is looking through. Both sides are injectable for the same
 *  reason `areas` is: the rules below are exercised against fixtures. */
export interface PaletteSources {
  areas?: NavArea[];
  settings?: SettingEntry[];
}

/** One row, with the flat index its section can't work out on its own. The
 *  cursor keys move through the flat list while the eye reads sections, so the
 *  index has to survive the grouping. */
export interface PaletteRow {
  hit: PaletteHit;
  index: number;
}

export interface PaletteSection {
  label: string;
  rows: PaletteRow[];
}

/** The heading pages file under. Settings file under their own group names, so
 *  a settings row can never be mistaken for somewhere to navigate. */
export const PAGES_SECTION = "PAGES";

function toHits(nav: NavMatch[], settings: SettingEntry[] = []): PaletteHit[] {
  return [
    ...nav.map((m): PaletteHit => ({ kind: "nav", nav: m })),
    ...settings.map((s): PaletteHit => ({ kind: "setting", setting: s })),
  ];
}

/** Search both kinds at once. Pages come first as a block: navigating is still
 *  what the palette is mostly for, and a settings row that jumped above the page
 *  you were reaching for would change what `Enter` does out from under you. */
export function searchPalette(
  query: string,
  sources: PaletteSources = {},
): PaletteHit[] {
  return toHits(
    searchNav(query, sources.areas ?? AREAS),
    searchSettings(query, sources.settings ?? []),
  );
}

/** The empty-query listing — every page, then every setting. The palette opens
 *  onto a directory rather than a blank overlay, and now that it holds two kinds
 *  of thing the directory is what teaches that the settings are in here at all. */
export function paletteDirectory(sources: PaletteSources = {}): PaletteHit[] {
  return toHits(flattenNav(sources.areas ?? AREAS), sources.settings ?? []);
}

/** Fold a flat result list into labelled sections, preserving order and carrying
 *  each row's flat index through. Sections appear in first-appearance order —
 *  the registry's declaration order is the operator-facing order, so grouping
 *  must not re-sort it. */
export function paletteSections(hits: PaletteHit[]): PaletteSection[] {
  const sections: PaletteSection[] = [];
  const byLabel = new Map<string, PaletteSection>();
  hits.forEach((hit, index) => {
    const label = hit.kind === "nav" ? PAGES_SECTION : hit.setting.group;
    let section = byLabel.get(label);
    if (!section) {
      section = { label, rows: [] };
      byLabel.set(label, section);
      sections.push(section);
    }
    section.rows.push({ hit, index });
  });
  return sections;
}
