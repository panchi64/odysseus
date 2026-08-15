import { Show, type JSX } from "solid-js";
import { ExternalLink, Row, Stack, Text } from "~/ui";
import type { EngineKind, Workload } from "~/lib/api/models-types";

/** Guidance for the free-text repo flow: what to paste and where to find it. The backend
 *  serves any Hugging Face repo, so rather than curate a (quickly-stale) model list, this
 *  points the operator at the right filtered HF listing for their engine + workload.
 *
 *  Presentation-only — static copy + an outbound link. */
const HF = "https://huggingface.co/models";
const UNSLOTH = "https://huggingface.co/unsloth";

function finder(
  engine: EngineKind | null,
  workload: Workload,
): { href: string; label: string } {
  if (workload === "embedding") {
    return {
      href: `${HF}?library=gguf&pipeline_tag=feature-extraction&sort=trending`,
      label: "Browse GGUF embedding models on Hugging Face ↗",
    };
  }
  if (engine === "mlx") {
    return {
      href: `${HF}?library=mlx&pipeline_tag=text-generation&sort=trending`,
      label: "Browse MLX chat models on Hugging Face ↗",
    };
  }
  return {
    href: `${HF}?library=gguf&pipeline_tag=text-generation&sort=trending`,
    label: "Browse GGUF chat models on Hugging Face ↗",
  };
}

export function RepoFinderHint(props: {
  engine: EngineKind | null;
  workload: Workload;
}): JSX.Element {
  const link = () => finder(props.engine, props.workload);
  return (
    <Stack gap={1}>
      <Text variant="micro" tone="dim">
        <Show
          when={props.workload === "embedding"}
          fallback="Paste any Hugging Face repo id. Choose an instruct model with native tool-calling (e.g. Qwen, Llama 3.x) so the agent can use tools."
        >
          Paste any GGUF embedding repo id. The knowledge base re-indexes into
          its vector space automatically.
        </Show>
      </Text>
      <Row gap={2} align="baseline" wrap>
        <ExternalLink href={link().href}>{link().label}</ExternalLink>
        <Show when={props.workload === "chat" && props.engine !== "mlx"}>
          <Text variant="micro" tone="dim">
            · we're fond of the{" "}
            <ExternalLink href={UNSLOTH}>unsloth team's quants ↗</ExternalLink>
          </Text>
        </Show>
      </Row>
    </Stack>
  );
}
