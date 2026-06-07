import { RequireAdmin } from "~/lib/guards";
import { UserManagementScreen } from "~/features/users";

export default function UsersRoute() {
  return (
    <RequireAdmin>
      <UserManagementScreen />
    </RequireAdmin>
  );
}
