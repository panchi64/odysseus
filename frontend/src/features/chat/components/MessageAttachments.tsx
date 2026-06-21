import { createMemo, For, Show, type JSX } from "solid-js";
import { AttachmentChip } from "~/ui";
import { useUploads } from "~/features/uploads/data";
import type { Upload } from "~/features/uploads/model";

interface MessageAttachmentsProps {
  /** Upload ids attached to this sent user turn. */
  ids: string[];
}

/** Read-only attachment chips on a sent user turn. Resolves each id against the
 *  uploads seam for its filename + KB state and links to the file; a since-deleted
 *  upload reads as an error chip. The seam is the single source of truth — the chip
 *  reflects current KB membership, not a stale copy captured at send time. */
export function MessageAttachments(
  props: MessageAttachmentsProps,
): JSX.Element {
  const uploads = useUploads();
  // One keyed index rebuilt per list change — O(1) lookups across every chip,
  // not a linear scan per chip on every reactive update.
  const byId = createMemo(
    () => new Map<string, Upload>(uploads()?.map((u) => [u.id, u]) ?? []),
  );

  return (
    <Show when={props.ids.length > 0}>
      <div class="flex max-w-[80%] flex-wrap justify-end gap-2">
        <For each={props.ids}>
          {(id) => {
            const u = () => byId().get(id);
            return (
              <AttachmentChip
                name={u()?.name ?? id}
                href={`/uploads/${id}`}
                status={u() ? undefined : "error"}
                kbExcluded={u()?.kbExcluded ?? false}
              />
            );
          }}
        </For>
      </div>
    </Show>
  );
}
