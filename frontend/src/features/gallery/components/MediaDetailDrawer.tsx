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
} from "~/ui";
import { bytes, date } from "~/lib/format";
import type { MediaItem } from "../model";

type AIAction = "upscale" | "inpaint" | "denoise" | "style-transfer" | null;

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

  function runAction(action: AIAction) {
    if (activeAction()) return;
    setActiveAction(action);
    setProgress(0);
    const iv = setInterval(() => {
      setProgress((p) => {
        if (p >= 100) {
          clearInterval(iv);
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
              <Text variant="label" tone="dim">
                AI EDIT
              </Text>
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
                <Button
                  variant="default"
                  size="sm"
                  leading="layers"
                  disabled={!!activeAction()}
                  onClick={() => runAction("upscale")}
                >
                  UPSCALE
                </Button>
                <Button
                  variant="default"
                  size="sm"
                  leading="edit"
                  disabled={!!activeAction()}
                  onClick={() => runAction("inpaint")}
                >
                  INPAINT
                </Button>
                <Button
                  variant="default"
                  size="sm"
                  leading="activity"
                  disabled={!!activeAction()}
                  onClick={() => runAction("denoise")}
                >
                  DENOISE
                </Button>
                <Button
                  variant="default"
                  size="sm"
                  leading="compare"
                  disabled={!!activeAction()}
                  onClick={() => runAction("style-transfer")}
                >
                  STYLE XFER
                </Button>
              </div>
            </Stack>
          </Stack>
        )}
      </Show>
    </Drawer>
  );
}
