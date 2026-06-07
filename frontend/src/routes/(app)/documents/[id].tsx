import { useParams } from "@solidjs/router";
import { RequirePrivilege } from "~/lib/guards";
import { DocumentEditorScreen } from "~/features/documents";

export default function DocumentEditorRoute() {
  const params = useParams<{ id: string }>();
  return (
    <RequirePrivilege privilege="documents">
      <DocumentEditorScreen id={params.id} />
    </RequirePrivilege>
  );
}
