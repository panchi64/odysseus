"""Normalising the model-facing text of a tool the moment before it is offered.

Most of what a model reads about a tool is written here, in this repo, by whoever wrote
the docstring. Two parts of it are not, and both are wrong in ways no amount of care in
our own files can fix:

- **Pydantic AI's docstring scaffolding.** Any docstring carrying a ``Returns:`` section
  comes back wrapped in ``<summary>…</summary>\\n<returns><description>…</description>
  </returns>`` (``pydantic_ai/_griffe.py``). No ``Tool`` or ``FunctionToolset`` option
  turns it off, and every tool ``pydantic_ai_harness`` contributes — the browser, the
  filesystem, the shell — is written that way. The tags are markup a reader has to see
  past, and the returns block restates what running the tool would show anyway.
- **Cross-references by a name that does not exist.** A harness toolset is written
  against its own function names, so its prose says "pass one back to ``snapshot``" and
  its parameters say "the ID returned by start_command". Every tool in this catalog is
  namespaced ``category_tool`` (``tools/toolsets.py``), so those names are not offered
  and a model that follows the instruction calls a tool that isn't there.

A third problem is ours only in the sense that we chose the library: the harness's
``Planning`` emits its **subtasks** vocabulary into the JSON schema — ``parent_id``,
``depends_on``, a ``blocked`` status, and prose explaining the flag that would enable
them — while we run with subtasks off, so the runtime rejects every one of them. Schema
the model is charged for and can only be punished for using is worse than no schema.

Everything here is a pure function over a ``ToolDefinition``: the same input gives the
same output, and applying it twice changes nothing the first pass didn't. That matters
because the rewrite runs on a prepare stage, once per model request, over definitions
other code (the operator's catalog, the sensitivity classifier) reads independently —
nothing is mutated in place, so the toolsets' own tool objects stay as the library
built them.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from functools import lru_cache
from typing import Any

from pydantic_ai import ToolDefinition

#: The whole description when a docstring had both a summary and a ``Returns:`` section.
_SUMMARY_AND_RETURNS = re.compile(
    r"\A<summary>(?P<summary>.*?)</summary>\s*<returns>.*</returns>\s*\Z", re.DOTALL
)
#: The whole description when the docstring was *only* a ``Returns:`` section — the
#: summary is empty, so the return text is all the model would have to go on.
_RETURNS_ONLY = re.compile(
    r"\A<returns>\s*(?:<type>.*?</type>\s*)?<description>(?P<description>.*?)</description>"
    r"\s*</returns>\s*\Z",
    re.DOTALL,
)
#: One run of backticks around text that stays on a single line — the form every
#: docstring in this catalog uses to mark an identifier.
_BACKTICKED = re.compile(r"(?P<ticks>`+)(?P<body>[^`\n]+?)(?P=ticks)")

#: Properties a category's tools carry that the model should not be charged for. The
#: browser's ``timeout_ms`` is a per-call override of a default the operator configures;
#: thirteen tools repeat its two-line description, and a model has no basis for picking a
#: number. The parameter itself is untouched — ``PreparedToolset`` keeps the original
#: argument validator, and the harness function keeps its ``None`` default — so dropping
#: it from the schema only stops it being offered.
_UNOFFERED_PROPERTIES: Mapping[str, frozenset[str]] = {"browse": frozenset({"timeout_ms"})}

#: Fields, enum values and prose that ``pydantic_ai_harness``'s ``Planning`` emits for a
#: subtasks mode we do not run. The toolset rejects all of them at call time.
_SUBTASK_PROPERTIES: frozenset[str] = frozenset({"parent_id", "depends_on"})
_SUBTASK_STATUS = "blocked"

#: Replacement prose for the library's own schema definitions, whose docstrings carry
#: rendered ``Attributes:`` blocks that duplicate the per-property descriptions beside
#: them and sentences about the flag that would turn subtasks on.
_PLAN_DEF_TEXT: Mapping[str, str] = {
    "PlanItem": "One step in the plan.",
    "TaskStatus": "Lifecycle status of a plan step.",
    "PlanStatusUpdate": "One status change in the batch.",
}
_PLAN_PROPERTY_TEXT: Mapping[tuple[str, str], str] = {
    ("PlanItem", "status"): "Current status of this step.",
    ("PlanStatusUpdate", "status"): "New status.",
}


def strip_docstring_xml(description: str | None) -> str | None:
    """Give back the summary alone, without the XML Pydantic AI wrapped it in.

    The returns block goes rather than being folded in: it describes the shape of a
    result the model is about to read in full anyway, and it is where the library's
    prose leaks configuration field names the model cannot set. A docstring that was
    *only* a returns section keeps its text, since dropping it would leave a tool
    described by nothing at all.
    """
    if not description:
        return description
    if summary := _SUMMARY_AND_RETURNS.match(description):
        return summary.group("summary").strip()
    if returns := _RETURNS_ONLY.match(description):
        return returns.group("description").strip()
    return description


def drop_properties(schema: Mapping[str, Any], names: Iterable[str]) -> dict[str, Any]:
    """Remove top-level properties, and any mention of them in ``required``."""
    dropped = frozenset(names)
    out = copy.deepcopy(dict(schema))
    properties = out.get("properties")
    if isinstance(properties, dict):
        for name in dropped:
            properties.pop(name, None)
    required = out.get("required")
    if isinstance(required, list):
        out["required"] = [name for name in required if name not in dropped]
        if not out["required"]:
            del out["required"]
    return out


def prefix_references(
    text: str,
    names_by_category: Mapping[str, frozenset[str]],
    category: str | None = None,
) -> str:
    """Rewrite a tool's own cross-references into the names the model is actually offered.

    Resolution is deliberately **within the referring tool's own category**. A bare name
    is only unambiguous there: ``search`` is two different tools across the catalog, and
    ``list``, ``start`` and ``select`` are ordinary words in browser and calendar prose
    that happen to collide with a registered name somewhere else. A reference that
    crosses a category has to be written out in full by whoever wrote it — which is the
    house rule anyway.

    Two shapes are rewritten. Inside backticks, any name in the category; outside them,
    only a name carrying an underscore — a compound identifier cannot be mistaken for a
    word of English, and a bare ``read`` or ``send`` in running prose certainly can.
    Dotted references (``corpus.retrieve``) resolve across every category, since a dot
    is a claim about a tool rather than a word.
    """
    patterns = _patterns(names_by_category)
    inside, compound = patterns.for_category(category)
    if inside is not None:
        text = _BACKTICKED.sub(
            lambda m: f"{m['ticks']}{_prefix_all(m['body'], inside, category)}{m['ticks']}",
            text,
        )
        text = _prefix_all(text, compound, category)
    return patterns.dotted.sub(lambda m: m[0].replace(".", "_", 1), text)


def strip_schema_leaks(name: str, schema: Mapping[str, Any]) -> dict[str, Any]:
    """Take the library's unreachable vocabulary out of one tool's JSON schema.

    Keyed per tool rather than applied by pattern: the fields are a specific library's
    specific optional mode, and a rule broad enough to catch them by shape would sooner
    or later delete something a tool means. ``tests/test_tool_descriptions.py`` asserts
    over the whole assembled catalog that nothing else has grown the same leak, so a
    harness upgrade that spreads it fails a test rather than reaching the model.
    """
    out = copy.deepcopy(dict(schema))
    if name in _SUBTASKS_LEAKED:
        _strip_subtasks(out)
    return out


def describe_text(
    name: str,
    description: str | None,
    names_by_category: Mapping[str, frozenset[str]],
) -> str | None:
    """The description a tool is offered under — what the model reads, and, so that the
    operator deciding whether to allow a tool sees the same thing, what the settings
    catalog lists."""
    stripped = strip_docstring_xml(description)
    if not stripped:
        return stripped
    return prefix_references(stripped, names_by_category, category_of(name, names_by_category))


def describe(
    tool_def: ToolDefinition, names_by_category: Mapping[str, frozenset[str]]
) -> ToolDefinition:
    """One tool, restated in the names and the vocabulary this catalog actually offers.

    Only the two model-facing fields change. Everything that carries policy — the kind an
    approval gate rewrote, the sensitivity metadata, deferred loading — is preserved by
    ``dataclasses.replace`` rather than reassembled, because a describing pass that
    quietly ungated a tool would be a security bug wearing a copy-editing hat.
    """
    category = category_of(tool_def.name, names_by_category)
    schema = strip_schema_leaks(tool_def.name, tool_def.parameters_json_schema)
    if unoffered := _UNOFFERED_PROPERTIES.get(category or ""):
        schema = drop_properties(schema, unoffered)
    _prefix_schema_text(schema, names_by_category, category)
    return replace(
        tool_def,
        description=describe_text(tool_def.name, tool_def.description, names_by_category),
        parameters_json_schema=schema,
    )


def category_names(
    categories: Mapping[str, Any],
) -> dict[str, frozenset[str]]:
    """The category → tool-name map the rewrite resolves references against.

    Read off the assembled category mapping itself, so it is the same set of names the
    agent is offered. A toolset that resolves its tools dynamically (an external MCP
    server) exposes no static registry and contributes an empty set — its descriptions
    are someone else's text and are left exactly as they arrived.
    """
    return {
        category: frozenset(getattr(toolset, "tools", {}))
        for category, toolset in categories.items()
    }


def category_of(name: str, names_by_category: Mapping[str, frozenset[str]]) -> str | None:
    """Which category a namespaced ``category_tool`` name was registered under.

    Longest prefix wins, so a category whose name is a prefix of another's cannot claim
    the other's tools.
    """
    candidates = [
        category
        for category, bare in names_by_category.items()
        if name.startswith(f"{category}_") and name[len(category) + 1 :] in bare
    ]
    return max(candidates, key=len) if candidates else None


#: The plan tools whose schema carries the harness's subtasks vocabulary.
_SUBTASKS_LEAKED = frozenset({"plan_write_plan", "plan_update_task_statuses"})


def _strip_subtasks(schema: dict[str, Any]) -> None:
    """Edit one already-copied plan schema in place."""
    defs = schema.get("$defs")
    if not isinstance(defs, dict):
        return
    for def_name, definition in defs.items():
        if not isinstance(definition, dict):
            continue
        # The `$defs` key already names the definition; a `title` repeating it is bytes
        # for nothing on every request.
        if definition.get("title") == def_name:
            del definition["title"]
        if text := _PLAN_DEF_TEXT.get(def_name):
            definition["description"] = text
        if isinstance(enum := definition.get("enum"), list):
            definition["enum"] = [value for value in enum if value != _SUBTASK_STATUS]
        properties = definition.get("properties")
        if not isinstance(properties, dict):
            continue
        for property_name in _SUBTASK_PROPERTIES:
            properties.pop(property_name, None)
        if isinstance(required := definition.get("required"), list):
            definition["required"] = [name for name in required if name not in _SUBTASK_PROPERTIES]
        for property_name, property_schema in properties.items():
            if isinstance(property_schema, dict) and (
                text := _PLAN_PROPERTY_TEXT.get((def_name, property_name))
            ):
                property_schema["description"] = text


def _prefix_schema_text(
    node: Any, names_by_category: Mapping[str, frozenset[str]], category: str | None
) -> None:
    """Rewrite every ``description`` in an already-copied schema, at any depth.

    Parameter descriptions carry as many dangling references as the tool descriptions do
    — the browser's arguments alone point at ``snapshot`` eleven times — and a model
    reading one is being told to call a tool it was never given.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "description" and isinstance(value, str):
                node[key] = prefix_references(value, names_by_category, category)
            else:
                _prefix_schema_text(value, names_by_category, category)
    elif isinstance(node, list):
        for item in node:
            _prefix_schema_text(item, names_by_category, category)


@dataclass(frozen=True)
class _Patterns:
    """The compiled alternations one catalog needs, built once per catalog."""

    #: category → (any name in it, only the names carrying an underscore).
    by_category: Mapping[str, tuple[re.Pattern[str] | None, re.Pattern[str] | None]]
    #: ``category.tool`` for every registered tool, across categories.
    dotted: re.Pattern[str]

    def for_category(
        self, category: str | None
    ) -> tuple[re.Pattern[str] | None, re.Pattern[str] | None]:
        return self.by_category.get(category or "", (None, None))


def _patterns(names_by_category: Mapping[str, frozenset[str]]) -> _Patterns:
    """The catalog is assembled once at startup and this runs on every model request, so
    the alternations are compiled against the category map's contents, not rebuilt."""
    return _compile(tuple(sorted(names_by_category.items())))


@lru_cache(maxsize=8)
def _compile(items: tuple[tuple[str, frozenset[str]], ...]) -> _Patterns:
    return _Patterns(
        by_category={
            category: (
                _alternation(names),
                _alternation(name for name in names if "_" in name),
            )
            for category, names in items
        },
        dotted=_alternation(f"{category}.{name}" for category, names in items for name in names)
        or re.compile(r"(?!x)x"),
    )


def _alternation(names: Iterable[str]) -> re.Pattern[str] | None:
    """A pattern matching any of ``names`` standing alone as an identifier.

    The lookarounds are what make the rewrite idempotent: an already-prefixed
    ``plan_write_plan`` has a word character before ``write_plan``, so the second pass
    finds nothing to do. Longest first, so ``update_task_statuses`` is not half-matched
    by ``update_task_status``.
    """
    ordered = sorted(names, key=len, reverse=True)
    if not ordered:
        return None
    joined = "|".join(re.escape(name) for name in ordered)
    return re.compile(rf"(?<![A-Za-z0-9_])(?:{joined})(?![A-Za-z0-9_])")


def _prefix_all(text: str, pattern: re.Pattern[str] | None, category: str | None) -> str:
    return text if pattern is None else pattern.sub(lambda m: f"{category}_{m[0]}", text)
