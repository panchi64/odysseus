import { Show, type JSX } from "solid-js";
import {
  Button,
  InstrumentBand,
  Markdown,
  Panel,
  Row,
  Stack,
  Text,
} from "~/ui";
import { relativeTime } from "~/lib/format";
import type { ResearchOut } from "../model";

function formatDuration(seconds: number): string {
  const s = Math.round(seconds);
  if (s < 60) return `${s}S`;
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return rem > 0 ? `${m}M ${rem}S` : `${m}M`;
}

interface ReportViewProps {
  entry: ResearchOut;
  onContinueInChat: () => void;
  continuing: boolean;
}

/** The finished report: rendered with the SAME `Markdown` component chat uses
 *  for an assistant answer (see `~/ui` `Markdown`'s own doc comment — it's
 *  built for assistant replies, research reports, and document bodies alike).
 *  Citations are inline in the report's Markdown (the writer cites from the
 *  evidence ledger as it composes), not a separate structured list, so there is
 *  no separate citation renderer to fork here. */
export function ReportView(props: ReportViewProps): JSX.Element {
  const stats = () => props.entry.stats;

  return (
    <Stack gap={4}>
      <Show when={stats()}>
        {(s) => (
          <InstrumentBand
            items={[
              { label: "ROUNDS", value: String(s().rounds) },
              { label: "SOURCES", value: String(s().sources) },
              { label: "QUERIES", value: String(s().queries) },
              { label: "DURATION", value: formatDuration(s().durationS) },
              { label: "MODEL", value: s().model },
            ]}
          />
        )}
      </Show>

      <Panel label="REPORT">
        <Markdown>{props.entry.report ?? ""}</Markdown>
      </Panel>

      <Panel>
        <Row gap={3} align="center" justify="between">
          <Stack gap={1}>
            <Text variant="label" tone="bright">
              CONTINUE IN CHAT
            </Text>
            <Text variant="micro" tone="dim">
              Start a follow-up conversation with this report loaded as context
              — no re-running the research.
            </Text>
          </Stack>
          <Button
            variant="primary"
            leading="send"
            disabled={props.continuing}
            onClick={props.onContinueInChat}
          >
            CONTINUE IN CHAT
          </Button>
        </Row>
      </Panel>

      <Show when={props.entry.finishedAt}>
        <Text variant="micro" tone="dim">
          Finished {relativeTime(props.entry.finishedAt!)}
        </Text>
      </Show>
    </Stack>
  );
}
