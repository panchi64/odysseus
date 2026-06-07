import type {
  EmailAccount,
  EmailFolder,
  EmailMessage,
  ReplySuggestion,
} from "./model";

export const mockAccounts: EmailAccount[] = [
  {
    id: "acc-1",
    name: "Personal",
    address: "personal@franciscocasiano.com",
    provider: "IMAP",
  },
  {
    id: "acc-2",
    name: "Work",
    address: "francisco@company.dev",
    provider: "SMTP/IMAP",
  },
];

export const mockFolders: EmailFolder[] = [
  { id: "f-inbox-1", accountId: "acc-1", name: "INBOX", count: 7 },
  { id: "f-sent-1", accountId: "acc-1", name: "SENT", count: 0 },
  { id: "f-archive-1", accountId: "acc-1", name: "ARCHIVE", count: 0 },
  { id: "f-spam-1", accountId: "acc-1", name: "SPAM", count: 2 },
  { id: "f-inbox-2", accountId: "acc-2", name: "INBOX", count: 12 },
  { id: "f-sent-2", accountId: "acc-2", name: "SENT", count: 0 },
];

export const mockMessages: EmailMessage[] = [
  {
    id: "msg-1",
    accountId: "acc-1",
    folderId: "f-inbox-1",
    from: "noreply@github.com",
    fromName: "GitHub",
    to: ["personal@franciscocasiano.com"],
    subject: "[odysseus] Security alert: new sign-in detected",
    snippet:
      "We noticed a new sign-in to your account from an unrecognized device...",
    body: "We noticed a new sign-in to your account from an unrecognized device.\n\nDevice: MacBook Pro (Monterey)\nLocation: San Francisco, CA\nTime: 2026-06-07 09:14 UTC\n\nIf this was you, no action is needed. If you don't recognize this sign-in, please review your account security settings immediately.",
    receivedAt: "2026-06-07T09:14:00Z",
    read: false,
    urgency: "high",
    tags: ["security", "github"],
    spam: false,
    summary:
      "GitHub detected a new sign-in from an unrecognized MacBook Pro in San Francisco.",
  },
  {
    id: "msg-2",
    accountId: "acc-1",
    folderId: "f-inbox-1",
    from: "alex@collaborator.dev",
    fromName: "Alex Rivera",
    to: ["personal@franciscocasiano.com"],
    subject: "Re: Pydantic AI migration — need your input on agent loop design",
    snippet:
      "Hey Francisco, I reviewed the spec you sent over. The deferred rebuild approach makes sense...",
    body: "Hey Francisco,\n\nI reviewed the spec you sent over. The deferred rebuild approach makes sense given the timeline constraints. A few thoughts:\n\n1. The tool registry abstraction looks solid — worth keeping the interface stable even if the internals change.\n2. For the streaming integration, I'd suggest wrapping the pydantic-ai RunContext rather than subclassing. Easier to mock in tests.\n3. The memory persistence layer might benefit from a WAL-mode SQLite write path for the agent loop state.\n\nLet me know if you want to pair on the session manager piece next week.\n\n— Alex",
    receivedAt: "2026-06-07T11:32:00Z",
    read: false,
    urgency: "normal",
    tags: ["engineering", "pydantic-ai"],
    spam: false,
    summary:
      "Alex reviewed the Pydantic AI migration spec and suggests wrapping RunContext instead of subclassing for easier test mocking.",
  },
  {
    id: "msg-3",
    accountId: "acc-1",
    folderId: "f-inbox-1",
    from: "billing@hetzner.com",
    fromName: "Hetzner Cloud",
    to: ["personal@franciscocasiano.com"],
    subject: "Invoice #HC-2026-06 — EUR 12.40 due",
    snippet:
      "Your invoice for June 2026 is available. Amount due: EUR 12.40...",
    body: "Dear customer,\n\nYour invoice for the billing period June 2026 is now available.\n\nAmount due: EUR 12.40\nDue date: 2026-06-15\nPayment method: Visa ending in 4242\n\nServices:\n- CX21 server (4 vCPU, 8 GB RAM) × 30 days: EUR 9.40\n- 20 TB bandwidth overage: EUR 3.00\n\nThe charge will be applied automatically.",
    receivedAt: "2026-06-07T08:00:00Z",
    read: true,
    urgency: "low",
    tags: ["billing", "infra"],
    spam: false,
    summary:
      "EUR 12.40 invoice for Hetzner Cloud June 2026 — CX21 server + 20 TB bandwidth overage.",
  },
  {
    id: "msg-4",
    accountId: "acc-1",
    folderId: "f-inbox-1",
    from: "newsletter@tldr.tech",
    fromName: "TLDR Tech",
    to: ["personal@franciscocasiano.com"],
    subject: "TLDR 2026-06-07: OpenAI o4-mini benchmarks, Rust async rework...",
    snippet:
      "Today's top stories: o4-mini math reasoning now outperforms o3 on AIME...",
    body: "TLDR Tech — 2026-06-07\n\n• OpenAI o4-mini math reasoning benchmarks show it outperforms o3 on AIME and MATH-500 at 60% lower cost.\n• Rust async rework proposal lands in nightly — new keyword `gen` for coroutine syntax.\n• Cloudflare Workers now support WASM 64-bit addressing for models up to 4 GB.\n• PostgreSQL 18 beta 2 released with incremental sort improvements.\n• Anthropic releases Claude 4 system card with extended thinking metrics.",
    receivedAt: "2026-06-07T06:00:00Z",
    read: true,
    urgency: "low",
    tags: ["newsletter"],
    spam: false,
    summary:
      "Daily tech digest: o4-mini benchmarks, Rust async rework, Cloudflare WASM 64-bit, Postgres 18 beta 2.",
  },
  {
    id: "msg-5",
    accountId: "acc-2",
    folderId: "f-inbox-2",
    from: "pm@company.dev",
    fromName: "Sarah Okonkwo",
    to: ["francisco@company.dev"],
    subject: "Sprint 24 planning — items for discussion",
    snippet:
      "Hi Francisco, attaching the draft sprint items for review before Thursday's call...",
    body: "Hi Francisco,\n\nAttaching the draft sprint items for review before Thursday's planning call at 14:00 UTC.\n\nKey discussion points:\n1. API rate limiter rollout — final sign-off needed\n2. Dashboard telemetry gaps — how many story points?\n3. Mobile baseline audit — should this be in sprint 24 or 25?\n\nPlease add comments in the doc by EOD Wednesday.\n\nThanks,\nSarah",
    receivedAt: "2026-06-07T13:15:00Z",
    read: false,
    urgency: "normal",
    tags: ["work", "planning"],
    spam: false,
    summary:
      "Sarah asks for review of sprint 24 items: API rate limiter, telemetry gaps, mobile audit — feedback due Wednesday.",
  },
  {
    id: "msg-6",
    accountId: "acc-2",
    folderId: "f-inbox-2",
    from: "alerts@pagerduty.com",
    fromName: "PagerDuty",
    to: ["francisco@company.dev"],
    subject: "[RESOLVED] P2 — Elevated error rate on /api/v2/chat endpoint",
    snippet: "RESOLVED: The incident has been resolved. Duration: 8m 42s...",
    body: "RESOLVED: The incident has been resolved.\n\nService: API Gateway — /api/v2/chat\nSeverity: P2\nDuration: 8m 42s\nError rate peak: 12.4% (threshold: 5%)\nRoot cause: Downstream LLM provider timeout spike\nResolution: Traffic rerouted to secondary provider\n\nPost-mortem scheduled for 2026-06-08 10:00 UTC.",
    receivedAt: "2026-06-07T07:43:00Z",
    read: true,
    urgency: "normal",
    tags: ["ops", "incident"],
    spam: false,
    summary:
      "P2 incident resolved: 8m 42s elevated error rate on /api/v2/chat due to LLM provider timeout, rerouted to secondary.",
  },
];

export const mockReplySuggestions: ReplySuggestion[] = [
  {
    id: "rs-1",
    label: "ACKNOWLEDGE",
    body: "Thanks for the heads-up. I'll take a look and follow up shortly.",
  },
  {
    id: "rs-2",
    label: "SCHEDULE CALL",
    body: "Happy to discuss further — does Thursday at 15:00 UTC work for you?",
  },
  {
    id: "rs-3",
    label: "DECLINE",
    body: "Appreciate you reaching out, but I won't be able to take this on right now.",
  },
];
