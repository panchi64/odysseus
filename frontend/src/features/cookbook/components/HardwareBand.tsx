import { Show, Suspense, type JSX } from "solid-js";
import { InstrumentBand, LoadingText } from "~/ui";
import { useHardware } from "../data";

export function HardwareBand(): JSX.Element {
  const hardware = useHardware();
  return (
    <Suspense fallback={<LoadingText label="READING HARDWARE" />}>
      <Show when={hardware()}>
        {(hw) => (
          <InstrumentBand
            items={[
              { label: "CHIP", value: hw().chip },
              { label: "RAM", value: hw().ram },
              { label: "VRAM", value: hw().vram },
              { label: "CORES", value: hw().cores },
              { label: "BACKEND", value: hw().backend },
              ...(hw().runtimes.length
                ? hw().runtimes.map((r) => ({
                    label: r.name.toUpperCase(),
                    value: r.version ?? "—",
                  }))
                : [
                    {
                      label: "RUNTIME",
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
