# 40 — Tools & Toolsets

> **Detail for Pillar III (the engine's reach).** This expands §2 / §3-pillar-III of the [architecture README](./README.md): how the agent's tools are defined, *which* tools a given run sees, and how the spec's whole access-control story (`AE-2`, `AE-3`) becomes **composition of Pydantic AI primitives keyed on per-run dependencies** rather than bespoke machinery. Decisions behind the calls: **D3** (no relevance layer), **D14** (single-operator gating), **D20** (approval), **D23** (code isolation), **D24** (scheduled pre-auth), **D25** (external-tool gating).

---

## 1. The one idea

**A tool is a thin adapter; the catalog the model sees is a policy.** Two ideas, kept apart:

- **What a tool *is*** — a typed function the model can call. It owns *no* logic: it validates args (Pydantic AI does this), reaches a capability through `RunContext.deps`, and shapes the result. The actual work lives in `services/`, where a REST route or the research pipeline reaches the same capability directly. A tool is the model's *doorway* to a capability, never the capability itself.
- **What the model *sees*** — not the raw catalog, but the catalog **after our access policy runs**: namespaced, operator-disabled tools dropped, sensitivity attached. That policy is a short **stack of toolset wrappers** evaluated against the run's deps. It is the single most leveraged mapping in the design.

Everything below is those two ideas worked out.

---

## 2. Tools are adapters over capabilities

A tool lives in `tools/`, grouped by `AE-2` category, and stays thin by construction:

```python
# tools/memory.py — the whole tool. No MEM-* logic here; it lives in services/memory.
@toolset.tool
async def recall(ctx: RunContext[RunDeps], query: str, limit: int = 5) -> list[dict]:
    """Recall relevant memories by meaning (with keyword fallback)."""
    store = ctx.deps.memory
    if store is None:                      # capability absent → say so, don't fail (XC-DEG-*)
        return [{"error": "Memory is unavailable."}]
    hits = await store.recall(ctx.deps.owner_id, query, limit=limit)
    return [{"content": h.memory.content, "matched_by": h.matched_by} for h in hits]
```

Three properties fall out of this shape and are non-negotiable:

| Property | Why it holds | Requirement |
|---|---|---|
| **Logic never hides in a tool.** | The `MemoryStore` is the one implementation; the tool, the `/memory/*` route, and any pipeline all call it. One source of truth, three callers. | README §3-pillar-III |
| **Capabilities degrade, tools report.** | A tool reads its capability handle off `deps`; `None` means the service isn't wired, and the tool returns a plain message the model adapts to — never an exception, never a hang. | `XC-DEG-*` |
| **Tools reach the run, not globals.** | `ctx.deps` carries the `Run`, the `owner_id`, and capability handles. A slow tool emits its own `tool.progress` (elapsed + partial output) through `deps.run`. Nothing is reached through module state. | `AE-6.1` |

### `RunDeps` — the keyed context every tool receives

`RunDeps` *is* the agent↔tools contract. It lives in `tools/deps.py` (below `agent/`, above `services/`, so both import it without a cycle) and becomes `RunContext.deps` inside Pydantic AI:

```python
@dataclass
class RunDeps:
    run: Run                                       # emit tool.progress; honor cancellation
    owner_id: str                                  # the ownership seam (D14)
    disabled_tools: frozenset[str] = frozenset()   # operator's enable/disable policy (AE-3.3)
    memory: MemoryStore | None = None              # capability handles — more land as services do
    sandbox: Sandbox | None = None                 # None ⇒ code-exec disabled, never host fallback
```

The deps object is assembled once per run by the orchestrator (`agent/engine.py`) and is the *only* thing the gating stack and the tools are keyed on. New capabilities land as new fields here, never as imports inside a tool.

---

## 3. The toolset stack — *which* tools a run sees

`AE-2` says tools are grouped into categories. `AE-3` says access is governed by **sensitivity** and by the operator's **enable/disable** choice. `AE-4` says the model picks its own tools from what it's offered. All three are realized by composing Pydantic AI toolset wrappers — `build_agent_toolsets()` is the whole policy:

```python
# tools/toolsets.py — the entire access policy, as built.
def build_agent_toolsets(categories=None) -> list[AbstractToolset[RunDeps]]:
    cats = dict(categories) if categories is not None else default_categories()
    prefixed  = [ts.prefixed(name) for name, ts in cats.items()]   # stable category_tool names
    combined  = CombinedToolset(prefixed)                          # one catalog, all categories
    return [combined.filtered(_enabled_gate)]                      # drop operator-disabled tools
```

Read as a pipeline, against the README's idealized stack:

```
CombinedToolset(builtin + memory + code + … MCP/integrations as they land)
  → .prefixed(category)        #              stable "category_tool" names           (AE-2.x)
  → .filtered(enabled_gate)    # AE-3.3       drop operator-disabled tools
  # no privilege gate          — single operator, no tiers (D14): there is no tier to filter on
  # no relevance pre-filter    — D3: a capable native-tool-call model discerns from the full
  #                              gated catalog; AE-4.2 is trivially met (every tool always present).
  #                              A .prepared() relevance step can slot in HERE if the catalog ever
  #                              outgrows what one prompt should carry — the seam is reserved.
```

Two deliberate omissions, each a settled decision rather than an oversight:

- **No privilege gate (D14).** The spec's README §2 stack shows a `privilege_gate` first. With a single operator there are **no tiers**, so there is nothing to filter on — the line is intentionally absent. The `owner_id` seam carries the *future* multi-user story; when a second human exists, a `.filtered(privilege_gate)` slots in ahead of the enabled gate, keyed on the same deps. The shape is ready; the filter is empty today.
- **No relevance pre-filter (D3).** `AE-4.1` (pre-select likely-relevant tools) is a waivable SHOULD-performance. On one powerful host with native-tool-call models, the model selects its own tools from the full gated catalog; pre-filtering would add latency and a place to be wrong. `AE-4.2` ("every permitted tool reachable") is then trivially satisfied. The `.prepared()` seam is reserved for if/when the catalog grows past what one context should hold.

### The category catalog

`default_categories()` is where the catalog grows — one entry per cluster, each a `FunctionToolset`:

| Category | Tools (today) | Backing capability | Status |
|---|---|---|---|
| `builtin` | `now` | — (starter category so the stack has something to compose) | ✅ built |
| `memory` | `remember`, `recall` | `services/memory` (hybrid recall, `MEM-*`) | ✅ built |
| `code` | `execute_code`, `run_host_command` | `services/sandbox` (`XC-SEC-7`) | ✅ built |
| `search`, `mail`, `documents`, … | — | land with their `services/` capability | ⬜ pending |
| MCP servers, integrations | — | external (`MCP-*`, `INTEG-*`) | ⬜ pending (gating designed — §4.4) |

Naming is `category_tool` (the `.prefixed(name)` step), so `recall` is offered as `memory_recall` — stable, collision-free names the operator's enable/disable list and the event stream both reference.

---

## 4. Sensitivity & gating — the four-decision story

`AE-3` divides tools by **sensitivity**: powerful or hard-to-reverse capabilities (host execution, host fs-write, email-send, model serve/stop, config, vault, *and* externally-registered tools) are **approval-gated when the agent invokes them**. Crucially, **gating is not a filter in the stack above** — a sensitive tool is *present* in the catalog; it simply **pauses for the operator before it executes**. That pause is one mechanism (D20) that four decisions build on.

### 4.1 D20 — approval via Pydantic AI deferred tools (the base mechanism)

A sensitive tool is marked `requires_approval=True` (or raises `ApprovalRequired` for *conditional* sensitivity, e.g. a write to a protected path). The flow, split clean down the chassis/engine line:

```
model requests a sensitive tool
  → Pydantic AI ends the turn with DeferredToolRequests   ← it did the agentic work,
      (tool name + VALIDATED args + tool_call_id)            and pointedly did NOT execute
  → WE park the Run: status → awaiting_input
  → WE emit  approval.required  (human-readable action + args [+ explanation])
  → WE notify on the right channel (inline | push/email for an unattended run)
  → WE hold the serialized message history as a ParkedTurn on the run
        … run survives client disconnect, indefinitely (AE-7) …
  → operator decides:  POST /runs/{id}/approve
  → WE resume with DeferredToolResults(approvals={id: ToolApproved() | ToolDenied(message)})
        ToolApproved may carry override_args; ToolDenied.message is shown to the model so it adapts
```

As built (`agent/engine.py`): the `Agent`'s `output_type` is `[str, DeferredToolRequests]`, so a turn either finishes with text or returns pending approvals. `_park_for_approval()` stashes a `ParkedTurn` (the agent, the message history, the requests, any pending correction-drop range) on `run.parked_payload`; `build_resume_orchestrator()` consumes it and feeds the operator's decisions back in. **Pydantic AI decides *what* needs approval and *exactly what it would do*; we own *parking, notifying, waiting, resuming*.** Because the parked state is just serialized history + pending requests, it survives disconnect for free and can outlive the connection entirely for unattended runs.

> The frozen v1 event protocol (D15) carries `approval.required`. D23 added an **optional `explanation`** field to it for the host-exec case — additive, no version bump.

### 4.2 D23 — code execution is isolated, not merely gated

Approval is **consent, not containment**: a misjudged click, a destructive command dressed up as benign, or injection that *manufactures* a plausible approval request all land on the real host if approval is the only line. So code execution gets a structural boundary *underneath* the gate. This is why `code` is **two tools, cleanly split** (`tools/code.py`):

| | `execute_code` | `run_host_command` |
|---|---|---|
| Runs on | the **host-isolated sandbox** (`services/sandbox`) | the **real host** |
| Approval | **none** — contained ⇒ no host risk ⇒ the agent computes freely | **`requires_approval=True`** (deferred, D20) |
| Extra contract | — | a plain-language **`explanation`** arg, shown to the operator, describing what it does and its effect on the host (`AE-3.4`) |
| If capability absent | returns "code execution is unavailable" — the model adapts | n/a |

The inversion is the point: **routine code-exec loses its approval friction entirely** (it's safe by construction), and the *only* approval prompt is the genuinely dangerous host escape hatch, where the operator reads an explanation rather than a raw command.

**The sandbox invariant** (`services/sandbox/base.py`): every agent-invoked execution sees only **copies** of files explicitly handed in (`SandboxSpec.files`), cannot touch the host filesystem / processes / environment, and has **network egress off by default** (so copied data can't leak). Outputs return explicitly (stdout/stderr + copied-out files); nothing escapes as a side effect. The backend is **pluggable** (`Sandbox` ABC; default `ContainerSandbox` over Docker/Podman — portable per `XC-PORT-1`) and **fails closed**: `detect_sandbox()` returns `None` when no runtime is present, `RunDeps.sandbox` is then `None`, and `execute_code` reports the capability disabled. **It MUST NOT silently fall back to the host** (`XC-DEG-*`). The operator's own terminal (`SHELL-*`) is unchanged and **agent-unreachable** — the agent's sole path to the host is the explained-approval tool.

### 4.3 D24 — pre-authorized scheduled tasks ⬜ *designed, not built*

Strict per-run approval (`AE-3.2`) would make a recurring task that touches a sensitive action **park every single run** — defeating unattended automation. Resolution: **the scheduling tool is itself a deferred/approval tool**. When the agent schedules a task, the Run parks and surfaces *the task* — its trigger, intended actions, and the specific sensitive actions it would perform — and approval grants a **scoped pre-authorization** stored with the task.

- **At each unattended run:** a sensitive action **within** the pre-authorized scope is auto-satisfied (the deferred result is supplied as approved) without re-parking; an action **outside** scope falls back to pause-and-notify (`AE-3.2`).
- **Scope, not a blank cheque:** the grant is over a *declared scope* (`may send email to these recipients`, `may run sandboxed code`, `may not run host code`), checked at runtime. Free-form tasks approve the *bounds*; runtime actions are matched against them.
- **Revocable & visible:** the operator can review and revoke any task's pre-authorization, returning it to strict per-run approval. Reuses D13 (scheduler materializes tasks as Runs) + D20 (deferred-tool approval) — no new machinery.

Lands with `TASK-*`.

### 4.4 D25 — external tools (MCP / integrations) sensitive by default ⬜ *designed, not built*

The `AE-3` sensitivity model rests on a *known* list (shell, email, vault…). Tools from registered MCP servers and configured integrations are the **unknown** case it can't enumerate — arbitrary, possibly externally-visible effects. So they are **approval-gated by default**, and the operator opts *specific* tools into **trusted** (auto-approve) status:

- In the toolset stack, external tools carry a default *sensitive* marking and ride the same deferred-tool path as D20.
- A **trusted-tool allowlist** (operator-managed, persisted in encrypted settings) flips specific tools to auto-approve.
- **Enable/disable (`AE-3.3`) is orthogonal and still applies** — the `_enabled_gate` runs regardless of trust.

Consistent with the whole posture: unknowns are contained until the operator deliberately, per-tool, relaxes them — never the agent. Lands with `MCP-*` / `INTEG-*`.

---

## 5. How it all composes (one run)

1. The orchestrator assembles `RunDeps` (run, owner, disabled-tool set, capability handles) — `agent/engine.py:run_chat_turn`.
2. `build_agent_toolsets()` produces the gated, namespaced stack; the `Agent` is built with it (`deps_type=RunDeps`, `output_type=[str, DeferredToolRequests]`).
3. The model runs its multi-step loop; for each call, the `_enabled_gate` and tool args are evaluated against `ctx.deps`. A non-sensitive tool executes and may emit `tool.progress`.
4. A **sensitive** tool does *not* execute — the turn ends with `DeferredToolRequests`; the run parks (§4.1) and waits for `POST …/approve`.
5. `execute_code` runs in the sandbox if present, else reports disabled (§4.2); `run_host_command` always parks for approval first.

The result: the spec's entire access-control surface (`AE-2` categories, `AE-3` sensitivity + enable/disable, `AE-4` model-discerns) is a **dozen lines of toolset composition plus a per-tool `requires_approval` flag** — keyed on one deps object, with every harder case (host exec, scheduled tasks, external tools) reusing the *same* deferred-tool pause rather than inventing new control flow.

---

## 6. Status & open seams

| Concern | State |
|---|---|
| Toolset stack (namespacing + enabled gate) | ✅ built (`tools/toolsets.py`) |
| `builtin`, `memory`, `code` categories | ✅ built |
| D20 approval pause/resume (engine + `/runs/{id}/approve`) | ✅ built |
| D23 sandbox isolation + host escape hatch | ✅ built (`services/sandbox`, `tools/code.py`) |
| Privilege gate (D14) | 🔭 seam reserved — empty until a second user exists |
| Relevance pre-filter (D3) | 🔭 seam reserved — deliberately omitted |
| D24 scheduled pre-authorization | ⬜ designed, lands with `TASK-*` |
| D25 external-tool gating + trusted allowlist | ⬜ designed, lands with `MCP-*` / `INTEG-*` |
| `search` / `mail` / `documents` / … categories | ⬜ land with their `services/` capability |

→ related detail: [`30-agent-engine.md`](./30-agent-engine.md) (the meta-loop and event translation), [`50-capabilities.md`](./50-capabilities.md) (the `services/` implementations tools adapt over), and the coverage matrix in [`70-spec-coverage.md`](./70-spec-coverage.md).
