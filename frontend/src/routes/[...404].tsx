import { Button, RegistrationFrame, Text } from "~/ui";

export default function NotFound() {
  return (
    <div class="flex h-screen items-center justify-center bg-bg text-text">
      <RegistrationFrame
        class="flex w-full max-w-md flex-col items-center gap-3 p-8 text-center"
        assetId="ODY-ERR-404"
      >
        <Text variant="readout-lg" tone="alert">
          404
        </Text>
        <Text variant="label" tone="dim">
          NO SUCH ROUTE
        </Text>
        <Text variant="body" tone="dim">
          The requested surface does not exist or has been decommissioned.
        </Text>
        <Button variant="default" href="/" leading="arrow-right" class="mt-2">
          RETURN TO OVERVIEW
        </Button>
      </RegistrationFrame>
    </div>
  );
}
