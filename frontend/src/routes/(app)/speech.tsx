import { RequireAdmin } from "~/lib/guards";
import { SpeechScreen } from "~/features/speech";

export default function SpeechRoute() {
  return (
    <RequireAdmin>
      <SpeechScreen />
    </RequireAdmin>
  );
}
