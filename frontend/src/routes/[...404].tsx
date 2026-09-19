import { Button, DeepField, RegistrationFrame, Text } from "~/ui";

/** A path with no route. The surfaces that became settings sections used to
 *  forward through here into `?settings=…`; nothing is deployed anywhere that
 *  could be holding a link to one, so a dead path reads as dead.
 *
 *  **This screen carries §11.1's licensed moment**, and it is the clearest case the
 *  rule has: a 404 is a whole viewport with one small plate on it and nothing running,
 *  so there is nothing for the field to compete with or sit in front of. It is also
 *  the one screen the operator reaches by accident, which is the right place for the
 *  product to be quietly good-looking rather than merely correct. */
export default function NotFound() {
  return (
    <div class="relative flex h-screen items-center justify-center overflow-hidden bg-bg text-text">
      <DeepField />
      <RegistrationFrame
        // Above the field: an absolutely positioned sibling otherwise paints over
        // in-flow content in the same stacking context.
        class="relative flex w-full max-w-md flex-col items-center gap-3 p-8 text-center"
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
