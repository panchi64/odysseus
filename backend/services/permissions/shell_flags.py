"""Reading one argument token as a flag.

The grammar walk (``shell_ast.py``) needs two things from a token that starts with `-`,
and neither is what the flag *means*. It needs to know that the token is an option rather
than an operand, so the words a command leads with can be told from the words it acts on
(:func:`~services.permissions.shell_ast.command_prefix`). And it needs the *value* glued
to a flag, because a path there is as real as a path standing on its own:
`--output=/etc/passwd` names a file exactly as `/etc/passwd` does, and a walk that skipped
every word starting with `-` could not see it.

It lives apart from the walk because it is the one piece of that reading with an ambiguity
of its own. `-oz` is either two short flags or `-o` carrying the value `z`, and nothing
short of a per-program option table can say which — so :func:`attached_value` takes the
reading that names a path where either does, on the principle that picking one reading
means picking the one an attacker gets to choose.

The one reading this module does **not** attempt is the separate word — `--output x`. That
would need to know which flags take a value, which is per-program knowledge this file does
not have; the word stands on its own in the argument list and is read as the ordinary
argument it looks like.
"""

from __future__ import annotations

#: A bare `-` is stdin and a bare `--` ends the options; neither is a flag, and reading
#: them as one would invent a `-` flag no program has.
_NOT_FLAGS = frozenset({"-", "--"})


def is_flag(token: str) -> bool:
    """Whether ``token`` is an option rather than an operand."""
    return token.startswith("-") and token not in _NOT_FLAGS


def attached_value(token: str) -> str | None:
    """The value glued to a flag — after its `=`, or after a short flag's letter.

    None when the token carries no value of its own, which includes every long flag
    written without an `=`: its value, if it takes one, is the next word.
    """
    if not is_flag(token):
        return None
    _, separator, value = token.partition("=")
    if separator:
        return value
    if token.startswith("--"):
        return None
    return token[2:] or None
