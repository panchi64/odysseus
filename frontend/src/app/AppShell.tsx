import { Show, type JSX } from "solid-js";
import { useLocation } from "@solidjs/router";
import {
  Button,
  Combobox,
  NotConnectedOverlay,
  RegistrationFrame,
  StatusFlag,
  ThemeToggle,
  Text,
} from "~/ui";
import { useSession } from "~/lib/stores/session";
import {
  effectiveValue,
  modelPickerGroups,
  selectModelByValue,
} from "~/lib/stores/models";
import { Sidebar } from "./Sidebar";
import { isConnectedRoute } from "./nav";

/** The authenticated app chrome: sidebar rail + top status bar + framed main
 *  content. Composed entirely from ~/ui. */
export function AppShell(props: { children: JSX.Element }): JSX.Element {
  const session = useSession();
  const location = useLocation();
  const connected = () => isConnectedRoute(location.pathname);
  return (
    <div class="flex h-screen overflow-hidden bg-bg text-text">
      <aside class="w-52 shrink-0 overflow-y-auto border-r border-line">
        <Sidebar />
      </aside>

      <div class="flex min-w-0 flex-1 flex-col">
        <header class="flex shrink-0 items-center justify-between gap-3 border-b border-line px-4 py-2">
          <div class="flex items-center gap-3">
            <StatusFlag status="live" dot>
              LINK
            </StatusFlag>
            <Text variant="micro" tone="dim">
              LOCAL
            </Text>
          </div>
          <div class="flex items-center gap-3">
            <Combobox
              groups={modelPickerGroups()}
              value={effectiveValue()}
              onChange={selectModelByValue}
              leading="cpu"
              align="right"
              placeholder="NO MODEL"
              searchPlaceholder="Search models…"
              emptyHint="NO MODELS — ADD AN ENDPOINT IN SETTINGS"
              aria-label="Active model"
            />
            <Text variant="label" tone="dim">
              OPERATOR
            </Text>
            <Button
              variant="ghost"
              size="sm"
              leading="lock"
              onClick={() => void session.lock()}
            >
              LOCK
            </Button>
            <ThemeToggle />
          </div>
        </header>

        <RegistrationFrame class="min-h-0 flex-1">
          <div class="relative h-full">
            <main class="h-full overflow-y-auto p-6">{props.children}</main>
            <Show when={!connected()}>
              <NotConnectedOverlay />
            </Show>
          </div>
        </RegistrationFrame>
      </div>
    </div>
  );
}
