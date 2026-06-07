import { RequireAdmin } from "~/lib/guards";
import { IntegrationsScreen } from "~/features/integrations";

export default function IntegrationsRoute() {
  return (
    <RequireAdmin>
      <IntegrationsScreen />
    </RequireAdmin>
  );
}
