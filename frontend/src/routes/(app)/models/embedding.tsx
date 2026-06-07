import { RequireAdmin } from "~/lib/guards";
import { EmbeddingScreen } from "~/features/embedding";

export default function EmbeddingRoute() {
  return (
    <RequireAdmin>
      <EmbeddingScreen />
    </RequireAdmin>
  );
}
