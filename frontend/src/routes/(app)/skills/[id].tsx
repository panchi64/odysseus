import { useParams } from "@solidjs/router";
import { RequirePrivilege } from "~/lib/guards";
import { SkillEditorScreen } from "~/features/skills";

export default function SkillEditorRoute() {
  const params = useParams<{ id: string }>();
  return (
    <RequirePrivilege privilege="skills">
      <SkillEditorScreen id={params.id} />
    </RequirePrivilege>
  );
}
