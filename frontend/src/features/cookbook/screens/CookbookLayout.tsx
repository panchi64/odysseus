import { Show, type JSX } from "solid-js";
import { PageHeader, Stack, StatusFlag } from "~/ui";
import { useHardware } from "../data";

/** Chrome shared by every cookbook page. The rail lists the pages, so this holds
 *  no tab state. */
export function CookbookLayout(props: { children: JSX.Element }): JSX.Element {
  const hardware = useHardware();

  return (
    <Stack gap={6}>
      <PageHeader
        title="Model cookbook"
        subtitle="Local and remote model serving, hardware fit, embedding configuration, and side-by-side comparison."
        assetId="SYS-MDL-03.1"
        actions={
          <Show when={hardware.latest}>
            {(hw) => (
              <StatusFlag status="nominal" dot>
                {hw().backend}
              </StatusFlag>
            )}
          </Show>
        }
      />
      {props.children}
    </Stack>
  );
}
