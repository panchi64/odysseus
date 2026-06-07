import { RequireAdmin } from "~/lib/guards";
import { McpScreen } from "~/features/mcp";

export default function McpRoute() {
  return (
    <RequireAdmin>
      <McpScreen />
    </RequireAdmin>
  );
}
