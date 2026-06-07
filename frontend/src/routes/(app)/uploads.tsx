import { RequirePrivilege } from "~/lib/guards";
import { UploadsScreen } from "~/features/uploads";

export default function UploadsRoute() {
  return (
    <RequirePrivilege privilege="uploads">
      <UploadsScreen />
    </RequirePrivilege>
  );
}
