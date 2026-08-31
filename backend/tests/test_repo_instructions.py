"""The byte budget on a project's own instruction files.

What is pinned is the *order of sacrifice*: broad files go whole before the specific one
is cut at all, and a cut lands on a line boundary with a marker the model can read. A
budget that truncated whichever file it reached first would be arithmetically correct and
practically useless — it would take the sentences the agent is standing in front of and
keep the ones about the monorepo.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_ai_harness.repo_context._loader import ContextFile

from tools.repo_instructions import (
    INSTRUCTIONS_BYTE_BUDGET,
    repo_instruction_text,
    within_budget,
)


def _file(name: str, content: str) -> ContextFile:
    return ContextFile(directory=Path("/repo"), path=Path("/repo") / name, content=content)


def test_files_that_fit_are_all_kept_untouched():
    files = [_file("AGENTS.md", "a" * 100), _file("CLAUDE.md", "b" * 100)]
    assert within_budget(files, 1_000) == files


def test_the_broad_file_is_dropped_whole_before_the_specific_one_is_cut():
    broad = _file("AGENTS.md", "broad\n" * 200)
    specific = _file("CLAUDE.md", "specific\n" * 10)
    kept = within_budget([broad, specific], 200)
    # Discovery orders broadest-first, so the survivor is the last one — and it is intact.
    assert [f.path.name for f in kept] == ["CLAUDE.md"]
    assert kept[0].content == specific.content


def test_the_last_file_standing_is_cut_rather_than_dropped():
    only = _file("CLAUDE.md", "".join(f"rule {n}\n" for n in range(500)))
    kept = within_budget([only], 200)

    assert len(kept) == 1
    body = kept[0].content
    assert len(body.encode("utf-8")) <= 200
    # Cut at a line boundary, with a marker — a brief that stops mid-rule reads as a
    # corrupted instruction rather than a shortened one.
    assert "cut here" in body
    assert "rule 0\n" in body
    assert "rule 499" not in body


def test_a_repo_with_no_instruction_file_contributes_nothing(tmp_path):
    assert repo_instruction_text(tmp_path) == ""


def test_a_repos_own_file_is_rendered_whole_when_it_is_a_sane_size(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("Run the tests with `uv run pytest`.\n")

    text = repo_instruction_text(tmp_path)

    assert "uv run pytest" in text
    assert 'path="CLAUDE.md"' in text  # labelled relative to the worktree root


def test_an_oversized_file_cannot_swallow_the_prompt_head(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("x" * (INSTRUCTIONS_BYTE_BUDGET * 3))

    text = repo_instruction_text(tmp_path)

    # The whole rendering, framing included, stays within a small multiple of the budget:
    # what must not happen is the file arriving at its own size.
    assert len(text.encode("utf-8")) < INSTRUCTIONS_BYTE_BUDGET + 1_000
