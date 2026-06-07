import { RequireAdmin } from "~/lib/guards";
import { HealthScreen } from "~/features/health";

export default function HealthRoute() {
  return (
    <RequireAdmin>
      <HealthScreen />
    </RequireAdmin>
  );
}
