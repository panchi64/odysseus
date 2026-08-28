import { useParams } from "@solidjs/router";
import { DocumentEditorScreen } from "~/features/documents";

export default function DocumentEditorRoute() {
  const params = useParams<{ id: string }>();
  return <DocumentEditorScreen id={params.id} />;
}
