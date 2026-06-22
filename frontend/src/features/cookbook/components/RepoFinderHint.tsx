import { Show, type JSX } from "solid-js";
import { ExternalLink, Stack, Text } from "~/ui";
import type { EngineKind, Workload } from "../model";

/** Guidance for the free-text repo flow: what to paste and where to find it. The backend
 *  serves any Hugging Face repo, so rather than curate a (quickly-stale) model list, this
 *  points the operator at the right filtered HF listing for their engine + workload.
 *
 *  Presentation-only — static copy + an outbound link. */
const HF = "https://huggingface.co/models";

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
          fallback="Paste any Hugging Face repo id below. Choose an instruct model with native tool-calling (e.g. Qwen, Llama 3.x) so the agent can use tools."
        >
          Paste any GGUF embedding repo id below. The knowledge base re-indexes
          into its vector space automatically.
        </Show>
      </Text>
      <ExternalLink href={link().href}>{link().label}</ExternalLink>
    </Stack>
  );
}
