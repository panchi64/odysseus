import { RequirePrivilege } from "~/lib/guards";
import { RagConfigScreen } from "~/features/rag";

export default function RagRoute() {
  return (
    <RequirePrivilege privilege="rag">
      <RagConfigScreen />
    </RequirePrivilege>
  );
}
