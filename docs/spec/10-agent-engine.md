# 10 — Agent Engine

The agent engine is the autonomous tool-using assistant. Given a conversation and a model, it works toward the user's request over multiple steps — invoking tools, observing results, and continuing — until it has completed the task or determined it cannot, streaming its progress throughout.

---

## AE-1 — Task execution

- **AE-1.1 (MUST).** The agent MUST be able to take multiple sequential steps in a single turn: invoke a tool, observe its result, and decide the next action based on that result.
- **AE-1.2 (MUST).** A turn MUST end in exactly one of three states: **done** (the request is satisfied and a final answer is given), **blocked** (the agent cannot proceed and says why), or it continues with another step.
- **AE-1.3 (MUST).** The agent MUST act on the results of its tool calls — incorporating tool output into its subsequent reasoning and final answer.
- **AE-1.4 (MUST).** Before declaring a task done, the agent MUST confirm that each concrete deliverable the user asked for was actually produced.
- **AE-1.5 (MUST — performance).** A single turn MUST be bounded by a maximum number of steps so it cannot run unbounded; on reaching the bound the agent MUST stop and report its state.
- **AE-1.6 (SHOULD — performance).** The agent SHOULD support an optional per-turn limit on the number of tool invocations; on reaching it, the agent MUST stop and inform the user.

## AE-2 — Capabilities (tools)

The agent MUST be able to invoke the following categories of tools. Each is a capability the agent can use on the user's behalf; availability is subject to the gating in `AE-3`.

| Category | Capabilities |
|---|---|
| Code & shell | Run shell commands; run Python; run a long task in the background and resume when it completes |
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
| Inter-agent | Converse with another model; create and drive sub-sessions; run a multi-step pipeline; control the UI |
| Configuration | Manage model endpoints, integrations, webhooks, API tokens, and settings |
| Vault | Search, retrieve, and unlock entries in the password vault |
| Integrations | Call configured third-party APIs |

- **AE-2.1 (MUST).** Each tool MUST present a typed description of its parameters so the model can call it correctly, and MUST validate arguments before acting.
- **AE-2.2 (MUST).** A tool MUST always return a result the agent can act on — including a clear error result on failure. A failing or unknown tool MUST NOT abort the turn.

## AE-3 — Access control

- **AE-3.1 (MUST).** A defined set of privileged tools — shell and code execution, filesystem access, email, contacts, memory, scheduling, model serving, configuration, and vault — MUST be unavailable to non-administrator users.
- **AE-3.2 (MUST).** A further subset — model-endpoint, integration, webhook, token, and settings management, and model download/serve/stop — MUST be restricted to administrators specifically.
- **AE-3.3 (MUST).** The user MUST be able to disable individual tools; disabled tools MUST NOT be offered to or invoked by the agent.

## AE-4 — Tool relevance (performance)

- **AE-4.1 (SHOULD — performance).** To keep latency low and model accuracy high, the agent SHOULD present only the tools relevant to the current request rather than the entire catalog, while always keeping a small core set of general-purpose tools available.
- **AE-4.2 (MUST).** When a document is open, the document-editing tools MUST be available regardless of relevance selection.

## AE-5 — Reliability

- **AE-5.1 (MUST).** The agent MUST NOT loop indefinitely. If it repeats the same action without progress, or keeps acting without converging, it MUST stop and either give its best answer or declare itself blocked.
- **AE-5.2 (SHOULD).** After performing actions that produce a checkable artifact, the agent SHOULD verify the result genuinely satisfies the request before declaring completion, and continue working if it does not. This MAY be operator-configurable and MUST be bounded so it cannot retry endlessly.
- **AE-5.3 (SHOULD).** The agent SHOULD support a prioritized list of model endpoints and fall back to the next on failure. Fallback applies before any answer text has been shown; once output has begun streaming it MUST NOT switch endpoints mid-answer, and a fallback MUST NOT duplicate output the user has already seen.
- **AE-5.4 (SHOULD — performance).** When the conversation approaches the model's context limit, the agent SHOULD reduce older context to stay within budget while preserving the active task and any open document. Reduction MAY drop or condense older turns; whichever is used, the active request MUST remain intact.
- **AE-5.5 (MAY).** After a turn, the system MAY judge whether the task truly succeeded and, if it did not, make a further corrective attempt automatically. A successful recovery MAY be retained as a reusable procedure for similar future tasks. Any such re-attempt MUST be bounded so it cannot retry endlessly.

## AE-6 — Streaming output

- **AE-6.1 (MUST).** The agent MUST stream its activity to the client as it happens, conveying at least: incremental answer text; the start, progress, and result of each tool invocation; live progress for long-running tools (elapsed time and partial output before the tool returns); step boundaries; document creation/streaming/updates; cited web sources; budget-limit notices; final run metrics; errors; and an explicit end-of-turn signal.
- **AE-6.2 (MUST).** Document content generated by the agent MUST stream into the document view as it is produced, then be committed as a new version.
- **AE-6.4 (SHOULD).** When the agent emits a substantial block of code or document-like content directly into the conversation without using a document tool, the system SHOULD promote it into a document automatically rather than leaving it inline.
- **AE-6.3 (MUST).** Reasoning/"thinking" output MUST be distinguishable from the final answer so the client can present it separately.

## AE-7 — Continuity

- **AE-7.1 (MUST).** A run MUST continue if the client disconnects, and a reconnecting client MUST be able to rejoin the run and receive the output it missed, for as long as the server process stays up. Continuity is not required to survive a restart of the server itself.

## AE-8 — Model requirements

- **AE-8.1 (MUST).** The agent supports models that provide native tool-calling. Models without this capability are out of scope.
