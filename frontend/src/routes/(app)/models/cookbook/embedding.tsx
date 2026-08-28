import { Stack } from "~/ui";
import {
  CookbookLayout,
  EmbeddingPanel,
  EmbeddingServePanel,
} from "~/features/cookbook";

export default function EmbeddingRoute() {
  return (
    <CookbookLayout>
      <Stack gap={6}>
        <EmbeddingServePanel />
        <EmbeddingPanel />
      </Stack>
    </CookbookLayout>
  );
}
