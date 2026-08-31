"""Research as a *thread*, opened from inside another one.

Research used to be a pipeline with a store, a REST surface and a report; it is now a
conversation in research mode, opened by `research_start` and read back by
`research_read`. What that buys — and therefore what these tests hold onto — is that the
new thread is an *ordinary* one: created through the same conversation store, run through
the same turn composition, notified through the same conversation-linked policy. The
things worth pinning are the ones that would quietly stop being true:

- the thread is stored **in research mode**, since everything research-shaped about it
  (its prompt, its round-trip ceiling, its catalog) is the registry's answer to that one
  stored word;
- it inherits the **parent's project**, so it lands in the scope of the work that
  prompted it instead of appearing unfiled beside it;
- `start` **returns before the turn finishes**, which is the whole reason the tool is
  non-blocking;
- `read` answers from the thread itself, and refuses an id it does not own rather than
  inventing an empty answer.
"""

from __future__ import annotations

import pytest

from services.research_threads import ParentThread, ResearchThreads, ResearchUnavailableError
from tests._helpers import client_app, patch_model_resolution


def _threads(app) -> ResearchThreads:
    threads = app.state.capabilities.get_optional(ResearchThreads)
    assert threads is not None, "the research manifest did not export its implementation"
    return threads


async def _settle(app, run_id: str) -> None:
    """Let the submitted run finish — it is a real Run on the real registry."""
    run = app.state.runs.get(run_id)
    assert run is not None
    if run.task is not None:
        await run.task


class TestStarting:
    async def test_opens_a_research_thread_and_returns_before_it_finishes(self, monkeypatch):
        async with client_app() as (_client, app):
            patch_model_resolution(monkeypatch, output_text="the answer")
            started = await _threads(app).start(
                "operator", "Why is the sky blue?", context="physics, not poetry"
            )
            # Returned already — the run is still the registry's problem, not the
            # caller's. A tool that awaited this would spend its whole turn here.
            assert app.state.runs.get(started.run_id) is not None
            binding = await app.state.conversations.binding(started.conversation_id)
            assert binding.mode == "research"
            await _settle(app, started.run_id)

    async def test_the_thread_inherits_the_parents_project(self, monkeypatch):
        async with client_app() as (_client, app):
            patch_model_resolution(monkeypatch)
            started = await _threads(app).start(
                "operator",
                "Why?",
                parent=ParentThread(conversation_id="c-parent", project_id="proj-1"),
            )
            binding = await app.state.conversations.binding(started.conversation_id)
            assert binding.project_id == "proj-1"
            await _settle(app, started.run_id)

    async def test_the_question_and_the_context_both_reach_the_thread(self, monkeypatch):
        async with client_app() as (_client, app):
            patch_model_resolution(monkeypatch)
            started = await _threads(app).start(
                "operator", "Which of the two?", context="we ruled out the first one"
            )
            await _settle(app, started.run_id)
            turns = await app.state.conversations.messages_view(started.conversation_id)
            opening = next(t for t in turns if t.role == "user")
            # The context stands in for the clarifying exchange there was nobody to have.
            assert "Which of the two?" in opening.content
            assert "we ruled out the first one" in opening.content

    async def test_a_blank_question_is_refused_rather_than_researched(self):
        async with client_app() as (_client, app):
            with pytest.raises(ResearchUnavailableError):
                await _threads(app).start("operator", "   ")


class TestReading:
    async def test_returns_the_threads_latest_answer(self, monkeypatch):
        async with client_app() as (_client, app):
            patch_model_resolution(monkeypatch, output_text="what I found")
            started = await _threads(app).start("operator", "Why is the sky blue?")
            await _settle(app, started.run_id)
            view = await _threads(app).read("operator", started.conversation_id)
            assert view.answer == "what I found"
            assert view.question == "Why is the sky blue?"
            # Nothing in flight any more, and there is an answer.
            assert view.status == "done"

    async def test_an_unknown_thread_is_an_available_failure(self):
        async with client_app() as (_client, app):
            with pytest.raises(ResearchUnavailableError):
                await _threads(app).read("operator", "nope")

    async def test_another_owners_thread_is_not_readable(self, monkeypatch):
        async with client_app() as (_client, app):
            patch_model_resolution(monkeypatch)
            started = await _threads(app).start("operator", "Why?")
            await _settle(app, started.run_id)
            with pytest.raises(ResearchUnavailableError):
                await _threads(app).read("someone-else", started.conversation_id)
