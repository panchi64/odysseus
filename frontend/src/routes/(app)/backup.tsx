import { RequireAdmin } from "~/lib/guards";
import { BackupScreen } from "~/features/backup";

export default function BackupRoute() {
  return (
    <RequireAdmin>
      <BackupScreen />
    </RequireAdmin>
  );
}
