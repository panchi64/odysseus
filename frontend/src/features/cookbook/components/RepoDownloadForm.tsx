import { createSignal, Show, type JSX } from "solid-js";
import { Button, Input, Row, Text } from "~/ui";
import type { EngineKind } from "../model";

/** The free-text "download by HF repo" row: a repo id + optional quant, run on
 *  the top available engine with its default `chat` workload. Validation is
 *  UX-only — the backend is the authority. */
export function RepoDownloadForm(props: {
  engine: EngineKind | null;
  onDownload: (repo: string, quant: string | undefined) => Promise<void>;
}): JSX.Element {
  const [repo, setRepo] = createSignal("");
  const [quant, setQuant] = createSignal("");
  const [busy, setBusy] = createSignal(false);
  const canSubmit = () => repo().trim().length > 0 && !busy() && !!props.engine;

  async function submit(e: Event): Promise<void> {
    e.preventDefault();
    if (!canSubmit()) return;
    setBusy(true);
    try {
      await props.onDownload(repo().trim(), quant().trim() || undefined);
      setRepo("");
      setQuant("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit}>
      <Row gap={3} align="end" class="flex-wrap">
        <div class="min-w-0 flex-1">
          <Input
            label="HUGGING FACE REPO"
            placeholder="org/model"
            value={repo()}
            onInput={(e) => setRepo(e.currentTarget.value)}
          />
        </div>
        <div class="w-32">
          <Input
            label="QUANT (OPTIONAL)"
            placeholder="Q4_K_M"
            value={quant()}
            onInput={(e) => setQuant(e.currentTarget.value)}
          />
        </div>
        <Button type="submit" leading="download" disabled={!canSubmit()}>
          {busy() ? "DOWNLOADING" : "DOWNLOAD"}
        </Button>
      </Row>
      <Show when={!props.engine}>
        <Text variant="micro" tone="dim" class="mt-1">
          No available engine to download with on this host yet.
        </Text>
      </Show>
    </form>
  );
}
