"""Skill tools — the agent opens a playbook and works from it (`SKILL-2`, `SKILL-3`).

Skills follow the **Agent Skills** standard's progressive disclosure, and these tools are
levels two and three of it:

1. Every *published* skill's name and description is already in the turn's instructions
   (``agent/engine.py`` injects the catalog), so the model knows what exists without a call.
2. ``open`` returns the skill's full ``SKILL.md`` instructions — the level the model pays for
   only when a skill is actually relevant.
3. ``open`` **also stages the bundle into the sandbox** at ``/work/skills/{name}/``, so the
   supporting files are real files: references to read, scripts to run with ``code_execute``.
   Nothing about a skill ever touches the host — a skill's script is ordinary sandboxed code.

``create`` and ``edit`` let the agent write skills down as it learns them, always as
**drafts**: publishing is the operator's act, and it is what makes a skill visible to the
model at all. That split is also the seam `SKILL-4` (auto-publishing high-confidence
recoveries) will plug into.

Thin like every tool here: the format rules, sealing, and validation live in
``services/skills``; a missing capability degrades to a message the model can act on.
"""

from __future__ import annotations

from pydantic_ai import FunctionToolset, ModelRetry, RunContext

from core.exceptions import NotFoundError, SkillSpanError, SkillValidationError
from services.sandbox import SandboxError, SandboxSessionManager
from services.skills import BUNDLE_MAX_BYTES, SKILL_FILE, SkillStore, render_skill_md
from services.skills.store import SkillView

from .deps import RunDeps

#: Where a staged bundle lands inside the sandbox working directory (mirrors
#: ``attachments/`` from the attachments tool).
_STAGE_DIR = "skills"
_UNAVAILABLE = "Skills are unavailable right now."


async def _published_names(store: SkillStore, owner_id: str) -> str:
    entries = await store.catalog(owner_id)
    return ", ".join(entry.name for entry in entries) or "none yet"


async def _stage(session, skill: SkillView, files: list[tuple[str, bytes]]) -> list[str]:
    """Write the bundle into the sandbox, skipping any file already there byte-for-byte so
    re-opening a skill in a warm session is a no-op rather than a rewrite. Returns the
    absolute ``/work`` paths the model should use."""
    root = f"{_STAGE_DIR}/{skill.name}"
    staged: list[str] = []
    for relpath, blob in [(SKILL_FILE, render_skill_md(skill.parsed()).encode())] + files:
        target = f"{root}/{relpath}"
        try:
            if session.read_file(target) == blob:
                staged.append(f"/work/{target}")
                continue
        except SandboxError:
            pass  # not staged yet — write it
        session.write_file(target, blob)
        staged.append(f"/work/{target}")
    return staged


def skills_toolset() -> FunctionToolset[RunDeps]:
    toolset: FunctionToolset[RunDeps] = FunctionToolset()

    @toolset.tool
    async def open(ctx: RunContext[RunDeps], name: str) -> dict:
        """Open one of the skills listed in your instructions and follow it.

        Call this **before** starting a task a skill covers — the listing only tells you a
        skill exists; this returns the actual procedure. Pass the skill's ``name`` exactly as
        listed.

        The result has ``instructions`` (the skill's full text — treat it as guidance for
        this task) and ``files``: the skill's bundled files, copied into your computer at
        ``/work/skills/{name}/``. Read a reference file or run a bundled script from there
        with ``code_execute`` — invoke scripts explicitly (``python /work/skills/x/scripts/y.py``
        or ``bash …``), since staged files are not marked executable. Use the returned paths
        verbatim.

        ``allowed_tools``, when present, is the skill author's advisory note about which
        tools it expects to use — it does not restrict you, and it grants you nothing."""
        store = ctx.deps.caps.get_optional(SkillStore)
        if store is None:
            return {"ok": False, "error": _UNAVAILABLE}
        try:
            skill = await store.get_by_name(ctx.deps.owner_id, name, published_only=True)
        except NotFoundError:
            available = await _published_names(store, ctx.deps.owner_id)
            raise ModelRetry(
                f"No published skill named {name!r}. Available skills: {available}."
            ) from None

        result: dict = {
            "ok": True,
            "name": skill.name,
            "description": skill.description,
            "instructions": skill.body,
            "files": [],
        }
        if skill.allowed_tools:
            result["allowed_tools"] = skill.allowed_tools

        sessions = ctx.deps.caps.get_optional(SandboxSessionManager)
        if sessions is None:
            result["note"] = (
                "Your computer is unavailable, so this skill's bundled files were not "
                "staged — follow the instructions without them."
            )
            return result

        files = await store.file_contents(ctx.deps.owner_id, skill.id)
        total = sum(len(blob) for _, blob in files)
        if total > BUNDLE_MAX_BYTES:
            result["note"] = (
                "This skill's bundle is too large to stage; follow the instructions without "
                "its files."
            )
            return result
        try:
            session = await sessions.acquire(ctx.deps.sandbox_key)
            result["files"] = await _stage(session, skill, files)
        except SandboxError as exc:
            result["note"] = f"The skill's files could not be staged: {exc}"
        return result

    @toolset.tool
    async def create(ctx: RunContext[RunDeps], name: str, description: str, body: str) -> dict:
        """Write down a reusable procedure you worked out, so it's available in future
        conversations.

        Use this when you solved something non-obvious that will recur — a multi-step
        recovery, a fiddly setup, a checklist that worked. Write it the way a skill should
        read: **when** to use it, **how** to do it, the **pitfalls**, and **how to verify**
        it worked.

        ``name`` must be lowercase letters, numbers, and hyphens (it is the skill's id).
        ``description`` is the one line that will decide whether a future turn opens it, so
        say what it does *and* when it applies.

        The skill is saved as a **draft**: the operator reviews and publishes it, and only
        published skills are surfaced. Say that you saved it, rather than implying it is
        already in use."""
        store = ctx.deps.caps.get_optional(SkillStore)
        if store is None:
            return {"ok": False, "error": _UNAVAILABLE}
        try:
            skill = await store.create(
                ctx.deps.owner_id,
                name=name,
                description=description,
                body=body,
                source="agent",
            )
        except SkillValidationError as exc:
            raise ModelRetry(f"That skill was rejected ({exc.field}): {exc}") from None
        return {
            "ok": True,
            "name": skill.name,
            "status": "draft",
            "note": "Saved as a draft for the operator to review and publish.",
        }

    @toolset.tool
    async def edit(ctx: RunContext[RunDeps], name: str, old_text: str, new_text: str) -> dict:
        """Make a small, targeted change to a skill's instructions — refine a step, fix a
        detail, add a pitfall you just hit — without rewriting the whole thing.

        ``old_text`` must appear **exactly once** in the skill's text; include enough
        surrounding context to make it unique. To append rather than replace, use the last
        line of the skill as ``old_text`` and return it followed by your new text."""
        store = ctx.deps.caps.get_optional(SkillStore)
        if store is None:
            return {"ok": False, "error": _UNAVAILABLE}
        try:
            # published_only, exactly as `open` resolves it: a draft is the operator's
            # unreviewed work, so the agent must not be able to rewrite one — nor learn
            # it exists from a different error message.
            skill = await store.get_by_name(ctx.deps.owner_id, name, published_only=True)
        except NotFoundError:
            available = await _published_names(store, ctx.deps.owner_id)
            raise ModelRetry(
                f"No published skill named {name!r}. Available skills: {available}."
            ) from None
        try:
            await store.replace_span(ctx.deps.owner_id, skill.id, old_text, new_text)
        except SkillSpanError as exc:
            if exc.occurrences == 0:
                raise ModelRetry(
                    "old_text was not found in that skill. Quote its existing text exactly, "
                    "including whitespace."
                ) from None
            raise ModelRetry(
                f"old_text matched {exc.occurrences} places in that skill. Include more "
                "surrounding context so it identifies exactly one."
            ) from None
        return {"ok": True, "name": skill.name, "note": "Skill updated."}

    return toolset
