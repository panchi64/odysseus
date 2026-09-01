"""Reading an ``ask_user`` call, and writing the operator's reply back into it.

One module owns both halves on purpose. The questions the client renders and the answer
the model reads are derived from the *same* place — the arguments of the parked call —
so a label the operator clicked cannot mean one thing on screen and another in history.
The client sends back which options it chose, never the prose; this is where prose is
made, and it is made from the parked arguments rather than from anything the client said.

**Why the arguments are parsed defensively.** They are whatever the model produced. A
badly-shaped ``questions`` list must degrade to a thin question rather than raise: the
first caller is the park, which is a turn in the middle of stopping cleanly, and an
exception there strands the run instead of pausing it.
"""

from __future__ import annotations

from typing import Any

from runs import QuestionOption, QuestionSpec


class AnswerError(ValueError):
    """The reply doesn't fit the question it answers — an unknown option, or nothing at
    all. Raised for the route to render; never for the park."""


def questions_of(args: dict[str, Any]) -> list[QuestionSpec]:
    """The questions carried by one ``ask_user`` call, as event bodies."""
    questions: list[QuestionSpec] = []
    for raw in args.get("questions") or []:
        if not isinstance(raw, dict):
            continue
        options = [
            QuestionOption(
                label=str(opt["label"]),
                description=(
                    str(opt["description"]) if opt.get("description") is not None else None
                ),
            )
            for opt in (raw.get("options") or [])
            if isinstance(opt, dict) and opt.get("label") is not None
        ]
        questions.append(
            QuestionSpec(
                question=str(raw.get("question", "")),
                options=options,
                multi_select=bool(raw.get("multi_select", False)),
            )
        )
    return questions


def render_answer(
    questions: list[QuestionSpec],
    replies: list[tuple[list[str], str | None]],
) -> str:
    """The operator's reply as the model will read it: each question restated, then what
    they said to it.

    The question is restated rather than referenced by index because this string is the
    tool's *result*, and a result that reads "1. Postgres" is only interpretable next to a
    call the model has to go back and re-read. Restating costs a line and removes the
    dependency.

    Raises :class:`AnswerError` if the two don't line up, an option isn't one that was
    offered, or a question came back with nothing said to it at all.
    """
    if len(replies) != len(questions):
        raise AnswerError(
            f"expected one reply per question ({len(questions)}), got {len(replies)}"
        )
    lines: list[str] = []
    for question, (selections, text) in zip(questions, replies, strict=True):
        offered = {opt.label for opt in question.options}
        unknown = [label for label in selections if label not in offered]
        if unknown:
            raise AnswerError(
                f"{unknown!r} was not offered for {question.question!r}; "
                f"offered: {sorted(offered)}"
            )
        written = (text or "").strip()
        if not selections and not written:
            raise AnswerError(f"nothing was answered for {question.question!r}")
        lines.append(f"Q: {question.question}")
        if selections:
            lines.append(f"A: {', '.join(selections)}")
            if written:
                # Both: they picked, and then said something about it. Kept distinct from
                # the choice so the model can tell an elaboration from a selection.
                lines.append(f"   They also wrote: {written}")
        else:
            # No option fit. Say so, so the model doesn't read the prose as a label it
            # should have offered and try to match it against its own list.
            lines.append(f"A: (none of the options) {written}")
    return "\n".join(lines)
