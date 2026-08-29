import { Button, RegistrationFrame, Text } from "~/ui";

/** A path with no route. The surfaces that became settings sections used to
 *  forward through here into `?settings=…`; nothing is deployed anywhere that
 *  could be holding a link to one, so a dead path reads as dead. */
export default function NotFound() {
  return (
    <div class="flex h-screen items-center justify-center bg-bg text-text">
      <RegistrationFrame
        class="flex w-full max-w-md flex-col items-center gap-3 p-8 text-center"
        assetId="ODY-ERR-404"
      >
        {/* The hero readout is `text-bright`, not alert (§10.4, §5 rule 1): a
            screen at rest is grayscale, and a wrong address is not a fault —
            nothing is running, failing, or waiting on the operator here. */}
        <Text variant="readout-lg" tone="bright">
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
  );
}
