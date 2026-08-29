/** The query key the dialog's state rides on. Declared here rather than beside
 *  the hook so this module imports nothing: `nav/index.ts` reads it to keep a
 *  redirecting path marked connected, and dragging the router (and the dialog
 *  behind it) into the nav derivations — and into their unit tests — for one
 *  string would be a poor trade. */
export const SETTINGS_PARAM = "settings";

/**
 * Every path that used to be a settings page, and the dialog category that
 * absorbed it.
 *
 * These are not dead links to be cleaned up later. `/settings/models` is what a
 * Cookbook toast still points at, `/settings/appearance` is what the rail's
 * Settings pin pointed at for the whole life of the two-tier rail, and any of
 * them may sit in a bookmark. Forwarding them costs one map; letting them 404
 * would make the redesign look like breakage.
 */
const LEGACY_SETTINGS_PATHS: Record<string, string> = {
  "/settings": "general",
  "/settings/appearance": "general",
  "/settings/chat": "general",
  "/settings/offline": "general",
  "/settings/tools": "agent",
  "/settings/models": "models",
  "/skills": "agent",
  "/projects": "agent",
  "/memory": "memory",
  "/vault": "security",
  "/admin/tokens": "security",
  "/admin/access-tokens": "security",
  "/integrations": "system",
  "/backup": "system",
  "/health": "system",
};

/**
 * The `?settings=` URL a retired page forwards to, or undefined when the path
 * was never one — in which case it really is a 404 and should read as one.
 *
 * The dialog opens over the **home route**, not over wherever the operator was:
 * this is a cold entry from a bookmark or a link, so there is no "where they
 * were" to preserve, and home is the one route that is always a sensible thing
 * to find behind it.
 */
export function legacySettingsHref(pathname: string): string | undefined {
  // Trailing slashes and a deep path under a retired page (`/skills/abc`) both
  // resolve to the page that owned them, since the surface itself is gone.
  const path = pathname.replace(/\/+$/, "") || "/";
  const category =
    LEGACY_SETTINGS_PATHS[path] ??
    Object.entries(LEGACY_SETTINGS_PATHS).find(
      ([p]) => p !== "/" && path.startsWith(`${p}/`),
    )?.[1];
  return category ? `/?${SETTINGS_PARAM}=${category}` : undefined;
}
