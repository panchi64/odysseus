import { Navigate } from "@solidjs/router";

/** /settings has no content of its own — the first section is the front door. */
export default function SettingsIndexRoute() {
  return <Navigate href="/settings/appearance" />;
}
