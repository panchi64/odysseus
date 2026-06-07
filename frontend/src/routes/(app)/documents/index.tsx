import { RequirePrivilege } from "~/lib/guards";
import { DocumentsLibraryScreen } from "~/features/documents";

export default function DocumentsRoute() {
  return (
    <RequirePrivilege privilege="documents">
      <DocumentsLibraryScreen />
    </RequirePrivilege>
  );
}
