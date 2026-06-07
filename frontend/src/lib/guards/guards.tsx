import { Show, type JSX } from "solid-js";
import { ForbiddenView } from "~/ui";
import { useSession } from "../stores/session";
import type { Privilege } from "../types";

/**
 * Route guards. They read the session store (a stub in Phase 1) and render a
 * visible denial (ForbiddenView) rather than a blank page when a check fails —
 * the security model requires denials to be explicit.
 *
 * Wrap a screen at its route file:
 *   <RequireAdmin><UserManagementScreen /></RequireAdmin>
 *
 * Phase 2 only changes the session store internals; these stay as-is.
 */

export function RequireAuth(props: { children: JSX.Element }): JSX.Element {
  const session = useSession();
  return (
    <Show
      when={session.isAuthenticated}
      fallback={
        <ForbiddenView
          reason="You must be signed in to view this area."
          code="AUTH-REQUIRED"
        />
      }
    >
      {props.children}
    </Show>
  );
}

export function RequireAdmin(props: { children: JSX.Element }): JSX.Element {
  const session = useSession();
  return (
    <Show
      when={session.isAdmin}
      fallback={
        <ForbiddenView
          reason="Administrator privilege is required for this area."
          code="PRIV-ADMIN"
        />
      }
    >
      {props.children}
    </Show>
  );
}

export function RequirePrivilege(props: {
  privilege: Privilege;
  children: JSX.Element;
}): JSX.Element {
  const session = useSession();
  return (
    <Show
      when={session.hasPrivilege(props.privilege)}
      fallback={
        <ForbiddenView
          reason="You do not have the privilege required for this feature."
          code={`PRIV-${props.privilege.toUpperCase()}`}
        />
      }
    >
      {props.children}
    </Show>
  );
}
