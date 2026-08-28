import { createResource, For, Show, type JSX } from "solid-js";
import { Chip, confirm, Icon, Row, Text, toast } from "~/ui";
import { fetchGrants, revokeGrant } from "../data";
import type { ApprovalGrant } from "../model";

/** The conversation's active tool auto-approval grants — a visible, revocable run of
 *  chips showing what the operator allowed to skip the per-call approval prompt for the
 *  rest of this thread. Renders nothing when there are none, and carries no band of its
 *  own: it is one segment of `ConversationStatusStrip`, which owns the layout.
 *  Refetches when the thread changes or the `revalidate` accessor ticks (e.g. a grant
 *  was just recorded). */
export function ConversationGrants(props: {
  conversationId: () => string | null;
  revalidate?: () => unknown;
}): JSX.Element {
  // Tag the fetched grants with the conversation they belong to. On a thread switch the
  // resource keeps the *previous* thread's value until the refetch resolves; without the
  // tag the strip would show stale chips and a click would revoke against the now-current
  // (wrong) conversation. The tag lets us ignore the value until it matches what's on
  // screen, and revoke against the conversation the chips actually belong to.
  //
  // The fetcher swallows its own failure rather than rejecting. This strip is a
  // secondary read living inside the transcript: a rejected resource re-throws
  // on read and would take the whole conversation down with it. An unreachable
  // grants endpoint should cost the operator the strip, nothing more — the next
  // decision re-ticks `revalidate` and it comes back.
  const [grants, { mutate, refetch }] = createResource(
    () => ({ id: props.conversationId(), tick: props.revalidate?.() }),
    async (src) => ({
      id: src.id,
      items: src.id
        ? await fetchGrants(src.id).catch(() => [] as ApprovalGrant[])
        : ([] as ApprovalGrant[]),
    }),
  );

  // `.latest`, not the resource — reading it while pending would suspend the
  // content region on every thread switch.
  const current = () => {
    const g = grants.latest;
    return g && g.id === props.conversationId() ? g : undefined;
  };
  const items = (): ApprovalGrant[] => current()?.items ?? [];

  async function revoke(toolName: string) {
    const id = current()?.id;
    if (!id) return;
    const ok = await confirm({
      title: `Stop auto-approving ${toolName}?`,
      detail:
        "The agent will pause and ask for approval the next time it calls this tool in this conversation.",
      confirmLabel: "REVOKE",
      cancelLabel: "CANCEL",
      tone: "alert",
    });
    if (!ok) return;
    try {
      await revokeGrant(id, toolName);
      mutate((g) =>
        g ? { ...g, items: g.items.filter((x) => x.toolName !== toolName) } : g,
      );
      toast.success(`Stopped auto-approving ${toolName}.`);
    } catch {
      toast.error("Unable to revoke the grant.");
      void refetch();
    }
  }

  return (
    <Show when={items().length > 0}>
      <Row gap={2} align="center" class="flex-wrap">
        <Text variant="label" tone="dim">
          AUTO-APPROVED
        </Text>
        <For each={items()}>
          {(g) => (
            <Chip leading="check" onClick={() => revoke(g.toolName)}>
              <span class="inline-flex items-center gap-1">
                {g.toolName}
                <Icon name="close" size={12} />
              </span>
            </Chip>
          )}
        </For>
      </Row>
    </Show>
  );
}
