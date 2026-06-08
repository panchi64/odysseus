import { createMemo, createSignal, type Accessor } from "solid-js";

/**
 * Headless list-view controller — the reusable logic half of the list-scaling
 * paradigm (the visual half is `<ListToolbar/>` in `~/ui`).
 *
 * It owns the *state* of viewing a list (query, sort key + direction, and an
 * optional selection set) and derives the filtered → sorted result. Screens
 * feed it a source accessor (usually a resource), describe how to search and
 * sort, and render `view.items()`. No styling, no DOM — pure state, so it stays
 * in `~/lib` and is unit-testable in isolation.
 *
 *   const view = createListView({
 *     source: () => docs() ?? [],
 *     search: (d) => `${d.title} ${d.author}`,
 *     sorts: {
 *       recent: { label: "NEWEST", compare: (a, b) => a.updatedAt.localeCompare(b.updatedAt) },
 *       name:   { label: "NAME",   compare: (a, b) => a.title.localeCompare(b.title) },
 *     },
 *     initialSort: "recent",
 *     initialDir: "desc",
 *     id: (d) => d.id, // enables bulk selection
 *   });
 */

export type SortDir = "asc" | "desc";

export interface SortDef<T> {
  /** Uppercase label shown in the sort control. */
  label: string;
  /** Ascending comparator; the controller flips it for `desc`. */
  compare: (a: T, b: T) => number;
}

export interface ListViewConfig<T> {
  /** Source rows (may be `undefined` while a resource is loading). */
  source: Accessor<T[] | undefined>;
  /** Haystack string matched (case-insensitively, substring) against the query. */
  search?: (item: T) => string;
  /** Named sort definitions; keys become the sort options. */
  sorts?: Record<string, SortDef<T>>;
  /** Initial sort key (defaults to the first declared sort). */
  initialSort?: string;
  /** Initial direction (defaults to `asc`). */
  initialDir?: SortDir;
  /** Stable identity. Providing it enables the selection API (bulk actions). */
  id?: (item: T) => string;
}

export interface ListView<T> {
  // query
  query: Accessor<string>;
  setQuery: (q: string) => void;
  // sort
  sortKey: Accessor<string | undefined>;
  setSort: (key: string) => void;
  dir: Accessor<SortDir>;
  toggleDir: () => void;
  sortOptions: { value: string; label: string }[];
  // derived rows
  items: Accessor<T[]>;
  total: Accessor<number>;
  count: Accessor<number>;
  isFiltered: Accessor<boolean>;
  reset: () => void;
  // selection (no-ops unless `config.id` is provided)
  selectable: boolean;
  selectedIds: Accessor<Set<string>>;
  selectedCount: Accessor<number>;
  isSelected: (id: string) => boolean;
  toggleOne: (id: string) => void;
  toggleAll: () => void;
  allSelected: Accessor<boolean>;
  selectedItems: Accessor<T[]>;
  clearSelection: () => void;
}

export function createListView<T>(config: ListViewConfig<T>): ListView<T> {
  const sortKeys = config.sorts ? Object.keys(config.sorts) : [];

  const [query, setQuery] = createSignal("");
  const [sortKey, setSortKey] = createSignal<string | undefined>(
    config.initialSort ?? sortKeys[0],
  );
  const [dir, setDir] = createSignal<SortDir>(config.initialDir ?? "asc");
  const [selectedIds, setSelectedIds] = createSignal<Set<string>>(new Set());

  const sortOptions = sortKeys.map((key) => ({
    value: key,
    label: config.sorts![key].label,
  }));

  const base = createMemo(() => config.source() ?? []);

  const filtered = createMemo(() => {
    const q = query().trim().toLowerCase();
    const rows = base();
    if (!q || !config.search) return rows;
    return rows.filter((item) =>
      config.search!(item).toLowerCase().includes(q),
    );
  });

  const items = createMemo(() => {
    const rows = filtered();
    const key = sortKey();
    const def = key && config.sorts ? config.sorts[key] : undefined;
    if (!def) return rows;
    const sorted = [...rows].sort(def.compare);
    return dir() === "desc" ? sorted.reverse() : sorted;
  });

  const idOf = config.id;
  const selectable = !!idOf;

  // Selection scoped to the live source: an id whose row has left base()
  // (tab/album switch, deletion, refetch) is pruned automatically, so the
  // count never lies and a bulk action can never touch a row the user can no
  // longer see. The raw `selectedIds` set is the input; everything user-facing
  // reads through this derived, validated set.
  const validSelectedIds = createMemo<Set<string>>(() => {
    if (!idOf) return new Set<string>();
    const present = new Set(base().map(idOf));
    const next = new Set<string>();
    for (const id of selectedIds()) if (present.has(id)) next.add(id);
    return next;
  });

  const selectedItems = createMemo(() => {
    if (!idOf) return [];
    const ids = validSelectedIds();
    return base().filter((item) => ids.has(idOf(item)));
  });

  const allSelected = createMemo(() => {
    const rows = items();
    if (!idOf || rows.length === 0) return false;
    const ids = validSelectedIds();
    return rows.every((item) => ids.has(idOf(item)));
  });

  const toggleOne = (id: string) =>
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const toggleAll = () =>
    setSelectedIds((prev) => {
      if (!idOf) return prev;
      const rows = items();
      const next = new Set(prev);
      const allOn =
        rows.length > 0 && rows.every((item) => next.has(idOf(item)));
      for (const item of rows) {
        if (allOn) next.delete(idOf(item));
        else next.add(idOf(item));
      }
      return next;
    });

  return {
    query,
    setQuery,
    sortKey,
    setSort: setSortKey,
    dir,
    toggleDir: () => setDir((d) => (d === "asc" ? "desc" : "asc")),
    sortOptions,
    items,
    total: () => base().length,
    count: () => filtered().length,
    isFiltered: () => query().trim().length > 0,
    reset: () => {
      setQuery("");
      setSelectedIds(new Set<string>());
    },
    selectable,
    selectedIds: validSelectedIds,
    selectedCount: () => validSelectedIds().size,
    isSelected: (id) => validSelectedIds().has(id),
    toggleOne,
    toggleAll,
    allSelected,
    selectedItems,
    clearSelection: () => setSelectedIds(new Set<string>()),
  };
}
