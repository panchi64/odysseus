import { type JSX } from "solid-js";
import { RegistrationFrame, StatusFlag, ThemeToggle, Text } from "~/ui";
import { useSession } from "~/lib/stores/session";
import { Sidebar } from "./Sidebar";

/** The authenticated app chrome: sidebar rail + top status bar + framed main
 *  content. Composed entirely from ~/ui. */
export function AppShell(props: { children: JSX.Element }): JSX.Element {
  const session = useSession();
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
              UPLINK 12MS · LOCAL
            </Text>
          </div>
          <div class="flex items-center gap-3">
            <Text variant="label" tone="dim">
              {session.user?.name ?? "GUEST"}
            </Text>
            <ThemeToggle />
          </div>
        </header>

        <RegistrationFrame class="min-h-0 flex-1">
          <main class="h-full overflow-y-auto p-6">{props.children}</main>
        </RegistrationFrame>
      </div>
    </div>
  );
}
