"""The permission level: the knobs behind the four names, and the two halves that
enforce them.

Two halves, because one alone is not enforcement. The **toolset** marks every tool that
reaches past the level's write scope as needing approval, so the model's request for one
comes back undone instead of running — that half is checked through the composed stack a
real run resolves, not through a re-derivation of the rule. The **decision** then rules on
the call that came back. Between them sits the invariant worth the most here: a level only
ever adds a gate, never removes one. A tool that pauses its own calls is still answered at
every level — by the operator, or by the review at the one level whose entire meaning is
that they asked for their answers to be given for them — so raising a thread to Edit
cannot quietly delete a protection nobody re-examined.
"""

from __future__ import annotations

from pydantic_ai import FunctionToolset, RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from agent import build_chat_orchestrator
from core.db import init_db, make_engine
from core.vault import Vault
from runs import Run, RunRegistry, RunStatus, RunStream
from services.conversations import ConversationBinding, ConversationStore
from services.modes import MODES
from services.permissions import (
    DEFAULT_PERMISSION,
    PERMISSION_LEVELS,
    PERMISSIONS,
    PLANNING_TOOLS,
    STRICTEST_PERMISSION,
    ApprovalPolicy,
    Decision,
    WriteScope,
    beyond_scope,
    blocked_message,
    decide,
    permission_level,
    permission_spec,
    tools_beyond_scope,
)
from services.tool_policy import permission_disabled_tools
from services.tool_sensitivity import SENSITIVITY_CLASSES, Sensitivity
from tools import RunDeps, build_agent_toolsets

from ._helpers import (
    client_app,
    collect_sse_events,
    full_tool_categories,
    patch_model_resolution,
)

OWNER = "operator"

# One tool per class, by name, so the tests below read as the rule they check rather than
# as a list of strings. Each is pinned to its class by `test_tool_sensitivity.py`.
READ = "web_search"
WORKSPACE_WRITE = "files_write_file"
HOST_EXEC = "shell_run_command"
EXTERNAL_EFFECT = "mail_send"
SECRET = "vault_get_entry"
#: A name no literal can enumerate — an operator's own MCP tool. Classifies as an
#: external effect, which is the fail-closed reading and the honest one.
UNCLASSIFIED = "external_someserver_do_a_thing"


def _classified_names() -> set[str]:
    return {name for names in SENSITIVITY_CLASSES.values() for name in names}


class TestTheKnobs:
    """A level is a preset over a pair, not a fourth branch."""

    def test_every_level_has_a_preset(self):
        assert set(PERMISSIONS) == PERMISSION_LEVELS
        assert all(spec.level == level for level, spec in PERMISSIONS.items())

    def test_the_write_scopes_are_what_the_two_read_only_levels_share(self):
        # Plan and Manual differ in what happens past the scope, not in the scope — which
        # is the point of storing the pair: the read-only-ness is one knob, and the two
        # levels are two answers to the *other* one.
        assert PERMISSIONS["plan"].write_scope is WriteScope.NONE
        assert PERMISSIONS["manual"].write_scope is WriteScope.NONE
        assert PERMISSIONS["plan"].approval_policy is ApprovalPolicy.WITHHOLD
        assert PERMISSIONS["manual"].approval_policy is ApprovalPolicy.ASK

    def test_edit_and_auto_reach_the_workspace_and_differ_in_who_answers(self):
        assert PERMISSIONS["edit"].write_scope is WriteScope.WORKSPACE
        assert PERMISSIONS["auto"].write_scope is WriteScope.WORKSPACE
        assert PERMISSIONS["edit"].approval_policy is ApprovalPolicy.ASK
        assert PERMISSIONS["auto"].approval_policy is ApprovalPolicy.REVIEW

    def test_a_scope_resolves_to_a_ceiling_on_the_sensitivity_classes(self):
        assert PERMISSIONS["plan"].ceiling is Sensitivity.READ
        assert PERMISSIONS["edit"].ceiling is Sensitivity.WORKSPACE_WRITE

    def test_an_unreadable_level_lands_on_the_one_that_does_least(self):
        # Off a database row and out of a parked run's payload, both of which outlive a
        # rename. The conservative direction is the level that can only look.
        assert permission_level("nonsense") == STRICTEST_PERMISSION
        assert permission_level("") == STRICTEST_PERMISSION
        assert permission_spec("nonsense") is PERMISSIONS["plan"]
        assert all(permission_level(level) == level for level in PERMISSION_LEVELS)

    def test_beyond_scope_is_the_one_question_both_halves_ask(self):
        assert not beyond_scope("edit", WORKSPACE_WRITE)
        assert beyond_scope("edit", HOST_EXEC)
        assert beyond_scope("manual", WORKSPACE_WRITE)
        assert not beyond_scope("manual", READ)

    def test_the_set_form_agrees_with_the_predicate(self):
        # The catalog-narrowing caller works in sets and the decision point works one call
        # at a time; a level that withheld a different set than it refuses would be two
        # rules wearing one name.
        for level in PERMISSION_LEVELS:
            assert tools_beyond_scope(level) == frozenset(
                name for name in _classified_names() if beyond_scope(level, name)
            )

    def test_an_unclassifiable_tool_is_elevated_only_where_the_guess_is_load_bearing(self):
        # The unclassifiable names are the operator's own MCP and connector tools, and
        # those already carry a per-tool decision of theirs — the trust list. A level that
        # permits changes leaves that alone rather than overruling an explicit answer with
        # an inferred one; a level that permits *nothing* has no other way to keep its
        # promise against a tool nothing here can bound, so it elevates.
        assert beyond_scope("plan", UNCLASSIFIED)
        assert beyond_scope("manual", UNCLASSIFIED)
        assert not beyond_scope("edit", UNCLASSIFIED)
        assert not beyond_scope("auto", UNCLASSIFIED)
        # ...and a call that arrives anyway is still read as the class that reaches
        # furthest, which is what makes Plan's refusal reach it.
        assert decide("plan", UNCLASSIFIED) is Decision.BLOCK

    def test_the_plan_writes_are_permitted_at_every_level(self):
        # A read-only turn ends by writing down what it would do; a level that made it ask
        # first would leave it no way to finish at all.
        for level in PERMISSION_LEVELS:
            for tool in PLANNING_TOOLS:
                assert not beyond_scope(level, tool)

    def test_every_mode_starts_a_thread_at_a_level_that_exists(self):
        assert all(spec.default_permission in PERMISSION_LEVELS for spec in MODES.values())


class TestTheDecisionMatrix:
    """What each level does with a deferred call, by the class of what it would do."""

    def test_plan_refuses_rather_than_asks(self):
        # There is nothing to put in front of the operator: they answered by choosing the
        # level. Everything above a read is refused, including a tool no literal can name
        # — which is the one that gets past Plan's catalog narrowing.
        for tool in (WORKSPACE_WRITE, HOST_EXEC, EXTERNAL_EFFECT, SECRET, UNCLASSIFIED):
            assert decide("plan", tool) is Decision.BLOCK

    def test_manual_asks_about_everything_it_did_not_already_permit(self):
        for tool in (WORKSPACE_WRITE, HOST_EXEC, EXTERNAL_EFFECT, SECRET, UNCLASSIFIED):
            assert decide("manual", tool) is Decision.ASK

    def test_edit_asks_past_the_workspace_and_not_within_it(self):
        for tool in (HOST_EXEC, EXTERNAL_EFFECT, SECRET, UNCLASSIFIED):
            assert decide("edit", tool) is Decision.ASK
        # A workspace write does not reach this decision at Edit at all — the toolset
        # never marks it, so the model's call simply runs (see the elevation tests).
        assert not beyond_scope("edit", WORKSPACE_WRITE)

    def test_auto_sends_the_same_calls_to_review_instead(self):
        for tool in (HOST_EXEC, EXTERNAL_EFFECT, SECRET, UNCLASSIFIED):
            assert decide("auto", tool) is Decision.REVIEW

    def test_a_tools_own_gate_survives_every_level(self):
        # The asymmetry the module exists to hold. A read that pauses its own calls (the
        # global-recall gate) is within every level's scope, so no level *asked* for it to
        # defer — and none of them may wave it through either.
        for level in PERMISSION_LEVELS - {"auto"}:
            assert decide(level, READ) is Decision.ASK
        # Auto is the one level that answers it with something other than the operator,
        # and only because answering on their behalf is what choosing Auto means. It is
        # still answered, never skipped.
        assert decide("auto", READ) is Decision.REVIEW

    def test_a_corrupt_level_decides_as_plan(self):
        assert decide("nonsense", HOST_EXEC) is Decision.BLOCK

    def test_the_refusal_names_the_level_and_the_tool(self):
        # The model has to be able to tell a refusal from a transient failure, or it
        # spends the rest of the turn retrying a call that will never be allowed.
        message = blocked_message("plan", HOST_EXEC)
        assert "plan" in message
        assert HOST_EXEC in message


async def _resolved_kinds(permission: str) -> dict[str, str]:
    """How a real run's composed toolset stack ends up defining every tool it offers —
    the ground truth for the elevation, resolved through the same stack the engine hands
    the Agent rather than through a re-reading of the rule."""
    run = Run(id="t", kind="chat", owner_id=OWNER, stream=RunStream())
    deps = RunDeps(
        run=run,
        owner_id=OWNER,
        permission=permission,
        # Plan's catalog narrowing is `tool_policy`'s half and is tested there; apply it
        # here too so this resolves the stack a Plan run really resolves.
        disabled_tools=permission_disabled_tools(permission),
    )
    ctx = RunContext(deps=deps, model=TestModel(), usage=RunUsage())
    tools = await build_agent_toolsets(full_tool_categories())[0].get_tools(ctx)
    return {name: tool.tool_def.kind for name, tool in tools.items()}


class TestTheToolsetElevation:
    """The half that makes the decision reachable: a tool past the level's scope is
    marked as needing approval, so the call comes back instead of running."""

    async def test_edit_marks_past_the_workspace_and_leaves_the_workspace_alone(self):
        kinds = await _resolved_kinds("edit")
        assert kinds[WORKSPACE_WRITE] == "function"
        assert kinds[READ] == "function"
        assert kinds[HOST_EXEC] == "unapproved"
        assert kinds[EXTERNAL_EFFECT] == "unapproved"
        assert kinds[SECRET] == "unapproved"

    async def test_manual_marks_the_workspace_writes_too(self):
        kinds = await _resolved_kinds("manual")
        assert kinds[WORKSPACE_WRITE] == "unapproved"
        assert kinds[HOST_EXEC] == "unapproved"
        # Reading still needs nothing: Manual is "ask before you *act*", not "ask before
        # you look", and a level that paused every read would be unusable.
        assert kinds[READ] == "function"

    async def test_plan_withholds_what_it_can_and_marks_what_it_cannot(self):
        kinds = await _resolved_kinds("plan")
        # Withheld outright — the model is never offered them, so a Plan turn's schemas
        # are a fraction of the others'.
        assert WORKSPACE_WRITE not in kinds
        assert HOST_EXEC not in kinds
        # ...except the plan writes, which are the one mutation a Plan turn exists to
        # make, and which still run without a prompt.
        assert kinds["plan_write_plan"] == "function"
        assert kinds[READ] == "function"

    async def test_a_tools_own_marking_is_never_taken_away(self):
        # `mail_send` carries `requires_approval=True` of its own. Every level must still
        # see it as needing approval, whatever its scope says.
        for level in ("edit", "auto", "manual"):
            assert (await _resolved_kinds(level))[EXTERNAL_EFFECT] == "unapproved"


class TestTheThreadRemembers:
    """The level lives on the conversation: set at creation from the mode, moved by the
    operator, and read back as one binding with the mode and the project."""

    async def _store(self, tmp_path) -> ConversationStore:
        engine = make_engine("sqlite:///:memory:")
        init_db(engine)
        vault = Vault(tmp_path / "keyfile.json")
        await vault.setup("pw")
        return ConversationStore(engine, vault)

    async def test_a_fresh_thread_starts_at_its_modes_default(self, tmp_path):
        store = await self._store(tmp_path)
        for mode, spec in MODES.items():
            conversation_id = await store.create_conversation(OWNER, mode=mode)
            binding = await store.binding(conversation_id)
            assert binding.permission == spec.default_permission

    async def test_an_explicit_level_beats_the_modes_default(self, tmp_path):
        store = await self._store(tmp_path)
        conversation_id = await store.create_conversation(OWNER, permission="plan")
        assert (await store.binding(conversation_id)).permission == "plan"

    async def test_the_level_moves_and_the_rest_of_the_binding_does_not(self, tmp_path):
        store = await self._store(tmp_path)
        conversation_id = await store.create_conversation(OWNER, mode="code", project_id="p1")
        assert await store.set_permission_level(conversation_id, "manual") == "manual"
        binding = await store.binding(conversation_id)
        assert binding.permission == "manual"
        assert binding.mode == "code"
        assert binding.project_id == "p1"

    async def test_a_corrupt_stored_level_reads_as_the_strictest(self, tmp_path):
        store = await self._store(tmp_path)
        conversation_id = await store.create_conversation(OWNER)
        await store.set_permission_level(conversation_id, "nonsense")
        assert (await store.binding(conversation_id)).permission == STRICTEST_PERMISSION

    async def test_a_missing_thread_reads_as_the_default(self, tmp_path):
        store = await self._store(tmp_path)
        assert (await store.binding("no-such-thread")).permission == DEFAULT_PERMISSION


class TestTheLiveControl:
    """Switching mid-thread is a plain send, and a Plan turn ends by being accepted."""

    async def test_a_send_carries_the_level_and_it_persists(self, monkeypatch):
        patch_model_resolution(monkeypatch, output_text="ok")
        async with client_app() as (client, _app):
            created = await client.post("/chat", json={"prompt": "hi", "permission_level": "plan"})
            conversation_id = created.json()["conversation_id"]
            await collect_sse_events(client, created.json()["run_id"])
            detail = await client.get(f"/conversations/{conversation_id}")
            assert detail.json()["permission_level"] == "plan"

            # ...and the next send moves it, without a separate call.
            again = await client.post(
                "/chat",
                json={
                    "prompt": "go on",
                    "conversation_id": conversation_id,
                    "permission_level": "edit",
                },
            )
            await collect_sse_events(client, again.json()["run_id"])
            detail = await client.get(f"/conversations/{conversation_id}")
            assert detail.json()["permission_level"] == "edit"

    async def test_a_send_without_a_level_leaves_the_thread_where_it_was(self, monkeypatch):
        patch_model_resolution(monkeypatch, output_text="ok")
        async with client_app() as (client, _app):
            created = await client.post(
                "/chat", json={"prompt": "hi", "permission_level": "manual"}
            )
            conversation_id = created.json()["conversation_id"]
            await collect_sse_events(client, created.json()["run_id"])
            again = await client.post(
                "/chat", json={"prompt": "more", "conversation_id": conversation_id}
            )
            await collect_sse_events(client, again.json()["run_id"])
            detail = await client.get(f"/conversations/{conversation_id}")
            assert detail.json()["permission_level"] == "manual"

    async def test_an_unknown_level_is_refused_at_the_edge(self, monkeypatch):
        patch_model_resolution(monkeypatch, output_text="ok")
        async with client_app() as (client, _app):
            resp = await client.post("/chat", json={"prompt": "hi", "permission_level": "root"})
            assert resp.status_code == 422

    async def test_accepting_a_plan_raises_the_level_and_hands_back_the_seed(
        self, monkeypatch
    ):
        patch_model_resolution(monkeypatch, output_text="here is the plan")
        async with client_app() as (client, app):
            created = await client.post(
                "/chat", json={"prompt": "plan it", "permission_level": "plan"}
            )
            conversation_id = created.json()["conversation_id"]
            await collect_sse_events(client, created.json()["run_id"])
            await app.state.conversation_plans.replace(
                "operator", conversation_id, _a_plan()
            )

            resp = await client.post(f"/conversations/{conversation_id}/plan/accept")
            assert resp.status_code == 200
            body = resp.json()
            assert body["permission_level"] == "edit"
            # The plan the operator agreed to rides in the seed, so the transcript records
            # what was accepted rather than whatever the list says later.
            assert "rewrite the parser" in body["prompt"]
            detail = await client.get(f"/conversations/{conversation_id}")
            assert detail.json()["permission_level"] == "edit"

    async def test_accepting_can_choose_the_unattended_level(self, monkeypatch):
        patch_model_resolution(monkeypatch, output_text="here is the plan")
        async with client_app() as (client, app):
            created = await client.post("/chat", json={"prompt": "plan it"})
            conversation_id = created.json()["conversation_id"]
            await collect_sse_events(client, created.json()["run_id"])
            await app.state.conversation_plans.replace("operator", conversation_id, _a_plan())

            resp = await client.post(
                f"/conversations/{conversation_id}/plan/accept", json={"level": "auto"}
            )
            assert resp.json()["permission_level"] == "auto"

    async def test_accepting_a_level_that_cannot_act_is_refused(self, monkeypatch):
        patch_model_resolution(monkeypatch, output_text="here is the plan")
        async with client_app() as (client, app):
            created = await client.post("/chat", json={"prompt": "plan it"})
            conversation_id = created.json()["conversation_id"]
            await collect_sse_events(client, created.json()["run_id"])
            await app.state.conversation_plans.replace("operator", conversation_id, _a_plan())

            resp = await client.post(
                f"/conversations/{conversation_id}/plan/accept", json={"level": "plan"}
            )
            assert resp.status_code == 422

    async def test_there_is_nothing_to_accept_without_a_plan(self, monkeypatch):
        patch_model_resolution(monkeypatch, output_text="no plan here")
        async with client_app() as (client, _app):
            created = await client.post("/chat", json={"prompt": "hi", "permission_level": "plan"})
            conversation_id = created.json()["conversation_id"]
            await collect_sse_events(client, created.json()["run_id"])

            resp = await client.post(f"/conversations/{conversation_id}/plan/accept")
            assert resp.status_code == 409
            # And the level did not move on the strength of a document that isn't there.
            detail = await client.get(f"/conversations/{conversation_id}")
            assert detail.json()["permission_level"] == "plan"


def _a_plan():
    from pydantic_ai_harness.planning import PlanItem

    return [PlanItem(id="1", content="rewrite the parser", status="pending")]


def _write_categories(calls: list[str]):
    """A category whose one tool classifies as a workspace write — and carries no marking
    of its own, so whether its call runs is entirely the level's answer."""
    toolset: FunctionToolset[RunDeps] = FunctionToolset()

    @toolset.tool_plain
    def write_file(path: str) -> str:
        calls.append(path)
        return f"wrote {path}"

    return {"files": toolset}


async def _run_at(level: str, calls: list[str]) -> Run:
    registry = RunRegistry()
    orchestrator = build_chat_orchestrator(
        "write the file",
        model=TestModel(custom_output_text="done"),
        categories=_write_categories(calls),
        binding=ConversationBinding(permission=level),
    )
    run = registry.submit(kind="chat", owner_id=OWNER, orchestrator=orchestrator)
    await run.wait()
    return run


class TestATurnUnderALevel:
    """The two halves, end to end: a real turn, a real tool, and the level deciding
    whether the call ever happens."""

    async def test_edit_lets_a_workspace_write_through(self):
        calls: list[str] = []
        run = await _run_at("edit", calls)
        assert run.status is RunStatus.done
        assert calls  # ran with no operator round-trip

    async def test_manual_parks_the_same_call(self):
        calls: list[str] = []
        run = await _run_at("manual", calls)
        assert run.status is RunStatus.awaiting_input
        assert not calls  # requested, not executed
        assert "approval.required" in [e.body.type for e in run.stream.replay()]

    async def test_plan_refuses_it_without_asking_anyone(self):
        calls: list[str] = []
        run = await _run_at("plan", calls)
        # The run finished on its own: the model was told the level does not permit this
        # and answered anyway. Nothing ran, and nothing waited on the operator.
        assert run.status is RunStatus.done
        assert not calls
        assert "approval.required" not in [e.body.type for e in run.stream.replay()]
