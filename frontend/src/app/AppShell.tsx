import { createEffect, onCleanup, Show, Suspense, type JSX } from "solid-js";
import { useLocation } from "@solidjs/router";
import {
  Button,
  Combobox,
  NotConnectedOverlay,
  RegistrationFrame,
  ResizeHandle,
  StatusFlag,
  ThemeToggle,
  Text,
  Tooltip,
  toast,
} from "~/ui";
import {
  effectiveValue,
  modelPickerGroups,
  refreshEndpoints,
  selectModelByValue,
} from "~/lib/stores/models";
import { useSession } from "~/lib/stores/session";
import {
  startNotifications,
  stopNotifications,
} from "~/lib/stores/notifications";
import { NotificationBell } from "./NotificationBell";
import { Sidebar, useSidebarWidth } from "./sidebar";
import { isConnectedRoute } from "./nav";

/** The authenticated app chrome: sidebar rail + top status bar + framed main
 *  content. Composed entirely from ~/ui. */
export function AppShell(props: { children: JSX.Element }): JSX.Element {
  const location = useLocation();
  const connected = () => isConnectedRoute(location.pathname);
  const session = useSession();
  const rail = useSidebarWidth();

  // The notification feed is app-lifetime, not per-route: subscribe once the
  // workspace is authenticated (the same signal the auth guard gates on) and
  // tear down on logout/lock so no state survives to the next session.
  createEffect(() => {
    if (session.isAuthenticated) startNotifications();
    else stopNotifications();
  });
  onCleanup(stopNotifications);
  return (
    <div class="flex h-screen overflow-hidden bg-bg text-text">
      {/* The rail is drag-sized; the handle draws the hairline that used to be
          the aside's right border. */}
      <aside
        class="shrink-0 overflow-y-auto"
        style={{ width: `${rail.width()}px` }}
      >
        <Sidebar />
      </aside>
      <ResizeHandle
        aria-label="Resize navigation rail"
        onResize={rail.resize}
        onResizeEnd={rail.persist}
      />

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
            <div class="flex items-center gap-1">
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
              <Tooltip label="REFRESH MODELS" side="bottom">
                <Button
                  variant="ghost"
                  size="sm"
                  leading="refresh"
                  aria-label="Refresh model list"
                  onClick={() => {
                    refreshEndpoints();
                    toast.info("Refreshing model list…");
                  }}
                />
              </Tooltip>
            </div>
            <NotificationBell />
            <ThemeToggle />
          </div>
        </header>

        <RegistrationFrame class="min-h-0 flex-1">
          <div class="relative h-full">
            {/* Scopes a suspending screen to the content region; without it the
                root boundary blanks the shell too, dropping the rail's scroll. */}
            <main class="h-full overflow-y-auto p-6">
              <Suspense>{props.children}</Suspense>
            </main>
            <Show when={!connected()}>
              <NotConnectedOverlay />
            </Show>
          </div>
        </RegistrationFrame>
      </div>
    </div>
  );
}
