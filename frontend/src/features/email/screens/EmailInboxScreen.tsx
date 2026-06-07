import { createSignal, For, Show, Suspense, type JSX } from "solid-js";
import {
  Button,
  Drawer,
  EmptyState,
  Input,
  InstrumentBand,
  ListRow,
  LoadingText,
  PageHeader,
  Panel,
  Row,
  Select,
  Stack,
  StatusFlag,
  Text,
  Textarea,
} from "~/ui";
import { relativeTime } from "~/lib/format";
import {
  useEmailAccounts,
  useEmailFolders,
  useEmailMessages,
  useReplySuggestions,
} from "../data";
import type { EmailMessage } from "../model";

const urgencyStatus = {
  low: "idle",
  normal: "idle",
  high: "alert",
} as const;

export function EmailInboxScreen(): JSX.Element {
  const accounts = useEmailAccounts();
  const folders = useEmailFolders();
  const messages = useEmailMessages();
  const replySuggestions = useReplySuggestions();

  const [selectedAccountId, setSelectedAccountId] = createSignal("acc-1");
  const [selectedFolderId, setSelectedFolderId] = createSignal("f-inbox-1");
  const [selectedMessageId, setSelectedMessageId] = createSignal<string | null>(
    "msg-1",
  );
  const [composeOpen, setComposeOpen] = createSignal(false);
  const [composeTo, setComposeTo] = createSignal("");
  const [composeSubject, setComposeSubject] = createSignal("");
  const [composeBody, setComposeBody] = createSignal("");

  const filteredMessages = () =>
    (messages() ?? []).filter(
      (m) =>
        m.accountId === selectedAccountId() &&
        m.folderId === selectedFolderId(),
    );

  const selectedMessage = (): EmailMessage | undefined =>
    (messages() ?? []).find((m) => m.id === selectedMessageId());

  const accountFolders = () =>
    (folders() ?? []).filter((f) => f.accountId === selectedAccountId());

  const unreadCount = () => filteredMessages().filter((m) => !m.read).length;
  const highUrgencyCount = () =>
    filteredMessages().filter((m) => m.urgency === "high").length;
  const spamCount = () =>
    (messages() ?? []).filter(
      (m) => m.accountId === selectedAccountId() && m.spam,
    ).length;

  return (
    <Stack gap={6}>
      <PageHeader
        title="EMAIL"
        subtitle="Multi-account inbox with AI triage."
        assetId="COMM-MAIL-01.0"
        actions={
          <Button
            variant="primary"
            leading="plus"
            onClick={() => setComposeOpen(true)}
          >
            COMPOSE
          </Button>
        }
      />

      <Suspense fallback={<LoadingText label="LOADING TRIAGE" />}>
        <InstrumentBand
          items={[
            {
              label: "UNREAD",
              value: String(unreadCount()),
              tone: unreadCount() > 0 ? "bright" : "dim",
            },
            {
              label: "HIGH URGENCY",
              value: String(highUrgencyCount()),
              tone: highUrgencyCount() > 0 ? "alert" : "dim",
            },
            {
              label: "SPAM FLAGGED",
              value: String(spamCount()),
              tone: spamCount() > 0 ? "warn" : "dim",
            },
            {
              label: "ACCOUNT",
              value:
                accounts()?.find((a) => a.id === selectedAccountId())
                  ?.address ?? "—",
            },
            {
              label: "FOLDER",
              value: selectedFolderId()
                .replace(/f-/, "")
                .replace(/-\d$/, "")
                .toUpperCase(),
            },
          ]}
        />
      </Suspense>

      <div class="flex h-full min-h-0 gap-4">
        {/* Account / Folder rail */}
        <aside class="hidden w-48 shrink-0 flex-col gap-4 lg:flex">
          <Panel label="ACCOUNTS" flush>
            <Suspense
              fallback={
                <div class="p-3">
                  <LoadingText />
                </div>
              }
            >
              <For each={accounts()}>
                {(acc) => (
                  <ListRow
                    label={acc.name}
                    leading="mail"
                    selected={acc.id === selectedAccountId()}
                    onClick={() => {
                      setSelectedAccountId(acc.id);
                      const firstFolder = (folders() ?? []).find(
                        (f) => f.accountId === acc.id,
                      );
                      if (firstFolder) setSelectedFolderId(firstFolder.id);
                      setSelectedMessageId(null);
                    }}
                    right={
                      <Text variant="micro" tone="dim">
                        {acc.provider}
                      </Text>
                    }
                  />
                )}
              </For>
            </Suspense>
          </Panel>

          <Panel label="FOLDERS" flush>
            <Suspense
              fallback={
                <div class="p-3">
                  <LoadingText />
                </div>
              }
            >
              <For each={accountFolders()}>
                {(folder) => (
                  <ListRow
                    label={folder.name}
                    selected={folder.id === selectedFolderId()}
                    onClick={() => {
                      setSelectedFolderId(folder.id);
                      setSelectedMessageId(null);
                    }}
                    right={
                      <Show when={folder.count > 0}>
                        <Text variant="micro" tone="bright">
                          {folder.count}
                        </Text>
                      </Show>
                    }
                  />
                )}
              </For>
            </Suspense>
          </Panel>
        </aside>

        {/* Message list */}
        <section class="flex min-h-0 w-72 shrink-0 flex-col">
          <Panel label="MESSAGES" flush class="flex min-h-0 flex-1 flex-col">
            <div class="min-h-0 flex-1 overflow-y-auto">
              <Suspense
                fallback={
                  <div class="p-3">
                    <LoadingText />
                  </div>
                }
              >
                <Show
                  when={filteredMessages().length}
                  fallback={
                    <EmptyState
                      icon="mail"
                      message="NO MESSAGES"
                      hint="This folder is empty."
                    />
                  }
                >
                  <For each={filteredMessages()}>
                    {(msg) => (
                      <button
                        type="button"
                        class="w-full border-b border-line text-left transition-colors hover:bg-raised"
                        classList={{
                          "bg-raised": msg.id === selectedMessageId(),
                        }}
                        onClick={() => setSelectedMessageId(msg.id)}
                      >
                        <div class="px-3 py-2">
                          <Row justify="between" align="start" gap={2}>
                            <Text
                              variant="label"
                              tone={msg.read ? "dim" : "bright"}
                              class="truncate"
                            >
                              {msg.fromName}
                            </Text>
                            <Text variant="micro" tone="dim" class="shrink-0">
                              {relativeTime(msg.receivedAt)}
                            </Text>
                          </Row>
                          <Text
                            variant="body"
                            tone={msg.read ? "dim" : "default"}
                            class="mt-0.5 truncate"
                          >
                            {msg.subject}
                          </Text>
                          <Text
                            variant="micro"
                            tone="dim"
                            class="mt-0.5 truncate"
                          >
                            {msg.snippet}
                          </Text>
                          <Row gap={1} wrap class="mt-1.5">
                            <Show when={msg.urgency === "high"}>
                              <StatusFlag status="alert">URGENT</StatusFlag>
                            </Show>
                            <Show when={msg.spam}>
                              <StatusFlag status="warn">SPAM</StatusFlag>
                            </Show>
                            <For each={msg.tags.slice(0, 2)}>
                              {(tag) => (
                                <StatusFlag status="idle">
                                  {tag.toUpperCase()}
                                </StatusFlag>
                              )}
                            </For>
                          </Row>
                        </div>
                      </button>
                    )}
                  </For>
                </Show>
              </Suspense>
            </div>
          </Panel>
        </section>

        {/* Reading pane */}
        <section class="flex min-h-0 min-w-0 flex-1 flex-col gap-4">
          <Show
            when={selectedMessage()}
            fallback={
              <div class="flex flex-1 items-center justify-center">
                <EmptyState
                  icon="mail"
                  message="NO MESSAGE SELECTED"
                  hint="Select a message from the list."
                />
              </div>
            }
          >
            {(msg) => (
              <>
                <Panel
                  label="MESSAGE"
                  meta={
                    <StatusFlag status={urgencyStatus[msg().urgency]}>
                      {msg().urgency.toUpperCase()}
                    </StatusFlag>
                  }
                >
                  <Stack gap={3}>
                    <div class="border-b border-line pb-3">
                      <Text variant="readout" tone="bright">
                        {msg().subject}
                      </Text>
                      <Row gap={2} align="center" class="mt-1">
                        <Text variant="micro" tone="dim">
                          FROM
                        </Text>
                        <Text variant="label" tone="default">
                          {msg().fromName}
                        </Text>
                        <Text variant="micro" tone="dim">
                          {msg().from}
                        </Text>
                        <Text variant="micro" tone="dim" class="ml-auto">
                          {relativeTime(msg().receivedAt)}
                        </Text>
                      </Row>
                    </div>
                    <Text
                      variant="body"
                      tone="default"
                      class="whitespace-pre-wrap"
                    >
                      {msg().body}
                    </Text>
                  </Stack>
                </Panel>

                <Panel label="AI SUMMARY" state="active">
                  <Text variant="body" tone="default">
                    {msg().summary}
                  </Text>
                </Panel>

                <Panel label="SUGGESTED REPLIES">
                  <Suspense fallback={<LoadingText />}>
                    <Row gap={2} wrap>
                      <For each={replySuggestions()}>
                        {(suggestion) => (
                          <Button
                            variant="default"
                            size="sm"
                            onClick={() => {
                              setComposeTo(msg().from);
                              setComposeSubject(`Re: ${msg().subject}`);
                              setComposeBody(suggestion.body);
                              setComposeOpen(true);
                            }}
                          >
                            {suggestion.label}
                          </Button>
                        )}
                      </For>
                      <Button
                        variant="ghost"
                        size="sm"
                        leading="edit"
                        onClick={() => {
                          setComposeTo(msg().from);
                          setComposeSubject(`Re: ${msg().subject}`);
                          setComposeBody("");
                          setComposeOpen(true);
                        }}
                      >
                        COMPOSE REPLY
                      </Button>
                    </Row>
                  </Suspense>
                </Panel>
              </>
            )}
          </Show>
        </section>
      </div>

      {/* Compose drawer */}
      <Drawer
        open={composeOpen()}
        onClose={() => setComposeOpen(false)}
        title="COMPOSE MESSAGE"
        side="right"
        footer={
          <Row gap={2}>
            <Button variant="ghost" onClick={() => setComposeOpen(false)}>
              CANCEL
            </Button>
            <Button
              variant="primary"
              leading="send"
              onClick={() => setComposeOpen(false)}
            >
              SEND
            </Button>
          </Row>
        }
      >
        <Stack gap={4}>
          <Input
            label="TO"
            value={composeTo()}
            onInput={(e) => setComposeTo(e.currentTarget.value)}
            placeholder="recipient@example.com"
          />
          <Input
            label="SUBJECT"
            value={composeSubject()}
            onInput={(e) => setComposeSubject(e.currentTarget.value)}
            placeholder="Subject line"
          />
          <Select
            label="SIGNATURE"
            value="sig-1"
            onChange={() => {}}
            options={[
              { value: "sig-1", label: "Francisco Casiano" },
              { value: "sig-none", label: "No signature" },
            ]}
          />
          <Textarea
            label="BODY"
            rows={12}
            value={composeBody()}
            onInput={(e) => setComposeBody(e.currentTarget.value)}
          />
          <Button variant="ghost" leading="upload" size="sm">
            ATTACH FILE
          </Button>
        </Stack>
      </Drawer>
    </Stack>
  );
}
