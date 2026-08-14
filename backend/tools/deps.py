"""RunDeps — the per-run dependency object the agent hands to its tools.

Lives in ``tools/`` because it is the agent↔tools contract and ``tools`` sits
below ``agent`` in the dependency order (agent → tools → services → core), so
both layers import it without a cycle. It becomes ``RunContext.deps`` inside
Pydantic AI: a tool reaches the Run (to emit its own ``tool.progress`` events),
the owner, and the per-run enabled-tool policy through it — never via globals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from runs import Run

if TYPE_CHECKING:
    from services.approval_grants import ApprovalGrantStore
    from services.artifacts import ArtifactStore
    from services.calendar import CalendarService
    from services.conversation_search import ConversationSearch
    from services.corpus import CorpusIndex
    from services.documents import DocumentStore
    from services.external_tools import ExternalTools
    from services.mail import MailService
    from services.memory import MemoryStore
    from services.notifications import NotificationService
    from services.sandbox import SandboxSessionManager
    from services.search import SearchService
    from services.secret_vault import SecretVaultService
    from services.skills import SkillStore
    from services.uploads import UploadStore
    from services.webfetch import BrowserFetcher
    from services.workspace_history import WorkspaceHistoryStore


@dataclass(frozen=True)
class Capabilities:
    """The capability handles an orchestrator hands a run's tools, bundled so a new
    capability is one field here — not a new parameter on every engine function and
    call site. Per-turn context (the conversation id) stays separate; the engine
    unpacks these into each turn's :class:`RunDeps`."""

    memory: MemoryStore | None = None
    sandbox_sessions: SandboxSessionManager | None = None
    artifacts: ArtifactStore | None = None
    search: SearchService | None = None
    fetcher: BrowserFetcher | None = None
    conversation_search: ConversationSearch | None = None
    corpus: CorpusIndex | None = None
    # The upload store, so a tool can fetch a chat attachment's bytes by id (the
    # attachments tool stages them into the sandbox). None ⇒ that tool degrades.
    uploads: UploadStore | None = None
    # Conversation-scoped tool auto-approval grants. The engine consults this to
    # auto-approve a deferred tool the operator allowed for the conversation; None
    # ⇒ every deferred call falls back to strict per-call approval.
    grants: ApprovalGrantStore | None = None
    # The View's git-style history. The engine snapshots the sandbox workspace here
    # after a file-changing turn; None ⇒ no history is captured (graceful).
    workspace_history: WorkspaceHistoryStore | None = None
    # The document library — lets the document tool create/edit versioned documents that
    # surface live in the chat View. None ⇒ the document tool degrades.
    documents: DocumentStore | None = None
    # The skill library (SKILL-1..3). Backs both the per-turn published-skill catalog the
    # engine injects and the `skills` toolset. None ⇒ no catalog is injected and the skill
    # tools degrade.
    skills: SkillStore | None = None
    # The attention/notification surface. The engine calls this when a run parks
    # awaiting approval (an ALWAYS-notify per the emit policy) and defensively at a
    # grant short-circuit (idempotent — resolves any notification a prior park left
    # pending). None ⇒ approval parks simply don't notify (graceful degradation, never
    # blocks the turn).
    notifications: NotificationService | None = None
    # --- Reserved sprint capabilities ---------------------------------------------
    # Declared up front so the parallel feature tracks don't each have to add a field
    # here and at every construction site. Both call sites already forward whatever is
    # on ``app.state`` under the matching name, so a track only has to hang its service
    # there — it never edits this file, the engine, `routes/chat.py`, or `app.py`.
    # Typed loosely because the concrete services don't exist yet; each track narrows
    # its own line to the real type when it lands (distinct lines ⇒ no conflicts).
    # The mail capability (`EMAIL-1..4`) — lets the mail toolset list/read/send the
    # operator's email. None ⇒ the mail tools report email is unavailable.
    mail: MailService | None = None
    # The calendar (`CAL-1..3`). Natural-language event entry rides on the service as
    # `.nl`, so the capability stays one handle. None ⇒ the calendar tools say so.
    calendar: CalendarService | None = None
    # The operator's secrets manager (VAULT-1). Every tool that reaches it is
    # approval-gated (VAULT-2); the service enforces its own lock on top. None ⇒ the vault
    # tools report the capability absent.
    secret_vault: SecretVaultService | None = None
    # MCP servers + configured connectors + the per-tool trust policy they share, as one
    # handle (`MCP-*`, `INTEG-*`, `AE-3.6`). None ⇒ the `external` category is empty.
    external: ExternalTools | None = None


@dataclass
class CompactionContext:
    """Per-run tool-result compaction state, reached by both the history processor (which
    fills it) and the ``expand_tool_result`` tool (which reads it). Lives here in ``tools/``
    because it is part of the deps contract; the processor that drives it lives in ``agent/``.

    ``enabled``/``keep_recent``/``min_tokens`` are the resolved effective config for the turn
    (operator default, or a per-conversation override). ``protect_from`` is the turn's
    persistence index — messages at or after it are the current turn (never compacted, since
    they are exactly what the engine persists); only earlier messages are eligible. The engine
    sets it once the conversation history length is known; 0 ⇒ nothing is prior (a safe no-op).
    ``full_by_id`` maps a compacted tool call's id → its original, full content, so the
    rehydration tool can return it verbatim — populated by the processor, which always sees the
    full DB history before condensing it."""

    enabled: bool = False
    keep_recent: int = 6
    min_tokens: int = 0
    protect_from: int = 0
    full_by_id: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunDeps:
    run: Run
    owner_id: str
    # Operator-disabled tools, by namespaced name. Empty ⇒ all enabled.
    disabled_tools: frozenset[str] = field(default_factory=frozenset)
    # Capability handles the tools reach (never via globals). More land here as
    # their services do (search, the open document, …).
    memory: MemoryStore | None = None
    # The execution sandbox, as a per-conversation session manager. None ⇒ no
    # runtime available, so code execution is disabled and its tool says so (it
    # never falls back to the host). The code tool keys a live session by the
    # conversation, falling back to the run id for a stateless (no-conversation) run.
    sandbox_sessions: SandboxSessionManager | None = None
    conversation_id: str | None = None
    # Where the agent's published previews are captured (the `preview` tool reads a
    # sandbox file and hands its bytes here). None ⇒ previews unavailable.
    artifacts: ArtifactStore | None = None
    # Web search over the configured provider. None ⇒ the search tool says so.
    search: SearchService | None = None
    # Web fetch — render a page in a headless browser + extract to Markdown. None ⇒ the
    # fetch tool says so (e.g. the Chromium binary is absent).
    fetcher: BrowserFetcher | None = None
    # Cross-chat search over the operator's other conversations. None ⇒ the
    # conversation tools say so (graceful degradation).
    conversation_search: ConversationSearch | None = None
    # The unified knowledge corpus (folders + memory + conversations as sources).
    # None ⇒ the corpus tool says so.
    corpus: CorpusIndex | None = None
    # The upload store — lets the attachments tool fetch a file's bytes by id and
    # stage them into the conversation's sandbox. None ⇒ the tool degrades.
    uploads: UploadStore | None = None
    # The View's git-style version history. A `view_show` captures the sandbox
    # workspace here as a new version, stamped with how it previews. None ⇒ the view
    # tool degrades (no versioned history).
    workspace_history: WorkspaceHistoryStore | None = None
    # The document library — the document tool creates/edits versioned documents that
    # stream into the chat View. None ⇒ the document tool degrades.
    documents: DocumentStore | None = None
    # The skill library (SKILL-1..3) — `skills_open` reads a published skill and stages its
    # bundle into the sandbox; the engine reads the catalog from it each turn. None ⇒ the
    # skill tools degrade and no catalog is injected.
    skills: SkillStore | None = None
    # Tool-result compaction state for this turn — the history processor fills its handle
    # map; the `expand_tool_result` tool reads it. None ⇒ compaction is off for the run.
    compaction: CompactionContext | None = None
    # --- Reserved sprint capabilities ---------------------------------------------
    # The tools-side half of the reserved handles on :class:`Capabilities` above; the
    # engine unpacks them here for every turn. None ⇒ that track hasn't landed (or its
    # service is unavailable), so its tools degrade with an "unavailable" result rather
    # than failing the turn — the same contract every other capability here follows.
    # The mail capability (`EMAIL-1..4`) — the mail toolset lists/reads/sends through it.
    # None ⇒ the mail tools report that email is unavailable.
    mail: MailService | None = None
    # The calendar (`CAL-1..3`) — the calendar tools read/write the operator's schedule
    # through it, and reach natural-language entry as `calendar.nl`. None ⇒ they degrade.
    calendar: CalendarService | None = None
    # The operator's secrets manager — read by the approval-gated `vault` tools (VAULT-2),
    # which still meet the vault's own lock behind the approval. None ⇒ they report the
    # capability absent.
    secret_vault: SecretVaultService | None = None
    # The external-tool capability (see :class:`Capabilities` above). None ⇒ the
    # `external` category composes to nothing, so no external tool is offered at all.
    external: ExternalTools | None = None

    @property
    def sandbox_key(self) -> str:
        """The key a conversation's sandbox session and its artifacts share — the
        conversation when there is one, else the run (a stateless turn). Defined
        once so the code and preview tools can never key them differently."""
        return self.conversation_id or self.run.id
