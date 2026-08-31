"""Reading a shell command's worst case off its grammar.

The half of the capability extraction that has to understand bash. Split from
``capability.py`` because the two change for entirely different reasons: this file moves
when the grammar grows a construct or a construct's worst case is read wrong, and that one
moves when a tool is added. Keeping them together would mean a tree-sitter node table and
a tool-name table living in one file and being edited by two different kinds of change.

**Why a real parser.** A command's worst case is a property of its *syntax* — which words
are program names, which are arguments, where a substitution nests — and regexes over that
syntax are wrong on exactly the cases that matter: a `;` inside a quoted string, a `$(…)`
inside a `"…"`, a redirect glued to a word. `tree-sitter-bash` is the maintained grammar,
and it recovers from errors instead of throwing, so a command it cannot parse comes back
as a tree with error nodes we can *see* and treat as unreadable — rather than as an
exception someone might catch and shrug off. `bashlex`, the pure-Python alternative, has
been unmaintained since ~2019 and breaks on ordinary bashisms.

**Every unread construct is recorded, never skipped.** A skipped node would silently
shrink the described worst case to less than the real one, which is the one failure a
deterministic stage cannot have — its consumer would then clear a command on the strength
of the part of it that parsed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import tree_sitter_bash
from tree_sitter import Language, Node, Parser

from services.permissions.shell_flags import attached_value, is_flag
from services.sandbox.base import SandboxError, contained_path

#: One parser, built once. `tree_sitter.Parser` is a thin handle over an immutable grammar
#: and parsing is synchronous and CPU-bound; rebuilding it per call would pay the grammar
#: load on every deferred command for nothing.
_LANGUAGE = Language(tree_sitter_bash.language())
_PARSER = Parser(_LANGUAGE)

# Node types that carry no meaning of their own — sequencing, grouping punctuation and
# comments. Walked through rather than ruled on. The operators are listed by their literal
# text because that is what the grammar names an anonymous node.
_STRUCTURE = frozenset({"program", "list", "pipeline", "redirected_statement"})
_IGNORED = frozenset({"&&", "||", "|", "|&", ";", ";;", "&", "\n", "comment"})

# Argument nodes whose text is fixed at parse time — the only kind whose value we know.
_LITERAL = frozenset({"word", "number", "raw_string"})

# Constructs whose value is decided at run time, by the shell or by another command.
# Each is named in the refusal because "which part of this could not be read" is the
# operator's first question when a benign-looking command escalates.
_DYNAMIC = {
    "simple_expansion": "a variable whose value is not known here",
    "expansion": "a parameter expansion whose value is not known here",
    "command_substitution": "a nested command whose output becomes an argument",
    "process_substitution": "a nested command substituted as a file",
    "arithmetic_expansion": "an arithmetic expansion",
}


@dataclass(frozen=True)
class ShellCommand:
    """One command inside a shell action — the program, and the words it was given.

    Kept as a pair rather than flattened into one list of words for the case that made the
    difference: `git log | git cat-file --batch` is two programs with two argument sets,
    and a policy asking "was this git invoked in a reading form?" has to be able to ask it
    of each one. A flat word list answers a different, weaker question.

    ``arguments`` is every literal argument in order, flags included — flags are kept
    because a flag is what separates `find .` from `find . -delete`, and because a flag is
    where a path hides when someone would rather it were not seen.
    """

    program: str
    arguments: tuple[str, ...] = ()


@dataclass(frozen=True)
class ShellReach:
    """What one command would touch, as the walk found it."""

    commands: tuple[ShellCommand, ...] = ()
    reads: tuple[str, ...] = ()
    writes: tuple[str, ...] = ()
    env_writes: tuple[str, ...] = ()
    network: bool = False
    escapes: tuple[str, ...] = ()
    unbounded: tuple[str, ...] = field(default_factory=tuple)


def escapes_workspace(root: Path | None, raw: str) -> bool:
    """Whether a path argument could land outside the workspace.

    Home-relative paths are refused outright rather than resolved: `~` is the operator's
    own directory by definition, so a command naming it is reaching past the workspace
    whatever the rest of the path says — and resolving it would only turn the question
    into one about a directory this process may not even share.

    With no known root — a stateless turn, a mode whose workspace never opened — an
    absolute or upward path is treated as escaping. There is nothing to measure it
    against, and "we could not tell" has to read the same as "it left".
    """
    if raw.startswith("~"):
        return True
    path = Path(raw)
    if root is None:
        return path.is_absolute() or ".." in path.parts
    try:
        contained_path(root, raw, what="path")
    except SandboxError:
        return True
    return False


def shell_reach(command: str, *, root: Path | None) -> ShellReach:
    """What one shell command would reach, read off its syntax.

    ``root`` is the run's workspace directory when it has one — the fence every path
    argument is measured against. None when the turn has no workspace open, in which case
    nothing can be placed and every absolute or upward path reads as an escape.
    """
    walk = _Walk(root)
    tree = _PARSER.parse(command.encode())
    # Asked of the whole tree before the walk, because the grammar's recovery is *quiet*:
    # `ls |` comes back as a well-formed pipeline whose second command has a MISSING name,
    # so a walk that only looked for ERROR nodes on its way down would describe it as two
    # commands and call the description complete. `has_error` covers both, at the root,
    # once — and the walk still runs, so what *was* read is still on the record.
    if tree.root_node.has_error:
        walk.unbounded.append("a fragment the shell grammar could not parse")
    walk.visit(tree.root_node)
    return ShellReach(
        commands=tuple(walk.commands),
        reads=tuple(walk.reads),
        writes=tuple(walk.writes),
        env_writes=tuple(walk.env_writes),
        network=walk.network,
        escapes=tuple(dict.fromkeys(walk.escapes)),
        unbounded=tuple(dict.fromkeys(walk.unbounded)),
    )


def _literal(node: Node) -> str | None:
    """The fixed text of an argument node, or None when it is decided at run time.

    A quoted string counts only when nothing inside it expands: `"foo"` is a literal,
    `"$HOME/foo"` is not, and telling the two apart is exactly what a regex cannot do.
    """
    if node.type in _LITERAL:
        text = node.text.decode(errors="replace") if node.text else ""
        return text[1:-1] if node.type == "raw_string" else text
    if node.type == "string":
        if any(child.type in _DYNAMIC for child in node.children):
            return None
        return node.text.decode(errors="replace").strip('"') if node.text else ""
    if node.type == "concatenation":
        parts = [_literal(child) for child in node.children]
        if any(part is None for part in parts):
            return None
        return "".join(part for part in parts if part is not None)
    return None


class _Walk:
    """One pass over a parsed command, accumulating what it would reach.

    A class rather than a fold because the walk is genuinely stateful — every branch
    contributes to the same lists — and because the recursion has to be able to stop
    describing and start refusing at any depth.
    """

    def __init__(self, root: Path | None) -> None:
        self._root = root
        self.commands: list[ShellCommand] = []
        self.reads: list[str] = []
        self.writes: list[str] = []
        self.env_writes: list[str] = []
        self.escapes: list[str] = []
        self.unbounded: list[str] = []
        self.network = False

    def visit(self, node: Node) -> None:
        if node.is_error or node.type == "ERROR":
            self.unbounded.append("a fragment the shell grammar could not parse")
            return
        if node.type in _IGNORED:
            return
        if node.type in _STRUCTURE:
            for child in node.children:
                self.visit(child)
            return
        if node.type == "command":
            self._command(node)
            return
        if node.type == "file_redirect":
            self._redirect(node)
            return
        if node.type in _DYNAMIC:
            self.unbounded.append(_DYNAMIC[node.type])
            return
        # Everything the grammar can produce and this module has no rule for: a subshell,
        # a loop, a function definition, a conditional, a heredoc. Naming the node type is
        # deliberate — it is the one string that tells whoever reads the escalation which
        # rule is missing.
        self.unbounded.append(f"an unrecognised shell construct ({node.type})")

    def _command(self, node: Node) -> None:
        program: str | None = None
        arguments: list[str] = []
        for child in node.children:
            if child.type == "variable_assignment":
                name = child.child_by_field_name("name")
                self.env_writes.append(
                    name.text.decode(errors="replace")
                    if name and name.text
                    else "an environment variable"
                )
            elif child.type == "command_name":
                # The command name is the one word that decides everything else, so a name
                # this module cannot read is not a command with an unknown name — it is
                # not a command at all as far as anything downstream may assume.
                program = _literal(child.children[0]) if child.child_count else None
                if not program:
                    # Empty as well as absent: a MISSING name node reads as the empty
                    # string, and an empty program is not a program with a short name.
                    program = None
                    self.unbounded.append("a program name assembled at run time")
            elif child.type == "file_redirect":
                self._redirect(child)
            else:
                word = self._argument(child)
                if word is not None:
                    arguments.append(word)
        if program is not None:
            self.commands.append(ShellCommand(program, tuple(arguments)))

    def _redirect(self, node: Node) -> None:
        # Every redirect is recorded as a write, the input ones included. `< file` only
        # reads, but calling a read a write can only escalate, and a rule with no
        # exceptions is a rule nobody has to check the exceptions of.
        for child in node.children:
            if child.type in _DYNAMIC:
                self.unbounded.append(_DYNAMIC[child.type])
                continue
            target = _literal(child)
            if target is not None:
                self._path(target, self.writes)

    def _argument(self, node: Node) -> str | None:
        """One argument's literal text, recorded against the worst case as it goes.

        A flag reaches exactly as far as the value glued to it — `--output=/etc/passwd`
        and `-o/etc/passwd` name that file as plainly as writing it on its own would, and
        a walk that dismissed every word starting with `-` could not see either. What the
        flag *means* is not this file's question; that the word it carries is a path is.
        """
        if node.type in _DYNAMIC:
            self.unbounded.append(_DYNAMIC[node.type])
            return None
        value = _literal(node)
        if value is None:
            self.unbounded.append(f"an argument of a kind not read here ({node.type})")
            return None
        if is_flag(value):
            attached = attached_value(value)
            if attached is not None:
                self._reach(attached)
        else:
            self._reach(value)
        return value

    def _reach(self, word: str) -> None:
        """What one word — an operand, or the value carried on a flag — would touch."""
        if "://" in word:
            self.network = True
        elif _names_a_path(word):
            self._path(word, self.reads)

    def _path(self, raw: str, into: list[str]) -> None:
        into.append(raw)
        if escapes_workspace(self._root, raw):
            self.escapes.append(raw)


def _names_a_path(word: str) -> bool:
    """Whether a word could reach out of the directory the command runs in.

    Only a word that *names a directory* can leave the workspace: a bare word is at worst
    a file beside the ones already there. Recording every bare word as a read would bury
    the two that matter under a page of grep patterns.
    """
    return "/" in word or word.startswith("~") or word in {".", ".."}
