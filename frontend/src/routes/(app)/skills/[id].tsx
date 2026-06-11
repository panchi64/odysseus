import { useParams } from "@solidjs/router";
import { SkillEditorScreen } from "~/features/skills";

export default function SkillEditorRoute() {
  const params = useParams<{ id: string }>();
  return <SkillEditorScreen id={params.id} />;
}
