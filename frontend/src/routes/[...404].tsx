import { Show } from "solid-js";
import { Navigate, useLocation } from "@solidjs/router";
import { Button, RegistrationFrame, Text } from "~/ui";
import { legacySettingsHref } from "~/app/settings-dialog";

/** Also the front door for every surface that became a settings category. A
 *  retired page forwards into the dialog; anything else really is a 404. */
export default function NotFound() {
  const location = useLocation();
  const legacy = () => legacySettingsHref(location.pathname);
  return (
    <Show when={!legacy()} fallback={<Navigate href={legacy()!} />}>
      <div class="flex h-screen items-center justify-center bg-bg text-text">
        <RegistrationFrame
          class="flex w-full max-w-md flex-col items-center gap-3 p-8 text-center"
          assetId="ODY-ERR-404"
        >
          <Text variant="readout-lg" tone="alert">
            404
          </Text>
          <Text variant="label" tone="dim">
            No such route
          </Text>
          <Text variant="body" tone="dim">
            The requested surface does not exist or has been decommissioned.
          </Text>
          <Button variant="default" href="/" leading="arrow-right" class="mt-2">
            Return to overview
          </Button>
        </RegistrationFrame>
      </div>
    </Show>
  );
}
