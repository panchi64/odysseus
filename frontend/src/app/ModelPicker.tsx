import type { JSX } from "solid-js";
import { Combobox } from "~/ui";
import {
  effectiveValue,
  modelPickerGroups,
  refreshEndpoints,
  refreshModels,
  selectModelByValue,
} from "~/lib/stores/models";

/** Which model the next turn runs on.
 *
 *  **This is the backend `main` role binding, not a per-surface preference.** The
 *  store writes `PUT /models/roles/main`, which is the same fact every server-initiated
 *  consumer resolves — titling, research, scheduled tasks. Changing it here changes it
 *  for all of them, deliberately: there is one operator and one active model, and a
 *  device-local override would be a second answer to a question the backend already
 *  owns. Every instance of this component is therefore a view of one value and they
 *  cannot disagree.
 *
 *  It lives **in the composer's action row** rather than the top bar. The model is not
 *  a property of the application, it is a property of the message about to be sent, and
 *  in the top bar it was a persistent global control on every screen — including the
 *  many with nothing to send. Next to SEND it is in the operator's eye-line at the one
 *  moment the choice matters, and it costs nothing on the screens that don't have one.
 *
 *  `bare` because the action row already sits on the composer's own surface: a filled
 *  control there is the box-in-a-box the system drops (§7).
 *
 *  **The list refreshes itself when it opens**, rather than sitting behind a refresh
 *  button. Opening the menu is already the operator saying "show me what I can pick",
 *  and a model that appeared since the app loaded — a local engine they just started —
 *  is exactly the one they opened it to find. The old button asked them to say it
 *  twice, and to somehow know the list in front of them was stale. */
export function ModelPicker(props: { class?: string }): JSX.Element {
  return (
    <Combobox
      bare
      groups={modelPickerGroups()}
      value={effectiveValue()}
      onChange={selectModelByValue}
      onOpen={() => {
        // Both: the catalog may have gained an endpoint (added in Settings in another
        // tab), and the endpoints it already had may serve models they didn't before.
        // Neither implies the other, and only the second needs asking the provider.
        refreshEndpoints();
        refreshModels();
      }}
      align="right"
      placeholder="No model"
      searchPlaceholder="Search models…"
      emptyHint="No models — add an endpoint in settings"
      aria-label="Active model"
      class={props.class}
    />
  );
}
