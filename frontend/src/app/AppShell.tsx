import { createEffect, onCleanup, Show, Suspense, type JSX } from "solid-js";
import { useLocation } from "@solidjs/router";
import {
  Button,
  Combobox,
  ErrorBoundary,
  NotConnectedOverlay,
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

/** The authenticated app chrome: sidebar rail + top status bar + the routed
 *  content region. Composed entirely from ~/ui. */
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
        {/* No rule under the top bar (§7). It is already a distinct region by
            position and by what it holds; a full-width hairline across every
            screen was chrome drawn where the eye had found the break. */}
        <header class="flex shrink-0 items-center justify-between gap-3 px-4 py-2">
          <div class="flex items-center gap-3">
            <StatusFlag status="live" dot>
              Link
            </StatusFlag>
            <Text variant="micro" tone="dim">
              Local
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
                placeholder="No model"
                searchPlaceholder="Search models…"
                emptyHint="No models — add an endpoint in settings"
                aria-label="Active model"
              />
              <Tooltip label="Refresh models" side="bottom">
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

        {/* The registration marks moved off the shell and onto `PageHeader`
            (§9). Framing the content region put two crosses just above the page
            and two in the bottom corners of the screen — bracketing the window
            rather than anything in it. They now frame the header row, which is
            an actual object. */}
        <div class="relative min-h-0 flex-1">
          {/* Scopes a suspending *or throwing* screen to the content region;
              without them the root blanks the shell too, taking the rail and
              the status bar with it. The path is the reset key, so navigating
              away from a broken screen clears the error. */}
          <main class="h-full overflow-y-auto p-6">
            <ErrorBoundary resetKey={() => location.pathname}>
              <Suspense>{props.children}</Suspense>
            </ErrorBoundary>
          </main>
          <Show when={!connected()}>
            <NotConnectedOverlay />
          </Show>
        </div>
      </div>
    </div>
  );
}
