import {
  createEffect,
  createMemo,
  createSignal,
  For,
  onMount,
  Show,
  type JSX,
} from "solid-js";
import { useNavigate } from "@solidjs/router";
import { Input, ListGroupHeader, Text } from "~/ui";
import {
  paletteDirectory,
  paletteSections,
  searchPalette,
  type PaletteHit,
} from "~/app/nav";
import { useSettingsIndex } from "~/app/nav/settings-index";
import { NavRow } from "./NavRow";
import { SettingRow } from "./SettingRow";
import { useSettingActions } from "./useSettingActions";

const LIST_ID = "nav-palette-results";
const rowId = (index: number): string => `nav-palette-row-${index}`;

export interface PaletteBodyProps {
  onClose: () => void;
}

/**
 * The palette's contents, mounted only while the overlay is open (`Modal`
 * renders its children behind a `Show`). That is deliberate on two counts: the
 * query and cursor reset by being born again rather than by an effect, and the
 * settings index's resources are created on open and torn down on close — so an
 * operator who never opens the palette never pays for the reads behind it.
 *
 * Results span two kinds. A **page** navigates and closes, as it always has. A
 * **setting** is actioned in place: the row stays put, its value updates, and the
 * overlay stays open, so several settings can be changed in one visit.
 */
export function PaletteBody(props: PaletteBodyProps): JSX.Element {
  const navigate = useNavigate();
  const settings = useSettingsIndex();
  const [query, setQuery] = createSignal("");
  const [cursor, setCursor] = createSignal(0);
  const actions = useSettingActions();
  let field: HTMLInputElement | undefined;

  // With no query the palette lists everything — an empty overlay would make
  // opening it a wasted keystroke, and the full list doubles as a directory.
  // Now that it holds two kinds of thing, that directory is also what teaches
  // the settings are reachable from here at all.
  const hits = createMemo<PaletteHit[]>(() =>
    query().trim()
      ? searchPalette(query(), { settings: settings() })
      : paletteDirectory({ settings: settings() }),
  );
  const sections = createMemo(() => paletteSections(hits()));

  // `onMount`, not a microtask: the field is only focusable once the overlay is
  // actually in the document, and mount is the point Solid guarantees that.
  onMount(() => field?.focus());

  // Keep the cursor on a row that still exists as the query narrows.
  createEffect(() => {
    const max = hits().length - 1;
    if (cursor() > max) setCursor(max < 0 ? 0 : max);
  });

  /** Close any open inline field and put focus back where the keys are read. */
  const stopEditing = (): void => {
    actions.cancel();
    field?.focus();
  };

  /** A page navigates and closes, as it always has. A setting is handed to the
   *  action hook and the overlay stays open — that is the whole point: several
   *  settings can be changed in one visit. */
  const activate = (hit: PaletteHit): void => {
    if (hit.kind === "nav") {
      props.onClose();
      navigate(hit.nav.item.href);
      return;
    }
    actions.activate(hit.setting);
  };

  const move = (delta: number): void => {
    // Leaving the row abandons its half-typed value: the field is an inline
    // affordance on the cursor, not a form that follows you down the list.
    if (actions.editing()) stopEditing();
    setCursor((i) => Math.min(Math.max(i + delta, 0), hits().length - 1));
  };

  /* The handler sits on the container, not on the search field, so it also
     catches keys typed into the inline number field — that field must not
     swallow Escape or the arrows the list navigates with. */
  const onKeyDown = (e: KeyboardEvent): void => {
    const hit = hits()[cursor()];
    if (e.key === "ArrowDown") {
      e.preventDefault();
      move(1);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      move(-1);
    } else if (e.key === "Enter") {
      e.preventDefault();
      const open = actions.editing();
      if (open && hit?.kind === "setting" && hit.setting.id === open) {
        actions.commit(hit.setting);
        field?.focus();
      } else if (hit) activate(hit);
    } else if (e.key === "Escape") {
      e.preventDefault();
      // Escape unwinds one layer at a time: the open field first, the overlay
      // only once nothing is being edited.
      if (actions.editing()) stopEditing();
      else props.onClose();
    } else if (e.key === " " && !actions.editing() && query() === "") {
      // Space activates only on an empty query. A leading space is a keystroke
      // the search would trim away anyway, so nothing is lost — while a query
      // with any text in it keeps Space as the space bar, where it belongs.
      if (hit) {
        e.preventDefault();
        activate(hit);
      }
    }
  };

  return (
    <div onKeyDown={onKeyDown}>
      <div class="p-2">
        <Input
          ref={field}
          value={query()}
          onInput={(e) => {
            setQuery(e.currentTarget.value);
            setCursor(0);
            // Typing re-sorts the list under the cursor, so whatever field was
            // open belongs to a row that may no longer be there.
            actions.cancel();
          }}
          leading="search"
          placeholder="Go to or change…"
          aria-label="Search pages and settings"
          role="combobox"
          aria-expanded={hits().length > 0}
          aria-controls={LIST_ID}
          aria-autocomplete="list"
          aria-activedescendant={
            hits().length > 0 ? rowId(cursor()) : undefined
          }
        />
      </div>

      <div
        id={LIST_ID}
        role="listbox"
        aria-label="Pages and settings"
        class="max-h-96 overflow-y-auto"
      >
        <Show
          when={hits().length > 0}
          fallback={
            <div class="px-3 py-4">
              <Text variant="micro" tone="dim">
                No match
              </Text>
            </div>
          }
        >
          <For each={sections()}>
            {(section) => (
              <div>
                <ListGroupHeader label={section.label} />
                <For each={section.rows}>
                  {(row) => {
                    const hit = row.hit;
                    const pick = (): void => {
                      setCursor(row.index);
                      activate(hit);
                    };
                    // A plain branch, not a `<Show>`: a row's kind is fixed for
                    // the life of the row object, so there is nothing here to
                    // stay reactive to — the list itself is rebuilt when the
                    // results change.
                    return hit.kind === "setting" ? (
                      <SettingRow
                        entry={hit.setting}
                        id={rowId(row.index)}
                        selected={row.index === cursor()}
                        busy={actions.busy() === hit.setting.id}
                        editing={actions.editing() === hit.setting.id}
                        draft={actions.draft()}
                        onDraft={actions.setDraft}
                        fieldRef={actions.setField}
                        onActivate={pick}
                      />
                    ) : (
                      <NavRow
                        match={hit.nav}
                        id={rowId(row.index)}
                        selected={row.index === cursor()}
                        onActivate={pick}
                      />
                    );
                  }}
                </For>
              </div>
            )}
          </For>
        </Show>
      </div>

      <div class="px-3 py-1.5">
        <Text variant="micro" tone="dim">
          ↑↓ MOVE · ENTER OPEN / CHANGE · ESC CLOSE
        </Text>
      </div>
    </div>
  );
}
