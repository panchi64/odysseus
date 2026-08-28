import { Show, type JSX } from "solid-js";
import { Navigate } from "@solidjs/router";
import { LoadingText, Stack, Text } from "~/ui";
import { useSession } from "../stores/session";

/**
 * The auth gate. Single operator, so there is one question: is the workspace
 * unlocked? While the boot probe runs we hold on a splash; an un-unlocked
 * workspace is redirected to its entry surface (`/signup` first-run, else
 * `/login`) rather than shown a blank or forbidden page.
 *
 * Phase 2 only changed the session store internals; this reads `useSession()`.
 */
export function RequireAuth(props: { children: JSX.Element }): JSX.Element {
  const session = useSession();
  return (
    <Show
      when={session.status !== "loading"}
      fallback={
        <div class="flex h-screen items-center justify-center bg-bg">
          <Stack gap={1} class="items-center">
            <Text variant="display" tone="bright" class="font-display">
              ODYSSEUS
            </Text>
            <LoadingText label="ESTABLISHING LINK…" />
          </Stack>
        </div>
      }
    >
      <Show
        when={session.isAuthenticated}
        fallback={
          <Navigate
            href={session.status === "uninitialized" ? "/signup" : "/login"}
          />
        }
      >
        {props.children}
      </Show>
    </Show>
  );
}
