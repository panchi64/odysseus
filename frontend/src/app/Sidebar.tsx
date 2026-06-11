import {
  For,
  Show,
  createEffect,
  createMemo,
  createSignal,
  type JSX,
} from "solid-js";
import { useLocation, useNavigate } from "@solidjs/router";
import { readLS, writeLS } from "~/lib/storage";
import { cx, Icon, Input, ListRow, Text, Tooltip } from "~/ui";
import {
  NAV,
  searchNav,
  type NavIndicator,
  type NavItem,
  type NavSection,
} from "./nav";

const COLLAPSE_STORAGE_KEY = "ody.sidebar.collapsed";

const indicatorBg: Record<NavIndicator, string> = {
  nominal: "bg-nominal",
  info: "bg-info",
  warn: "bg-warn",
  alert: "bg-alert",
};

/** Small semantic square marking ambient activity on an item (§4 — color
 *  carries meaning only). Square by default. */
function IndicatorSquare(props: { status: NavIndicator }): JSX.Element {
  return (
    <span
      class={cx("size-2 shrink-0", indicatorBg[props.status])}
      aria-label={`${props.status} activity`}
    />
  );
}

/** Right-aligned row meta: an ambient activity square, plus a dim OFFLINE tag for
 *  surfaces not yet wired to the backend so the missing set is scannable from the
 *  rail. Returns nothing when the row carries neither. */
function navMeta(item: NavItem): JSX.Element | undefined {
  const offline = !item.connected;
  if (!item.indicator && !offline) return undefined;
  return (
    <span class="flex items-center gap-2">
      <Show when={item.indicator}>
        {(ind) => <IndicatorSquare status={ind()} />}
      </Show>
      <Show when={offline}>
        <Text variant="micro" tone="dim">
          OFFLINE
        </Text>
      </Show>
    </span>
  );
}

function sectionIndicator(section: NavSection): NavIndicator | undefined {
  return section.items.find((i) => i.indicator)?.indicator;
}

function loadCollapsed(): Record<string, boolean> {
  try {
    const raw = readLS(COLLAPSE_STORAGE_KEY);
    return raw ? (JSON.parse(raw) as Record<string, boolean>) : {};
  } catch {
    return {};
  }
}

/** Primary navigation rail: a searchable overview of every capability, with
 *  rarely-touched sections collapsed so the resting view leads with the
 *  everyday. The active route is derived from the current location. */
export function Sidebar(): JSX.Element {
  const location = useLocation();
  const navigate = useNavigate();
  const isActive = (href: string) =>
    location.pathname === href || location.pathname.startsWith(`${href}/`);

  // Per-section collapse state: stored prefs over each section's default.
  const stored = loadCollapsed();
  const initial: Record<string, boolean> = {};
  for (const s of NAV)
    initial[s.title] = stored[s.title] ?? !!s.defaultCollapsed;
  const [collapsed, setCollapsed] = createSignal(initial);

  const persist = (next: Record<string, boolean>) => {
    setCollapsed(next);
    writeLS(COLLAPSE_STORAGE_KEY, JSON.stringify(next));
  };
  const toggleSection = (title: string) =>
    persist({ ...collapsed(), [title]: !collapsed()[title] });
  const expandSection = (title: string) =>
    persist({ ...collapsed(), [title]: false });

  // A section is shown collapsed unless the active route lives inside it — you
  // can always see where you are.
  const isCollapsed = (section: NavSection) =>
    !!collapsed()[section.title] &&
    !section.items.some((i) => isActive(i.href));

  // Search. The rail itself never reflows; matches surface in a dropdown, and a
  // lone match scrolls into view and flashes.
  const [query, setQuery] = createSignal("");
  const matches = createMemo(() => searchNav(query()));
  const showDropdown = () =>
    query().trim().length > 0 && matches().length !== 1;

  const rowRefs = new Map<string, HTMLElement>();
  let lastFlashed = "";

  const flashRow = (href: string) => {
    const el = rowRefs.get(href);
    if (!el) return;
    el.scrollIntoView({ block: "nearest" });
    el.classList.remove("ody-flash");
    void el.offsetWidth; // restart the animation if re-triggered
    el.classList.add("ody-flash");
    window.setTimeout(() => el.classList.remove("ody-flash"), 3000);
  };

  // When a query narrows to exactly one item, reveal and flash it.
  createEffect(() => {
    const m = matches();
    if (!query().trim() || m.length !== 1) {
      lastFlashed = "";
      return;
    }
    const { item, section } = m[0];
    if (item.href === lastFlashed) return;
    lastFlashed = item.href;
    expandSection(section.title);
    window.setTimeout(() => flashRow(item.href), 30);
  });

  const goTo = (href: string) => {
    setQuery("");
    navigate(href);
  };
  const onSearchKey = (e: KeyboardEvent) => {
    if (e.key === "Enter") {
      const m = matches();
      if (m.length) goTo(m[0].item.href);
    } else if (e.key === "Escape") {
      setQuery("");
    }
  };

  return (
    <nav class="flex min-h-full flex-col bg-surface">
      <div class="sticky top-0 z-30 bg-surface">
        <a
          href="/"
          class="flex flex-col gap-0.5 border-b border-line px-3 py-3 transition-colors hover:bg-raised"
        >
          <Text variant="readout" tone="bright" class="font-display">
            ODYSSEUS
          </Text>
          <Text variant="micro" tone="dim">
            ODY-WORKSPACE-02.1
          </Text>
        </a>

        <div class="relative border-b border-line p-2">
          <Icon
            name="search"
            size={14}
            class="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-dim"
          />
          <Input
            value={query()}
            onInput={(e) => setQuery(e.currentTarget.value)}
            onKeyDown={onSearchKey}
            placeholder="SEARCH"
            aria-label="Search navigation"
            class="pl-7"
          />

          <Show when={showDropdown()}>
            <div class="absolute inset-x-2 top-full z-40 max-h-80 overflow-y-auto border border-line bg-surface">
              <Show
                when={matches().length > 0}
                fallback={
                  <div class="px-3 py-2">
                    <Text variant="micro" tone="dim">
                      NO MATCH
                    </Text>
                  </div>
                }
              >
                <For each={matches()}>
                  {(m) => (
                    <button
                      type="button"
                      onClick={() => goTo(m.item.href)}
                      class="flex w-full items-center justify-between gap-2 border-b border-line px-3 py-2 text-left transition-colors last:border-0 hover:bg-raised"
                    >
                      <span class="flex min-w-0 items-center gap-2">
                        <Icon name={m.item.icon} class="text-dim" />
                        <Text variant="label" tone="default" class="truncate">
                          {m.item.label}
                        </Text>
                      </span>
                      <Text variant="micro" tone="dim">
                        {m.section.title}
                      </Text>
                    </button>
                  )}
                </For>
              </Show>
            </div>
          </Show>
        </div>
      </div>

      <div class="flex flex-col py-2">
        <For each={NAV}>
          {(section) => (
            <div class="mb-2">
              <button
                type="button"
                onClick={() => toggleSection(section.title)}
                aria-expanded={!isCollapsed(section)}
                class="flex w-full items-center justify-between px-3 py-1 text-left transition-colors hover:bg-raised"
              >
                <Text variant="micro" tone="dim">
                  {section.title}
                </Text>
                <span class="flex items-center gap-1.5">
                  <Show
                    when={isCollapsed(section) && sectionIndicator(section)}
                  >
                    {(ind) => <IndicatorSquare status={ind()} />}
                  </Show>
                  <Icon
                    name={
                      isCollapsed(section) ? "chevron-right" : "chevron-down"
                    }
                    size={12}
                    class="text-dim"
                  />
                </span>
              </button>
              <Show when={!isCollapsed(section)}>
                <For each={section.items}>
                  {(item) => (
                    <Tooltip
                      float
                      delay={1000}
                      side="right"
                      label={item.description}
                      class="block w-full"
                    >
                      <div ref={(el) => rowRefs.set(item.href, el)}>
                        <ListRow
                          label={item.label}
                          leading={item.icon}
                          href={item.href}
                          selected={isActive(item.href)}
                          flush
                          right={navMeta(item)}
                        />
                      </div>
                    </Tooltip>
                  )}
                </For>
              </Show>
            </div>
          )}
        </For>
      </div>
    </nav>
  );
}
