import { createResource, For, Show, type JSX } from "solid-js";
import { MetaAction, Popover, Text, Tooltip, toast } from "~/ui";
import { fetchAutoCompactOverride, setAutoCompactOverride } from "../data";
import { MetaSep } from "./MetaSep";

const TOOLTIP =
  "When this conversation nears the model's context limit, fold its earlier turns into a summary and keep going. The full transcript stays here — only what the model re-reads is condensed.";

/** The per-conversation auto-compaction control, as one segment of the composer's
 *  readout line: `Fold on` / `Fold off`, opening a menu that pins the behaviour for
 *  *this* conversation or clears the pin so it inherits the global default. The
 *  backend owns the resolution; this only reflects and relays it. Renders nothing
 *  until a thread exists.
 *
 *  It was a `Toggle` plus a reset `Button` while it lived in the status band above the
 *  transcript. A switch is chrome, and the line it sits in now is a readout — so the
 *  state became a word and the two actions became a menu. That also fixes something the
 *  switch could not say: the *reset* was a second control the operator had to notice,
 *  where "use the default" is simply the third option beside the other two. */
export function ConversationCompactionToggle(props: {
  conversationId: () => string | null;
}): JSX.Element {
  // Tag the fetched state with its conversation, so a thread switch can't show the previous
  // thread's value (or write against the wrong conversation) before the refetch lands.
  //
  // The fetcher swallows its own failure rather than rejecting, for the same reason
  // `ConversationGrants` does: this control is a secondary read in the composer's
  // readout line, which sits *outside* the transcript's ErrorBoundary. A rejected
  // resource re-throws on read (Solid's `.latest` calls `read()` while unresolved) and
  // would blank the whole chat screen over an unreachable toggle endpoint. Losing the
  // segment until the next thread switch is the right cost.
  const [state, { mutate }] = createResource(
    () => props.conversationId(),
    async (id) => {
      const s = await fetchAutoCompactOverride(id).catch(() => null);
      return s ? { id, ...s } : null;
    },
  );
  // `.latest`, not the resource — reading it while pending would suspend the
  // content region on every thread switch.
  const current = () => {
    const s = state.latest;
    return s && s.id === props.conversationId() ? s : undefined;
  };

  // `true`/`false` pin a per-chat override; `null` clears it back to inheriting the global default.
  async function apply(next: boolean | null) {
    const id = props.conversationId();
    if (!id) return;
    try {
      const saved = await setAutoCompactOverride(id, next);
      mutate({ id, ...saved });
    } catch {
      toast.error("Unable to update auto-compaction for this chat.");
    }
  }

  /* `Popover` rather than `Menu`, for one structural reason: `Menu` wraps whatever
     it is given in a `<button>` of its own, and the trigger here is already a
     button — nesting the two is invalid markup and leaves the inner control
     unreachable by keyboard. Driving the shared shell directly costs three lines
     and matches the grants segment beside it. */
  const OPTIONS: { label: string; value: boolean | null }[] = [
    { label: "On for this chat", value: true },
    { label: "Off for this chat", value: false },
    { label: "Use the default", value: null },
  ];

  return (
    <Show when={current()}>
      {(s) => (
        <>
          <MetaSep />
          <Popover
            align="right"
            panelClass="min-w-44 p-2"
            trigger={({ open, setOpen }) => (
              <Tooltip label={TOOLTIP} side="top">
                {/* Bright while this thread pins its own value, dim while it
                  inherits — brightness separates pinned from inherited, which is
                  exactly what the old label's tone swap said. */}
                <MetaAction
                  active={s().override !== null || open()}
                  aria-expanded={open()}
                  aria-label="Auto-compaction for this conversation"
                  onClick={() => setOpen(!open())}
                >
                  Fold {s().effective ? "on" : "off"}
                </MetaAction>
              </Tooltip>
            )}
            panel={({ close }) => (
              <div role="menu" class="flex flex-col">
                <For each={OPTIONS}>
                  {(option) => (
                    <button
                      type="button"
                      role="menuitemradio"
                      aria-checked={s().override === option.value}
                      onClick={() => {
                        close();
                        void apply(option.value);
                      }}
                      class="flex items-center justify-between gap-3 rounded-ctl px-2 py-1.5 text-left hover:bg-raised"
                    >
                      <Text
                        variant="label"
                        tone={
                          s().override === option.value ? "bright" : "default"
                        }
                      >
                        {option.label}
                      </Text>
                    </button>
                  )}
                </For>
              </div>
            )}
          />
        </>
      )}
    </Show>
  );
}
