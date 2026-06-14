import { Show, type JSX } from "solid-js";
import { Button, Composer, Text, toast } from "~/ui";
import { createCompareController } from "../compare/data";
import { ComparePaneView } from "../compare/ComparePane";

/** Side-by-side model compare — the COMPARE tab of the Model Cookbook. One
 *  message is fanned to two independently-selected models and their answers
 *  stream in parallel. Each pane is a real (but ephemeral) chat conversation, so
 *  the comparison is a true multi-turn dialogue against each model — not a
 *  one-shot. All run lifecycle is backend-owned; this panel only relays intent.
 *  Owns no page chrome; the Cookbook screen provides the header. */
export function ComparePanel(): JSX.Element {
  const compare = createCompareController();

  const stop = async () => {
    await compare.cancel();
    toast.success("Comparison stopped");
  };
  const reset = () => {
    compare.reset();
    toast.info("Comparison cleared");
  };

  return (
    <div class="flex h-[70vh] min-h-[28rem] flex-col gap-3">
      <div class="flex items-center justify-between gap-3">
        <Text variant="micro" tone="dim">
          One message, sent to both models at once. These threads are scratch —
          they stay out of your chat history.
        </Text>
        <Show when={compare.started()}>
          <Button variant="ghost" size="sm" leading="refresh" onClick={reset}>
            NEW COMPARISON
          </Button>
        </Show>
      </div>

      <div class="flex min-h-0 flex-1 flex-col gap-3 lg:flex-row">
        <ComparePaneView pane={compare.panes[0]} label="MODEL A" />
        <ComparePaneView pane={compare.panes[1]} label="MODEL B" />
      </div>

      <Composer
        disabled={compare.sending() || !compare.ready()}
        streaming={compare.sending()}
        onStop={() => void stop()}
        onSend={(text) => compare.send(text)}
        placeholder={
          compare.ready()
            ? "Message both models…"
            : "Select a model in each pane to begin…"
        }
        storageKey="compare:prompt"
      />
    </div>
  );
}
