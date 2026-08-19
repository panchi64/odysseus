import {
  CookbookLayout,
  HardwareBand,
  LocalModelsPanel,
} from "~/features/cookbook";

export default function LocalModelsRoute() {
  return (
    <CookbookLayout>
      <HardwareBand />
      <LocalModelsPanel />
    </CookbookLayout>
  );
}
