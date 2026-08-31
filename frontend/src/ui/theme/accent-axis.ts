/**
 * One **axis** of the accent overrides — the shape both stores turned out to be.
 *
 * `accent-store` reads and writes `overrides[theme][token]`; `session-accent-store`
 * reads and writes `overrides.sessionAccent[theme][mode]`. That extra key level was the
 * only difference between them, and yet each carried its own copy of four accessors, its
 * own clear-on-default rule, and its own prune-the-empty-parent unwind — one level deep
 * on one axis, two on the other, and the guard in `accent-overrides` forked a third time
 * to sanitize them. Four rules, three implementations, and the same bug available in
 * each: an override cleared back to its shipped value leaving an empty object behind, so
 * `hasAccentOverrides` keeps answering yes and the RESET ALL control never goes away.
 *
 * So the path is a parameter and the rules are written once. What is left in each store
 * is the vocabulary of its own axis — which keys, which shipped values — plus the one
 * genuine asymmetry the session axis has (Normal *is* the base token and delegates).
 *
 * Deliberately free of any runtime dependency on `accent-overrides`: the stored blob and
 * the update function are handed in, so the module that owns the storage can use these
 * helpers to sanitize what it reads without the two importing each other.
 */

import type { AccentOverrides } from "./accent-overrides";
import { normalizeHex } from "./contrast";
import type { ThemeMode } from "./theme-store";

/** Where an axis's per-theme map sits inside the stored blob, outermost key first:
 *  `["phosphor"]` for the accent meanings, `["sessionAccent", "phosphor"]` for the
 *  session signatures. */
export type AxisPath = readonly string[];

type Node = Record<string, unknown>;

/** The map at `path`, or undefined. Guards every level, because the same walk is used
 *  over `localStorage`'s answer — which is user-writable and may be any shape at all. */
export function readAt(
  value: unknown,
  path: AxisPath,
): Record<string, string> | undefined {
  let node: unknown = value;
  for (const key of path) {
    if (!node || typeof node !== "object") return undefined;
    node = (node as Node)[key];
  }
  return node && typeof node === "object"
    ? (node as Record<string, string>)
    : undefined;
}

/** `value` with the map at `path` replaced, **pruning every level left empty**. Copies
 *  down the path rather than mutating, so the signal sees a new object and repaints. */
export function writeAt(
  value: AccentOverrides,
  path: AxisPath,
  entry: Record<string, string>,
): AccentOverrides {
  return writeNode(value as Node, path, entry) as AccentOverrides;
}

function writeNode(
  node: Node,
  path: AxisPath,
  entry: Record<string, string>,
): Node {
  const [head, ...rest] = path;
  const child = rest.length
    ? writeNode((node[head] as Node) ?? {}, rest, entry)
    : entry;
  const next: Node = { ...node };
  if (Object.keys(child).length > 0) next[head] = child;
  else delete next[head];
  return next;
}

/** What an axis is, said once: where it lives and what it falls back to. */
export interface AccentAxisSpec<K extends string> {
  path: (theme: ThemeMode) => AxisPath;
  /** The shipped value a key resolves to when nothing is overridden. Read from the
   *  defaults tables rather than the cascade — by the time any of this runs the
   *  pre-paint script has applied the overrides on top, so the cascade holds the
   *  *current* value, which is exactly not what "is this overridden" is asking. */
  shipped: (theme: ThemeMode, key: K) => string;
}

/** The stored blob and the one way to replace it. */
export interface AccentStoreHandle {
  read: () => AccentOverrides;
  update: (next: AccentOverrides, options?: { persist?: boolean }) => void;
}

export interface AccentAxis<K extends string> {
  value: (theme: ThemeMode, key: K) => string;
  isOverridden: (theme: ThemeMode, key: K) => boolean;
  set: (
    theme: ThemeMode,
    key: K,
    value: string,
    options?: { persist?: boolean },
  ) => void;
  reset: (theme: ThemeMode, key: K, options?: { persist?: boolean }) => void;
}

export function createAccentAxis<K extends string>(
  spec: AccentAxisSpec<K>,
  store: AccentStoreHandle,
): AccentAxis<K> {
  const entryOf = (theme: ThemeMode) => readAt(store.read(), spec.path(theme));

  const reset: AccentAxis<K>["reset"] = (theme, key, options) => {
    const entry = { ...entryOf(theme) };
    delete entry[key];
    store.update(writeAt(store.read(), spec.path(theme), entry), options);
  };

  return {
    value: (theme, key) => entryOf(theme)?.[key] ?? spec.shipped(theme, key),
    isOverridden: (theme, key) => entryOf(theme)?.[key] !== undefined,
    set: (theme, key, value, options) => {
      const hex = normalizeHex(value);
      if (!hex) return;
      // A value equal to the shipped one clears the override rather than storing it,
      // so "I set it back by hand" and "I pressed reset" leave the same state —
      // otherwise the reset control would linger beside a key that is no longer
      // overriding anything.
      if (hex === spec.shipped(theme, key)) {
        reset(theme, key, options);
        return;
      }
      store.update(
        writeAt(store.read(), spec.path(theme), {
          ...entryOf(theme),
          [key]: hex,
        }),
        options,
      );
    },
    reset,
  };
}

/** Copy one axis out of an untrusted blob into a clean one: keys this build has a rule
 *  for, values that normalize to a real hex, nothing else, and no empty levels left
 *  behind. This runs over `localStorage`, whose contents are concatenated into a
 *  stylesheet, so it is load-bearing rather than tidiness. */
export function sanitizeAxis<K extends string>(
  raw: unknown,
  clean: AccentOverrides,
  themes: readonly ThemeMode[],
  spec: {
    path: (theme: ThemeMode) => AxisPath;
    accepts: (key: string) => key is K;
  },
): AccentOverrides {
  let next = clean;
  for (const theme of themes) {
    const entry = readAt(raw, spec.path(theme));
    if (!entry) continue;
    const kept: Record<string, string> = {};
    for (const [key, value] of Object.entries(entry)) {
      if (!spec.accepts(key) || typeof value !== "string") continue;
      const hex = normalizeHex(value);
      if (hex) kept[key] = hex;
    }
    next = writeAt(next, spec.path(theme), kept);
  }
  return next;
}
