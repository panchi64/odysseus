import { RequireAdmin } from "~/lib/guards";
import { ShellScreen } from "~/features/shell";

export default function ShellRoute() {
  return (
    <RequireAdmin>
      <ShellScreen />
    </RequireAdmin>
  );
}
