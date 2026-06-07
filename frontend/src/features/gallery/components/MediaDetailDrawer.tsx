import { createSignal, For, onCleanup, Show, type JSX } from "solid-js";
import {
  Box,
  Button,
  Divider,
  Drawer,
  Field,
  Icon,
  ProgressBar,
  Row,
  Stack,
  StatusFlag,
  Text,
  Tooltip,
  toast,
} from "~/ui";
import { bytes, date } from "~/lib/format";
import type { MediaItem } from "../model";

type AIAction = "upscale" | "inpaint" | "denoise" | "style-transfer" | null;

const AI_ACTION_META: Record<
  NonNullable<AIAction>,
  { label: string; tooltip: string; variantSuffix: string }
> = {
  upscale: {
    label: "UPSCALE",
    tooltip:
      "Increase resolution 2×. Saves as a new variant; original is preserved.",
    variantSuffix: "upscaled",
  },
  inpaint: {
    label: "INPAINT",
    tooltip:
      "Fill or restore selected regions. Saves as a new variant; original is preserved.",
    variantSuffix: "inpainted",
  },
  denoise: {
    label: "DENOISE",
    tooltip:
      "Reduce noise and artifacts. Saves as a new variant; original is preserved.",
    variantSuffix: "denoised",
  },
  "style-transfer": {
    label: "STYLE XFER",
    tooltip:
      "Apply a style preset. Saves as a new variant; original is preserved.",
    variantSuffix: "styled",
  },
};

interface MediaDetailDrawerProps {
  item: MediaItem | null;
  open: boolean;
  onClose: () => void;
}

export function MediaDetailDrawer(props: MediaDetailDrawerProps): JSX.Element {
  const [activeAction, setActiveAction] = createSignal<AIAction>(null);
  const [progress, setProgress] = createSignal(0);
  const timers: ReturnType<typeof setTimeout>[] = [];
  onCleanup(() => timers.forEach(clearTimeout));

  function runAction(action: NonNullable<AIAction>) {
    if (activeAction()) return;
    setActiveAction(action);
    setProgress(0);
    const iv = setInterval(() => {
      setProgress((p) => {
        if (p >= 100) {
          clearInterval(iv);
          const item = props.item;
          if (item) {
            const meta = AI_ACTION_META[action];
            const ext = item.title.includes(".")
              ? item.title.slice(item.title.lastIndexOf("."))
              : "";
            const base = item.title.includes(".")
              ? item.title.slice(0, item.title.lastIndexOf("."))
              : item.title;
            const variantName = `${base}_${meta.variantSuffix}${ext}`;
            toast.success(`NEW VARIANT SAVED: ${variantName}`, {
              duration: 5000,
            });
          }
          const t = setTimeout(() => setActiveAction(null), 600);
          timers.push(t);
          return 100;
        }
        return p + 4;
      });
    }, 60);
    timers.push(iv);
  }

  return (
    <Drawer
      open={props.open}
      onClose={props.onClose}
      title="MEDIA DETAIL"
      side="right"
    >
      <Show
        when={props.item}
        fallback={<Text tone="dim">No item selected.</Text>}
      >
        {(item) => (
          <Stack gap={4}>
            {/* Preview */}
            <Box class="aspect-square w-full border border-line bg-bg flex items-center justify-center">
              <Stack gap={2} class="items-center">
                <Icon
                  name={item().type === "video" ? "play" : "image"}
                  size={40}
                  class="text-dim"
                />
                <Text variant="micro" tone="dim">
                  PREVIEW PLACEHOLDER
                </Text>
              </Stack>
            </Box>

            <Stack gap={2}>
              <Text variant="label" tone="bright">
                {item().title}
              </Text>
              <Row gap={2} wrap>
                <StatusFlag
                  status={item().type === "video" ? "info" : "nominal"}
                >
                  {item().type.toUpperCase()}
                </StatusFlag>
                <Show when={item().favorite}>
                  <StatusFlag status="warn">FAVORITE</StatusFlag>
                </Show>
              </Row>
            </Stack>

            <Stack gap={1}>
              <Field
                label="ALBUM"
                value={item().album.toUpperCase()}
                orientation="row"
              />
              <Field
                label="SIZE"
                value={bytes(item().sizeBytes)}
                orientation="row"
              />
              <Field
                label="CREATED"
                value={date(item().createdAt)}
                orientation="row"
              />
            </Stack>

            <Stack gap={1}>
              <Text variant="label" tone="dim">
                TAGS
              </Text>
              <Row gap={1} wrap>
                <For each={item().tags}>
                  {(tag) => (
                    <Text
                      variant="micro"
                      tone="dim"
                      class="border border-line px-1 py-0.5"
                    >
                      {tag}
                    </Text>
                  )}
                </For>
              </Row>
            </Stack>

            <Divider />

            <Stack gap={2}>
              <Stack gap={1}>
                <Text variant="label" tone="dim">
                  AI EDIT
                </Text>
                <Text variant="micro" tone="dim">
                  Operations save a new variant; the original is always
                  preserved.
                </Text>
              </Stack>
              <Show when={activeAction()}>
                {(action) => (
                  <ProgressBar
                    label={action().toUpperCase().replace("-", " ")}
                    value={progress()}
                    tone={progress() < 100 ? "info" : "nominal"}
                    showValue
                  />
                )}
              </Show>
              <div class="grid grid-cols-2 gap-2">
                <Tooltip label={AI_ACTION_META.upscale.tooltip} side="top">
                  <Button
                    variant="default"
                    size="sm"
                    leading="layers"
                    disabled={!!activeAction()}
                    onClick={() => runAction("upscale")}
                    class="w-full"
                  >
                    UPSCALE
                  </Button>
                </Tooltip>
                <Tooltip label={AI_ACTION_META.inpaint.tooltip} side="top">
                  <Button
                    variant="default"
                    size="sm"
                    leading="edit"
                    disabled={!!activeAction()}
                    onClick={() => runAction("inpaint")}
                    class="w-full"
                  >
                    INPAINT
                  </Button>
                </Tooltip>
                <Tooltip label={AI_ACTION_META.denoise.tooltip} side="top">
                  <Button
                    variant="default"
                    size="sm"
                    leading="activity"
                    disabled={!!activeAction()}
                    onClick={() => runAction("denoise")}
                    class="w-full"
                  >
                    DENOISE
                  </Button>
                </Tooltip>
                <Tooltip
                  label={AI_ACTION_META["style-transfer"].tooltip}
                  side="top"
                >
                  <Button
                    variant="default"
                    size="sm"
                    leading="compare"
                    disabled={!!activeAction()}
                    onClick={() => runAction("style-transfer")}
                    class="w-full"
                  >
                    STYLE XFER
                  </Button>
                </Tooltip>
              </div>
            </Stack>
          </Stack>
        )}
      </Show>
    </Drawer>
  );
}
