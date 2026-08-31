"""Reading one argument token as a flag.

Two things need the same reading of a token, and would drift apart if each did it itself.
The grammar walk (``shell_ast.py``) needs the *value* glued to a flag, because a path
there is as real as a path standing on its own: `--output=/etc/passwd` names a file
exactly as `/etc/passwd` does, and a walk that skipped every word starting with `-` could
not see it. The allowlist (``read_only.py``) needs the *name*, because a table stating a
rule about `-o` and then matching raw tokens states nothing at all about `-o/tmp/x` or
`--output=x` — which is the same flag.

**Where the reading is ambiguous, both readings are taken.** `-oz` is either two short
flags or `-o` with the value `z`, and nothing short of a per-program option table can say
which. So a single-dash token contributes *every* letter in it as a candidate flag **and**
its tail as a candidate value: a denial matches if any reading is denied, and the
containment check runs if any reading names a path. Picking one reading would mean picking
the one an attacker gets to choose.

The one reading this module does **not** attempt is the separate word — `--output x`. That
would need to know which flags take a value, which is per-program knowledge this file does
not have; the word stands on its own in the argument list and is read as the ordinary
argument it looks like. What that leaves open — a flag whose value shifts the position of
the word after it — is answered where it matters, by refusing to read past a flag at all
(``read_only.py``'s subcommand rule).
"""

from __future__ import annotations

#: A bare `-` is stdin and a bare `--` ends the options; neither is a flag, and reading
#: them as one would invent a `-` flag no program has.
_NOT_FLAGS = frozenset({"-", "--"})


def is_flag(token: str) -> bool:
    """Whether ``token`` is an option rather than an operand."""
    return token.startswith("-") and token not in _NOT_FLAGS


def flag_names(token: str) -> frozenset[str]:
    """Every flag ``token`` could be using — empty when it is not a flag at all.

    A long token is exactly one flag, named up to its `=`. A single-dash token is both
    what it says (`-delete` is one predicate, not four letters) and every letter in it
    (`-la` is two flags, and `-oout` is `-o` carrying a value), because the two forms are
    indistinguishable without knowing the program's options.
    """
    if not is_flag(token):
        return frozenset()
    name = token.partition("=")[0]
    if token.startswith("--"):
        return frozenset({name})
    return frozenset({name}) | {f"-{letter}" for letter in token[1:]}


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
