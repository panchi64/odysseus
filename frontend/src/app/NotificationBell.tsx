import { For, Show, type JSX } from "solid-js";
import { useNavigate } from "@solidjs/router";
import {
  Button,
  EmptyState,
  Icon,
  Popover,
  Select,
  StatusDot,
  Text,
  cx,
  type IconName,
} from "~/ui";
import { relativeTime } from "~/lib/format";
import {
  AUTO_CLEAR_OPTIONS,
  useNotifications,
} from "~/lib/stores/notifications";
import type {
  Notification,
  NotificationKind,
} from "~/lib/stream/notificationEvents";
import { openConversation } from "~/features/chat/data";
import { requestApprovalFocus } from "~/features/chat/viewerPersistence";

/** Icon + accent per kind (design: approval_needed = warn, run_failed = danger,
 *  run_completed/task_outcome = neutral, reminder = info accent). */
const KIND_ICON: Record<NotificationKind, IconName> = {
  approval_needed: "warning",
  run_failed: "close",
  run_completed: "check",
  reminder: "bell",
  task_outcome: "activity",
  system: "info",
};

const KIND_TONE: Record<NotificationKind, string> = {
  approval_needed: "text-warn",
  run_failed: "text-alert",
  run_completed: "text-dim",
  reminder: "text-info",
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
      class="flex w-full items-start gap-2 px-3 py-2 text-left transition-colors hover:bg-raised"
    >
      <Icon
        name={KIND_ICON[n().kind]}
        size={14}
        class={cx("mt-0.5 shrink-0", KIND_TONE[n().kind])}
      />
      <span class="min-w-0 flex-1">
        <span class="flex items-center gap-1.5">
          <Show when={unread()}>
            <StatusDot status="info" />
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
    // An approval deep-link asks the pending card to focus itself on arrival —
    // consumed once by the non-stale ApprovalCard that mounts for this thread.
    if (n.kind === "approval_needed") requestApprovalFocus();
    void notifications.markRead([n.id]);
    if (n.conversationId) {
      openConversation(n.conversationId);
      navigate("/chat");
    } else if (n.researchId) {
      navigate(`/research/${n.researchId}`);
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
            <span class="absolute -right-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-ctl bg-alert px-0.5 text-micro font-mono font-bold text-bg">
              {badge()}
            </span>
          </Show>
        </Button>
      )}
      panel={({ close }) => (
        <div class="flex max-h-96 flex-col">
          <div class="shrink-0">
            <div class="flex items-center justify-between gap-2 px-3 py-2">
              <Text variant="micro" tone="dim">
                Notifications
              </Text>
              <Show when={notifications.unreadCount > 0}>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => void notifications.markAllRead()}
                >
                  Mark all read
                </Button>
              </Show>
            </div>
            {/* Auto-clear: a display preference (mark read + drop from the list
                after a timeout). `approval_needed` is exempt. Off disables it. */}
            <div class="flex items-center gap-2 px-3 py-1.5">
              <Text variant="micro" tone="dim">
                Auto-clear
              </Text>
              <div class="ml-auto w-24">
                <Select
                  options={AUTO_CLEAR_OPTIONS}
                  value={String(notifications.autoClearSeconds)}
                  onChange={(v) => notifications.setAutoClearSeconds(Number(v))}
                />
              </div>
            </div>
          </div>
          <div class="min-h-0 flex-1 overflow-y-auto">
            <Show
              when={notifications.visibleItems.length > 0}
              fallback={<EmptyState icon="bell" message="No notifications" />}
            >
              <For each={notifications.visibleItems}>
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
