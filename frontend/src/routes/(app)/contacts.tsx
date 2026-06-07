import { RequirePrivilege } from "~/lib/guards";
import { ContactsScreen } from "~/features/contacts";

export default function ContactsRoute() {
  return (
    <RequirePrivilege privilege="contacts">
      <ContactsScreen />
    </RequirePrivilege>
  );
}
