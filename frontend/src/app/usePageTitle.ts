import { createEffect } from "solid-js";
import { useLocation } from "@solidjs/router";
import { NAV } from "./nav";

const BRAND = "ODYSSEUS";

/** Routes that aren't in the sidebar nav. */
const STATIC_TITLES: Record<string, string> = {
  "/": "Overview",
  "/login": "Sign In",
  "/signup": "Sign Up",
};

/** href -> label, derived from the single nav model. */
const NAV_TITLES: Record<string, string> = Object.fromEntries(
  NAV.flatMap((section) => section.items).map((item) => [
    item.href,
    item.label,
  ]),
);

function titleFor(pathname: string): string {
  if (STATIC_TITLES[pathname]) return STATIC_TITLES[pathname];
  if (NAV_TITLES[pathname]) return NAV_TITLES[pathname];
  // Longest-prefix match handles detail/nested routes (e.g. /research/r-007).
  const match = Object.keys(NAV_TITLES)
    .filter((href) => pathname === href || pathname.startsWith(`${href}/`))
    .sort((a, b) => b.length - a.length)[0];
  return match ? NAV_TITLES[match] : "Not Found";
}

/**
 * Keeps `document.title` in sync with the current route — centrally, from the
 * nav model — so no screen has to set its own title. Call once at the app root.
 */
export function usePageTitle(): void {
  const location = useLocation();
  createEffect(() => {
    document.title = `${titleFor(location.pathname)} · ${BRAND}`;
  });
}
