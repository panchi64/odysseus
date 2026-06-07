import { RequireAdmin } from "~/lib/guards";
import { VaultScreen } from "~/features/vault";

export default function VaultRoute() {
  return (
    <RequireAdmin>
      <VaultScreen />
    </RequireAdmin>
  );
}
