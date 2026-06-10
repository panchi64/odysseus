# 10 — Agent Engine

The agent engine is the autonomous tool-using assistant. Given a conversation and a model, it works toward the user's request over multiple steps — invoking tools, observing results, and continuing — until it has completed the task or determined it cannot, streaming its progress throughout.

---

## AE-1 — Task execution

- **AE-1.1 (MUST).** The agent MUST be able to take multiple sequential steps in a single turn: invoke a tool, observe its result, and decide the next action based on that result.
- **AE-1.2 (MUST).** At each step the agent either continues with another step or reaches a **terminal outcome**: **done** (the request is satisfied and a final answer is given) or **blocked** (the agent cannot proceed and says why). A turn MAY also **pause to await the operator's approval** of a sensitive action (`AE-3`) and resume from there, or be stopped by a bound (`AE-1.5`/`AE-1.6`) or by cancellation. A turn MUST NOT end in any other way — silently or in an indeterminate state.
- **AE-1.3 (MUST).** The agent MUST act on the results of its tool calls — incorporating tool output into its subsequent reasoning and final answer.
- **AE-1.4 (MUST).** Before declaring a task done, the agent MUST check its own work — confirming that each concrete deliverable the user asked for was actually produced — and MUST NOT claim a completion it cannot substantiate. This is the agent's own diligence *within* the turn; the separate, optional system that independently re-judges a finished turn and may retry is `AE-5.2`.
- **AE-1.5 (MUST — performance).** A single turn MUST be bounded by a maximum number of steps so it cannot run unbounded; on reaching the bound the agent MUST stop and report its state.
- **AE-1.6 (SHOULD — performance).** The agent SHOULD support an optional per-turn limit on the number of tool invocations; on reaching it, the agent MUST stop and inform the user.

## AE-2 — Capabilities (tools)

The agent MUST be able to invoke the following categories of tools. Each is a capability the agent can use on the user's behalf; availability is subject to the gating in `AE-3`.

| Category | Capabilities |
|---|---|
| Code & shell | Run code and shell commands in an **isolated sandbox** (on copies of provided files, never the host — `XC-SEC-7`); run a long task in the background and resume when it completes; run a command **on the host** only via a distinct, explicitly-approved tool (`AE-3.4`) |
| Filesystem | Read and write files |
| Web | Search the web; generate images; edit images |
| Documents | Create, replace, edit (find/replace), and suggest changes to documents; manage the document library |
| Memory & history | Store and recall long-term memory; search past conversations |
| Skills | Create, refine, publish, and search reusable skills |
| Notes, tasks, calendar | Manage notes and reminders; manage scheduled tasks; manage calendar events |
| Email | List, read, send, and reply to email |
| Contacts | Resolve a name to a contact; manage contacts |
| Model management | Download, serve, list, and stop models; search and inspect model catalogs; manage serving presets and remote hosts |
| Research | Start a deep-research run; retrieve and manage research results |
| Inter-agent | Converse with another model; create and drive sub-sessions; run a multi-step pipeline |
| Configuration | Manage model endpoints, integrations, webhooks, API tokens, and settings |
| Vault | Search, retrieve, and unlock entries in the password vault |
| Integrations | Call configured third-party APIs |

- **AE-2.1 (MUST).** Each tool MUST present a typed description of its parameters so the model can call it correctly, and MUST validate arguments before acting.
- **AE-2.2 (MUST).** A tool MUST always return a result the agent can act on — including a clear error result on failure. A failing or unknown tool MUST NOT abort the turn.

## AE-3 — Sensitive actions & access control

The system is operated by a single operator, so control is expressed over *actions*, not user tiers: actions that are powerful, externally-visible, or hard to reverse require the operator's explicit approval before they take effect.

- **AE-3.1 (MUST).** A defined set of tools perform **sensitive actions** — running code or commands **on the host**, host filesystem writes, sending email, model download/serve/stop, endpoint/integration/webhook/token/settings configuration, and vault access. The agent MUST NOT complete a sensitive action without the operator's explicit approval of that specific action, presented with what it will do — the action and its concrete arguments — before it takes effect. (**Sandboxed** code execution is deliberately *excluded* from this set: isolated from the host and run only on copies per `XC-SEC-7`, it carries no host-level risk and needs no approval.)
- **AE-3.2 (MUST).** Approval MUST be solicited through a channel appropriate to the run: inline for an interactive run, and through the operator's notification channels for an unattended or scheduled run, which MUST pause awaiting a response rather than proceeding unapproved — except where a scheduling-time pre-authorization already covers the action (`AE-3.5`). A denied action MUST NOT be performed, and the agent MUST be informed of the denial so it can adapt.
- **AE-3.3 (MUST).** The operator MUST be able to disable individual tools; disabled tools MUST NOT be offered to or invoked by the agent.
- **AE-3.4 (MUST).** When the agent requests to run code or commands directly **on the host** (the exceptional non-sandboxed path, `XC-SEC-7`), the approval request MUST include, alongside the exact command, a **plain-language explanation** of what it does and the effect it will have on the host — so the operator can judge the request without having to read the raw command.
- **AE-3.5 (MUST).** When the agent schedules a recurring or unattended task, creating it is itself an approval-gated action: the operator MUST be shown the task before it is created — its trigger, what it will do, and the **specific sensitive actions** (if any) it would perform on its unattended runs. Approving it both creates the task and grants it a **scoped pre-authorization** for exactly those sensitive actions, so its later runs perform them without pausing each time. A run that attempts a sensitive action **outside** the approved scope MUST fall back to pausing and notifying (`AE-3.2`). The operator MUST be able to review and revoke a task's pre-authorization at any time.
- **AE-3.6 (MUST).** Tools that come from outside the system's own catalog — those exposed by registered external tool servers (`MCP-*`) and configured third-party integrations (`INTEG-*`) — are **sensitive by default**, because their effects are not known to the system and may be externally visible. The agent MUST NOT invoke such a tool without approval unless the operator has explicitly marked that specific tool as **trusted**, in which case it is invoked without prompting. Marking a tool trusted is an operator action, never the agent's, and is revocable.

## AE-4 — Tool catalog discipline (performance)

- **AE-4.1 (SHOULD — performance).** To keep model accuracy high, the tool catalog SHOULD be kept lean and coarse-grained — favoring a few action-parameterized tools over many narrow ones — so that a capable native-tool-calling model (`AE-8.1`) can select correctly from the *full* catalog without a runtime relevance filter. Should the catalog ever grow large enough to degrade selection, a relevance pre-filter MAY be introduced, always keeping a core set of general-purpose tools available.
- **AE-4.2 (MUST).** Every tool the agent is permitted to use (`AE-3`) is available to it for the whole turn; in particular, when a document is open the document-editing tools MUST be available.

## AE-5 — Reliability

- **AE-5.1 (MUST).** The agent MUST NOT loop indefinitely. If it repeats the same action without progress, or keeps acting without converging, it MUST stop and either give its best answer or declare itself blocked.
- **AE-5.2 (SHOULD).** The system SHOULD provide a **post-turn verifier**: after a turn that produced a checkable artifact, it judges whether the result genuinely satisfies the request and, if not, makes a **bounded** corrective re-attempt before completion. The verifier MAY be operator-configurable — including disabled, or triggered only for turns that produced an artifact — and MUST be bounded so it cannot retry endlessly. It is the systemic counterpart to the agent's own in-turn diligence (`AE-1.4`). When such a re-attempt succeeds, the recovered procedure MAY be retained as a reusable skill (`SKILL-4`).
- **AE-5.3 (SHOULD).** The agent SHOULD support a prioritized list of model endpoints and fall back to the next on failure. Fallback applies before any answer text has been shown; once output has begun streaming it MUST NOT switch endpoints mid-answer, and a fallback MUST NOT duplicate output the user has already seen.
- **AE-5.4 (SHOULD — performance).** When the conversation approaches the model's context limit, the agent SHOULD reduce older context to stay within budget while preserving the active task and any open document. Reduction MAY drop or condense older turns; whichever is used, the active request MUST remain intact.

## AE-6 — Streaming output

- **AE-6.1 (MUST).** The agent MUST stream its activity to the client as it happens, conveying at least: incremental answer text; the start, progress, and result of each tool invocation; live progress for long-running tools (elapsed time and partial output before the tool returns); step boundaries; document creation/streaming/updates; cited web sources; budget-limit notices; final run metrics; errors; and an explicit end-of-turn signal.
- **AE-6.2 (MUST).** Document content generated by the agent MUST stream into the document view as it is produced, then be committed as a new version.
- **AE-6.3 (MUST).** Reasoning/"thinking" output MUST be distinguishable from the final answer so the client can present it separately.
- **AE-6.4 (SHOULD).** When the agent emits a substantial block of code or document-like content directly into the conversation without using a document tool, the system SHOULD promote it into a document automatically rather than leaving it inline.

## AE-7 — Continuity

- **AE-7.1 (MUST).** A run MUST continue if the client disconnects, and a reconnecting client MUST be able to rejoin the run and receive the output it missed, for as long as the server process stays up. Continuity is not required to survive a restart of the server itself.

## AE-8 — Model requirements

- **AE-8.1 (MUST).** The agent supports models that provide native tool-calling. Models without this capability are out of scope.
