import { RequirePrivilege } from "~/lib/guards";
import { EmailInboxScreen } from "~/features/email";

export default function EmailRoute() {
  return (
    <RequirePrivilege privilege="email">
      <EmailInboxScreen />
    </RequirePrivilege>
  );
}
