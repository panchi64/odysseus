import { RequirePrivilege } from "~/lib/guards";
import { SkillsDirectoryScreen } from "~/features/skills";

export default function SkillsRoute() {
  return (
    <RequirePrivilege privilege="skills">
      <SkillsDirectoryScreen />
    </RequirePrivilege>
  );
}
