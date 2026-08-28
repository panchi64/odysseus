import { Show, Suspense, type JSX } from "solid-js";
import { InstrumentBand, LoadingText } from "~/ui";
import { useHardware } from "../data";

export function HardwareBand(): JSX.Element {
  const hardware = useHardware();
  return (
    <Suspense fallback={<LoadingText label="Reading hardware" />}>
      <Show when={hardware()}>
        {(hw) => (
          <InstrumentBand
            items={[
              { label: "Chip", value: hw().chip },
              { label: "RAM", value: hw().ram },
              { label: "VRAM", value: hw().vram },
              { label: "Cores", value: hw().cores },
              { label: "Backend", value: hw().backend },
              ...(hw().runtimes.length
                ? hw().runtimes.map((r) => ({
                    label: r.name.toUpperCase(),
                    value: r.version ?? "—",
                  }))
                : [
                    {
                      label: "Runtime",
                      value: "none detected",
                      tone: "dim" as const,
                    },
                  ]),
            ]}
          />
        )}
      </Show>
    </Suspense>
  );
}
