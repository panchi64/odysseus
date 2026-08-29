import { Navigate } from "@solidjs/router";

/**
 * `/login` is no longer a surface — the auth gate renders the unlock screen in
 * place, wherever the operator already is (see `~/lib/guards`). The path stays
 * because bookmarks and old toasts point at it: send it home, where the gate
 * shows the same screen against a tree that reads no resources, so this redirect
 * commits immediately.
 */
export default function LoginRoute() {
  return <Navigate href="/" />;
}
