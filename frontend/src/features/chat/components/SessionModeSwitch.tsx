import { For, type JSX } from "solid-js";
import { useNavigate } from "@solidjs/router";
import { SESSION_MODES } from "~/lib/modes";
import { Icon, Text, Tooltip, cx } from "~/ui";
import {
  activeSessionMode,
  setActiveSessionMode,
} from "~/lib/stores/sessionMode";

/**
 * **Which kind of work you are looking at** — the rail's first control, above the
 * threads it arranges.
 *
 * It used to be a dropdown in the composer, shown only while a thread was still
 * unsaved, because the mode was a property of the message being sent. It is not:
 * it is a property of the *thread*, and therefore of the list of threads. Here it
 * does one thing that reads as three — it files what the rail shows, decides what
 * the next new thread will be, and repaints the signature accent through
 * `data-mode` — because those are the same fact stated at three ranges.
 *
 * The mode of a thread already saved is still immutable and still the backend's:
 * a code thread owns a git branch, and re-pointing it would strand that branch.
 * Opening one moves this switch to match it rather than the other way round.
 *
 * **It no longer asks which directory a code thread will work in.** That line lived
 * here for as long as the directory was something chosen *after* pressing NEW; now the
 * directory comes first and the thread is started from its own section of the rail, so
 * the question is asked where the answer already is. This is the mode switch and
 * nothing else.
 */
export function SessionModeSwitch(): JSX.Element {
  const mode = activeSessionMode;
  const navigate = useNavigate();
  /** Pick a mode, and go where that mode's threads are.
   *
   *  Filing the rail without moving was right while a Chat row sat above this one
   *  to do the moving. With that row gone this is the way in, and a control that
   *  re-sorts a list you cannot see is not one. Navigating from `/chat` is a no-op
   *  and leaves the open thread alone, so the only case it changes is the one
   *  where the operator is looking at something else. */
  const setMode = (id: Parameters<typeof setActiveSessionMode>[0]): void => {
    setActiveSessionMode(id);
    navigate("/chat");
  };

  return (
    <div class="flex flex-col gap-1 px-2 pb-1">
      <div
        role="radiogroup"
        aria-label="Session mode"
        class="flex items-center gap-1 rounded-ctl bg-sunken p-0.5"
      >
        <For each={SESSION_MODES}>
          {(spec) => (
            <Tooltip
              delay={600}
              side="bottom"
              label={spec.description}
              class="min-w-0 flex-1"
            >
              <button
                type="button"
                role="radio"
                aria-checked={mode() === spec.id}
                onClick={() => setMode(spec.id)}
                class={cx(
                  "flex w-full items-center justify-center gap-1.5 rounded-ctl px-2 py-1.5 transition-colors hover:bg-raised",
                  // Selection is a raised fill on a smoothed corner, the same
                  // way the rail marks the page you are on — not a coloured pill,
                  // which would spend the signature accent on the control that
                  // *chooses* the signature accent.
                  mode() === spec.id && "bg-raised",
                )}
              >
                <Icon
                  name={spec.icon}
                  size={14}
                  class={mode() === spec.id ? "text-bright" : "text-dim"}
                />
                <Text
                  variant="label"
                  tone={mode() === spec.id ? "bright" : "dim"}
                >
                  {spec.label}
                </Text>
              </button>
            </Tooltip>
          )}
        </For>
      </div>
    </div>
  );
}
