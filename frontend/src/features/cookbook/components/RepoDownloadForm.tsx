import { createSignal, Show, type JSX } from "solid-js";
import { Button, Input, Row, Text } from "~/ui";
import type { EngineKind } from "../model";
import { QuantSelect } from "./QuantSelect";

/** The "download by HF repo" row: a repo id + a repo-introspected quant, run on the given
 *  engine. The single capture point for the repo flow — reused by the LOCAL MODELS download,
 *  the GET STARTED run-locally serve, and the embedding serve. The quant dropdown self-hides
 *  where a quant doesn't apply (MLX bakes it into the repo id; no repo entered yet), so there
 *  is nothing to gate from here. `submitLabel`/`busyLabel` name the action. Validation is
 *  UX-only — the backend is the authority. */
export function RepoDownloadForm(props: {
  engine: EngineKind | null;
  onDownload: (repo: string, quant: string | undefined) => Promise<void>;
  submitLabel?: string;
  busyLabel?: string;
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
        <QuantSelect
          repo={repo()}
          engine={props.engine}
          value={quant()}
          onChange={setQuant}
        />
        <Button type="submit" leading="download" disabled={!canSubmit()}>
          {busy()
            ? (props.busyLabel ?? "DOWNLOADING")
            : (props.submitLabel ?? "DOWNLOAD")}
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
