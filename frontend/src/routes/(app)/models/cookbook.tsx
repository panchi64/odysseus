import { RequireAdmin } from "~/lib/guards";
import { CookbookScreen } from "~/features/cookbook";

export default function CookbookRoute() {
  return (
    <RequireAdmin>
      <CookbookScreen />
    </RequireAdmin>
  );
}
