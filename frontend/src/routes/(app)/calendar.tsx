import { RequirePrivilege } from "~/lib/guards";
import { CalendarScreen } from "~/features/calendar";

export default function CalendarRoute() {
  return (
    <RequirePrivilege privilege="calendar">
      <CalendarScreen />
    </RequirePrivilege>
  );
}
