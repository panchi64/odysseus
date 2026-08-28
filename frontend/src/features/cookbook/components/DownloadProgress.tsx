import { Show, type JSX } from "solid-js";
import { ProgressBar, Text } from "~/ui";
import { bytes } from "~/lib/format";
import type { DownloadProgress as DownloadProgressData } from "../model";

/** A labeled download bar for a managed model's live progress. Determinate when
 *  the backend knows the total (`fraction`/`totalBytes` present); otherwise an
 *  indeterminate band. The percent is derived from `fraction` (0..1), never a
 *  `percent` field — see `serving.ts`. Presentation-only: it renders whatever the
 *  poll last reported. */
export function DownloadProgress(props: {
  progress: DownloadProgressData;
}): JSX.Element {
  const determinate = () =>
    props.progress.fraction != null && props.progress.totalBytes != null;
  const percent = () => Math.round((props.progress.fraction ?? 0) * 100);

  return (
    <div class="flex flex-col gap-1">
      <ProgressBar
        tone="info"
        value={determinate() ? percent() : undefined}
        showValue
      />
      <div class="flex items-baseline justify-between gap-2">
        <Show
          when={props.progress.file}
          fallback={
            <Text variant="micro" tone="dim">
              {determinate() ? "Downloading" : "Preparing"}
            </Text>
          }
        >
          <Text variant="micro" tone="dim" class="min-w-0 truncate">
            {props.progress.file}
          </Text>
        </Show>
        <Show when={props.progress.totalBytes != null}>
          <Text variant="micro" tone="dim" class="shrink-0">
            {bytes(props.progress.downloadedBytes)} /{" "}
            {bytes(props.progress.totalBytes!)}
          </Text>
        </Show>
      </div>
    </div>
  );
}
