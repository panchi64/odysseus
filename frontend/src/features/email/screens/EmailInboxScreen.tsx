import {
  createSignal,
  For,
  Show,
  Suspense,
  type Accessor,
  type JSX,
} from "solid-js";
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
  toast,
} from "~/ui";
import { relativeTime } from "~/lib/format";
import {
  useEmailAccounts,
  useEmailFolders,
  useEmailMessages,
  useReplySuggestions,
} from "../data";
import type { EmailAccount, EmailFolder, EmailMessage } from "../model";

const urgencyStatus = {
  low: "idle",
  normal: "idle",
  high: "alert",
} as const;

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

// ─── Account / Folder Rail ────────────────────────────────────────────────────

interface AccountFolderRailProps {
  accounts: Accessor<EmailAccount[] | undefined>;
  folders: Accessor<EmailFolder[] | undefined>;
  selectedAccountId: Accessor<string>;
  selectedFolderId: Accessor<string>;
  onAccountSelect: (acc: EmailAccount) => void;
  onFolderSelect: (folder: EmailFolder) => void;
}

function AccountFolderRail(props: AccountFolderRailProps): JSX.Element {
  const accountFolders = () =>
    (props.folders() ?? []).filter(
      (f) => f.accountId === props.selectedAccountId(),
    );

  return (
    <Stack gap={4}>
      <Panel label="ACCOUNTS" flush>
        <Suspense
          fallback={
            <div class="p-3">
              <LoadingText />
            </div>
          }
        >
          <For each={props.accounts()}>
            {(acc) => (
              <ListRow
                label={acc.name}
                leading="mail"
                selected={acc.id === props.selectedAccountId()}
                onClick={() => props.onAccountSelect(acc)}
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
                selected={folder.id === props.selectedFolderId()}
                onClick={() => props.onFolderSelect(folder)}
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
    </Stack>
  );
}

// ─── Email Inbox Screen ───────────────────────────────────────────────────────

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

  // Compose drawer state
  const [composeOpen, setComposeOpen] = createSignal(false);
  const [composeTo, setComposeTo] = createSignal("");
  const [composeSubject, setComposeSubject] = createSignal("");
  const [composeBody, setComposeBody] = createSignal("");
  const [toError, setToError] = createSignal("");
  const [attachedFiles, setAttachedFiles] = createSignal<string[]>([]);

  // Draft recovery: show banner when drawer closes with non-empty fields
  const [hasDraft, setHasDraft] = createSignal(false);

  // Mobile: sidebar drawer
  const [mobileSidebarOpen, setMobileSidebarOpen] = createSignal(false);

  const hasComposeContent = () =>
    composeTo().trim() !== "" ||
    composeSubject().trim() !== "" ||
    composeBody().trim() !== "";

  function openCompose(to = "", subject = "", body = ""): void {
    setComposeTo(to);
    setComposeSubject(subject);
    setComposeBody(body);
    setToError("");
    setAttachedFiles([]);
    setHasDraft(false);
    setComposeOpen(true);
  }

  function closeCompose(): void {
    if (hasComposeContent()) {
      setHasDraft(true);
    }
    setComposeOpen(false);
  }

  function handleSend(): void {
    const to = composeTo().trim();
    if (!to) {
      setToError("RECIPIENT REQUIRED");
      return;
    }
    if (!EMAIL_RE.test(to)) {
      setToError("INVALID EMAIL ADDRESS");
      return;
    }
    setToError("");
    // Phase-1 mock: simulate a successful send
    setComposeOpen(false);
    setHasDraft(false);
    setComposeTo("");
    setComposeSubject("");
    setComposeBody("");
    setAttachedFiles([]);
    toast.success("MESSAGE SENT");
  }

  // Phase-1 mock: cycle through a set of plausible filenames
  const MOCK_FILES = [
    "report-Q2-2026.pdf",
    "screenshot.png",
    "notes.txt",
    "data-export.csv",
  ];

  function handleAttach(): void {
    const picked = MOCK_FILES[attachedFiles().length % MOCK_FILES.length];
    setAttachedFiles((prev) => [...prev, picked]);
  }

  function removeAttachment(name: string): void {
    setAttachedFiles((prev) => prev.filter((f) => f !== name));
  }

  const filteredMessages = () =>
    (messages() ?? []).filter(
      (m) =>
        m.accountId === selectedAccountId() &&
        m.folderId === selectedFolderId(),
    );

  const selectedMessage = (): EmailMessage | undefined =>
    (messages() ?? []).find((m) => m.id === selectedMessageId());

  const unreadCount = () => filteredMessages().filter((m) => !m.read).length;
  const highUrgencyCount = () =>
    filteredMessages().filter((m) => m.urgency === "high").length;
  const spamCount = () =>
    (messages() ?? []).filter(
      (m) => m.accountId === selectedAccountId() && m.spam,
    ).length;

  const currentAccountAddress = () =>
    accounts()?.find((a) => a.id === selectedAccountId())?.address ?? "—";

  const currentFolderName = () =>
    selectedFolderId().replace(/f-/, "").replace(/-\d$/, "").toUpperCase();

  function handleAccountSelect(acc: EmailAccount): void {
    const firstFolder = (folders() ?? []).find((f) => f.accountId === acc.id);
    setSelectedAccountId(acc.id);
    if (firstFolder) setSelectedFolderId(firstFolder.id);
    setSelectedMessageId(null);
    setMobileSidebarOpen(false);
    toast.info(`ACCOUNT: ${acc.address}`);
  }

  function handleFolderSelect(folder: EmailFolder): void {
    setSelectedFolderId(folder.id);
    setSelectedMessageId(null);
    setMobileSidebarOpen(false);
  }

  return (
    <Stack gap={6}>
      <PageHeader
        title="EMAIL"
        subtitle="Multi-account inbox with AI triage."
        assetId="COMM-MAIL-01.0"
        actions={
          <Row gap={2}>
            {/* Mobile: trigger to open the accounts/folders sidebar in a Drawer */}
            <Button
              variant="ghost"
              leading="mail"
              class="lg:hidden"
              onClick={() => setMobileSidebarOpen(true)}
            >
              ACCOUNTS
            </Button>
            <Button
              variant="primary"
              leading="plus"
              onClick={() => openCompose()}
            >
              COMPOSE
            </Button>
          </Row>
        }
      />

      {/* Draft recovery banner — shown when compose drawer closes with content */}
      <Show when={hasDraft()}>
        <div class="flex items-center gap-3 border border-warn bg-surface px-4 py-2">
          <StatusFlag status="warn">DRAFT SAVED</StatusFlag>
          <Text variant="body" tone="dim" class="flex-1">
            Your unsent message was preserved.
          </Text>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setHasDraft(false);
              setComposeOpen(true);
            }}
          >
            RESUME
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setHasDraft(false);
              setComposeTo("");
              setComposeSubject("");
              setComposeBody("");
              setAttachedFiles([]);
            }}
          >
            DISCARD
          </Button>
        </div>
      </Show>

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
              value: currentAccountAddress(),
            },
            {
              label: "FOLDER",
              value: currentFolderName(),
            },
          ]}
        />
      </Suspense>

      {/* Mobile: accounts/folders slide-in drawer */}
      <Drawer
        open={mobileSidebarOpen()}
        onClose={() => setMobileSidebarOpen(false)}
        title="ACCOUNTS & FOLDERS"
        side="left"
      >
        <AccountFolderRail
          accounts={accounts}
          folders={folders}
          selectedAccountId={selectedAccountId}
          selectedFolderId={selectedFolderId}
          onAccountSelect={handleAccountSelect}
          onFolderSelect={handleFolderSelect}
        />
      </Drawer>

      <div class="flex h-full min-h-0 gap-4">
        {/* Account / Folder rail — desktop only */}
        <aside class="hidden w-48 shrink-0 flex-col gap-4 lg:flex">
          <AccountFolderRail
            accounts={accounts}
            folders={folders}
            selectedAccountId={selectedAccountId}
            selectedFolderId={selectedFolderId}
            onAccountSelect={handleAccountSelect}
            onFolderSelect={handleFolderSelect}
          />
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
                              openCompose(
                                msg().from,
                                `Re: ${msg().subject}`,
                                suggestion.body,
                              );
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
                          openCompose(msg().from, `Re: ${msg().subject}`, "");
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
        onClose={closeCompose}
        title="COMPOSE MESSAGE"
        side="right"
        footer={
          <Row gap={2}>
            <Button variant="ghost" onClick={closeCompose}>
              CANCEL
            </Button>
            <Button variant="primary" leading="send" onClick={handleSend}>
              SEND
            </Button>
          </Row>
        }
      >
        <Stack gap={4}>
          <Input
            label="TO"
            value={composeTo()}
            onInput={(e) => {
              setComposeTo(e.currentTarget.value);
              if (toError()) setToError("");
            }}
            placeholder="recipient@example.com"
            invalid={toError() !== ""}
            hint={toError() || undefined}
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
          <Stack gap={2}>
            <Button
              variant="ghost"
              leading="upload"
              size="sm"
              onClick={handleAttach}
            >
              ATTACH FILE
            </Button>
            <Show when={attachedFiles().length > 0}>
              <Stack gap={1}>
                <For each={attachedFiles()}>
                  {(file) => (
                    <Row gap={2} align="center">
                      <Text variant="micro" tone="dim" class="flex-1 truncate">
                        {file}
                      </Text>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => removeAttachment(file)}
                      >
                        REMOVE
                      </Button>
                    </Row>
                  )}
                </For>
              </Stack>
            </Show>
          </Stack>
        </Stack>
      </Drawer>
    </Stack>
  );
}
