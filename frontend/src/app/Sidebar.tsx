import { For, type JSX } from "solid-js";
import { useLocation } from "@solidjs/router";
import { ListRow, StatusFlag, Text } from "~/ui";
import { NAV } from "./nav";

/** Primary navigation rail. Renders the NAV model; the active route is derived
 *  from the current location. */
export function Sidebar(): JSX.Element {
  const location = useLocation();
  const isActive = (href: string) =>
    location.pathname === href || location.pathname.startsWith(`${href}/`);

  return (
    <nav class="flex min-h-full flex-col bg-surface">
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

      <div class="flex flex-col py-2">
        <For each={NAV}>
          {(section) => (
            <div class="mb-2">
              <div class="px-3 py-1">
                <Text variant="micro" tone="dim">
                  {section.title}
                </Text>
              </div>
              <For each={section.items}>
                {(item) => (
                  <ListRow
                    label={item.label}
                    leading={item.icon}
                    href={item.href}
                    selected={isActive(item.href)}
                    flush
                    right={
                      item.tier === "admin" ? (
                        <StatusFlag status="idle">ADM</StatusFlag>
                      ) : undefined
                    }
                  />
                )}
              </For>
            </div>
          )}
        </For>
      </div>
    </nav>
  );
}
