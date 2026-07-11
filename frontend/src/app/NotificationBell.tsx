import { For, Show, type JSX } from "solid-js";
import { useNavigate } from "@solidjs/router";
import {
  Button,
  EmptyState,
  Icon,
  Popover,
  Text,
  cx,
  type IconName,
} from "~/ui";
import { relativeTime } from "~/lib/format";
import { useNotifications } from "~/lib/stores/notifications";
import type {
  Notification,
  NotificationKind,
} from "~/lib/stream/notificationEvents";
import { openConversation } from "~/features/chat/data";

/** Icon + accent per kind (design: approval_needed = warn, run_failed = danger,
 *  run_completed = neutral). `task_outcome`/`system` read neutral too — nothing
 *  emits `task_outcome` yet (Phase 5 seam). */
const KIND_ICON: Record<NotificationKind, IconName> = {
  approval_needed: "warning",
  run_failed: "close",
  run_completed: "check",
  task_outcome: "activity",
  system: "info",
};

const KIND_TONE: Record<NotificationKind, string> = {
  approval_needed: "text-warn",
  run_failed: "text-alert",
  run_completed: "text-dim",
  task_outcome: "text-dim",
  system: "text-dim",
};

/** One notification row: kind icon, title + optional body, relative time, and
 *  unread emphasis (brighter title, a leading dot). Clicking marks it read and
 *  — when it references a conversation — navigates there; the chat screen's
 *  cold-load/reattach machinery takes it from there. */
function NotificationRow(props: {
  notification: Notification;
  onOpen: (n: Notification) => void;
}): JSX.Element {
  const n = () => props.notification;
  const unread = () => !n().readAt;
  return (
    <button
      type="button"
      onClick={() => props.onOpen(n())}
      class="flex w-full items-start gap-2 border-b border-line px-3 py-2 text-left transition-colors last:border-0 hover:bg-raised"
    >
      <Icon
        name={KIND_ICON[n().kind]}
        size={14}
        class={cx("mt-0.5 shrink-0", KIND_TONE[n().kind])}
      />
      <span class="min-w-0 flex-1">
        <span class="flex items-center gap-1.5">
          <Show when={unread()}>
            <span
              class="size-1.5 shrink-0 rounded-full bg-info"
              aria-hidden="true"
            />
          </Show>
          <Text
            variant="label"
            tone={unread() ? "bright" : "dim"}
            class="truncate"
          >
            {n().title}
          </Text>
        </span>
        <Show when={n().body}>
          <Text variant="micro" tone="dim" class="mt-0.5 block truncate">
            {n().body}
          </Text>
        </Show>
      </span>
      <Text variant="micro" tone="dim" class="shrink-0 whitespace-nowrap">
        {relativeTime(n().createdAt)}
      </Text>
    </button>
  );
}

/** Sidebar bell + unread badge, opening a newest-first notification panel — the
 *  durable attention surface (design: approval/failure/completion/task-outcome
 *  notifications land here even when the operator was elsewhere). Read/unread,
 *  emit, and dedupe policy are entirely backend-owned; this only renders the
 *  store built by the previous batch (`~/lib/stores/notifications`) and relays
 *  mark-read/click intent back to it. */
export function NotificationBell(): JSX.Element {
  const notifications = useNotifications();
  const navigate = useNavigate();

  const badge = () => {
    const c = notifications.unreadCount;
    return c > 9 ? "9+" : String(c);
  };

  const openNotification = (n: Notification) => {
    void notifications.markRead([n.id]);
    if (n.conversationId) {
      openConversation(n.conversationId);
      navigate("/chat");
    }
  };

  return (
    <Popover
      align="right"
      panelClass="w-80 max-h-96 flex flex-col overflow-hidden"
      trigger={({ open, setOpen }) => (
        <Button
          variant="ghost"
          size="sm"
          class="relative"
          aria-label="Notifications"
          onClick={() => setOpen(!open())}
        >
          <Icon name="bell" size={14} />
          <Show when={notifications.unreadCount > 0}>
            <span class="absolute -right-1 -top-1 flex h-3.5 min-w-3.5 items-center justify-center rounded-ctl bg-alert px-0.5 text-[10px] font-mono font-bold leading-none text-bg">
              {badge()}
            </span>
          </Show>
        </Button>
      )}
      panel={({ close }) => (
        <div class="flex max-h-96 flex-col">
          <div class="flex shrink-0 items-center justify-between gap-2 border-b border-line px-3 py-2">
            <Text variant="micro" tone="dim">
              NOTIFICATIONS
            </Text>
            <Show when={notifications.unreadCount > 0}>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => void notifications.markAllRead()}
              >
                MARK ALL READ
              </Button>
            </Show>
          </div>
          <div class="min-h-0 flex-1 overflow-y-auto">
            <Show
              when={notifications.items.length > 0}
              fallback={<EmptyState icon="bell" message="NO NOTIFICATIONS" />}
            >
              <For each={notifications.items}>
                {(n) => (
                  <NotificationRow
                    notification={n}
                    onOpen={(item) => {
                      close();
                      openNotification(item);
                    }}
                  />
                )}
              </For>
            </Show>
          </div>
        </div>
      )}
    />
  );
}
