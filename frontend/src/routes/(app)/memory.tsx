import { RequirePrivilege } from "~/lib/guards";
import { MemoryTimelineScreen } from "~/features/memory";

export default function MemoryRoute() {
  return (
    <RequirePrivilege privilege="memory">
      <MemoryTimelineScreen />
    </RequirePrivilege>
  );
}
