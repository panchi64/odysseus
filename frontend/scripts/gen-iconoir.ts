/**
 * Iconoir → registry body generator.
 *
 * The icon registry (`src/ui/icons/registry.tsx`) stores *inner* SVG markup only;
 * the `Icon` primitive supplies the <svg> wrapper, sizing, stroke, currentColor,
 * and joins. Iconoir ships geometry on a 24px grid (design-system §5's idiom:
 * geometric, native 1.5px stroke), so each generated entry declares `viewBox: 24`
 * and the primitive normalizes stroke weight to the 16px grid.
 *
 * This is the on-demand pull mechanism: add `registryName: "iconoir-name"` to MAP,
 * run `bun run scripts/gen-iconoir.ts`, and paste the printed entries into the
 * registry. Only the inlined markup ships. Iconoir is deliberately *not* a
 * dependency — it was an ~700 KB devDependency serving a generator that runs a
 * few times a year, so the set is fetched here instead. That makes this script
 * (and only this script) need network access.
 *
 * Redundant per-element attributes (fill/stroke/stroke-*) are stripped so the
 * primitive's uniform values win, matching the hand-rolled entries' style.
 */
export {}; // Nothing is exported; this marks the file a module so top-level await type-checks.

const ICONS_URL = "https://cdn.jsdelivr.net/npm/@iconify-json/iconoir@1/icons.json";

/** registry IconName → Iconoir icon name. Bespoke HUD glyphs are omitted (kept hand-rolled). */
const MAP: Record<string, string> = {
  "chevron-right": "nav-arrow-right",
  "chevron-down": "nav-arrow-down",
  "chevron-up": "nav-arrow-up",
  "chevron-left": "nav-arrow-left",
  "arrow-right": "arrow-right",
  plus: "plus",
  minus: "minus",
  close: "xmark",
  check: "check",
  search: "search",
  menu: "menu",
  warning: "warning-triangle",
  info: "info-circle",
  lock: "lock",
  key: "key",
  eye: "eye",
  edit: "edit-pencil",
  trash: "trash",
  refresh: "refresh",
  download: "download",
  upload: "upload",
  send: "send-diagonal",
  chat: "chat-bubble-empty",
  play: "play",
  pause: "pause",
  settings: "settings",
  user: "user",
  users: "group",
  mail: "mail",
  calendar: "calendar",
  file: "page",
  note: "notes",
  image: "media-image",
  database: "database",
  cpu: "cpu",
  terminal: "terminal",
  code: "code",
  activity: "activity",
  link: "link",
  mic: "microphone",
  clock: "clock",
  grid: "view-grid",
  archive: "archive",
  copy: "copy",
  pin: "pin",
  sun: "sun-light",
  moon: "half-moon",
  system: "computer",
  library: "book",
  bell: "bell",
};

const STRIP = /\s(?:fill|stroke|stroke-width|stroke-linecap|stroke-linejoin)="[^"]*"/g;

const response = await fetch(ICONS_URL);
if (!response.ok) {
  throw new Error(
    `could not fetch Iconoir: ${response.status} ${response.statusText} — ${ICONS_URL}`,
  );
}
const set = (await response.json()) as { icons: Record<string, { body: string }> };

for (const [name, iconoir] of Object.entries(MAP)) {
  const icon = set.icons[iconoir];
  if (!icon) {
    console.error(`✗ missing in Iconoir: ${iconoir} (for "${name}")`);
    continue;
  }
  const body = icon.body.replace(STRIP, "").replace(/\s+\/>/g, " />");
  const key = /^[a-z][a-z0-9]*$/.test(name) ? name : `"${name}"`;
  console.log(`  ${key}: g24(() => (<>${body}</>)),`);
}
