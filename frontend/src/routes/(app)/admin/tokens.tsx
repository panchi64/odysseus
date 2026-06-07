import { RequireAdmin } from "~/lib/guards";
import { ApiTokensScreen } from "~/features/tokens";

export default function TokensRoute() {
  return (
    <RequireAdmin>
      <ApiTokensScreen />
    </RequireAdmin>
  );
}
