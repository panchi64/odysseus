import type { RouteSectionProps } from "@solidjs/router";
import { RequireAuth } from "~/lib/guards";
import { AppShell } from "~/app/AppShell";

/** Layout for all authenticated app surfaces: auth gate + shell chrome. */
export default function AppGroupLayout(props: RouteSectionProps) {
  return (
    <RequireAuth>
      <AppShell>{props.children}</AppShell>
    </RequireAuth>
  );
}
