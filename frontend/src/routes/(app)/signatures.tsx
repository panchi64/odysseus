import { RequirePrivilege } from "~/lib/guards";
import { SignaturesScreen } from "~/features/signatures";

export default function SignaturesRoute() {
  return (
    <RequirePrivilege privilege="signatures">
      <SignaturesScreen />
    </RequirePrivilege>
  );
}
