r"""Reading a shell command's worst case off its grammar.

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

**A word is only literal if the shell would hand it over unchanged.** The grammar gives
back the text as *written*, and the program is handed the text as *expanded* — and between
the two sit brace expansion, globbing and backslash removal, none of which the tree
records. `cat .\./etc/passwd`, `cat \/etc/passwd`, `cat {..,}/etc/passwd` and
`cat .[.]/.[.]/etc/passwd` all read `/etc/passwd` under `/bin/sh` while naming, as written,
a path with no `..` and no leading slash for a containment check to catch. So a bare word
carrying any of those characters is not read as a literal at all: it is recorded as
unbounded, exactly like a `$VAR`, and for the same reason — the value arrives later.
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

# What the shell still does to a *bare* word after the grammar has read it: brace
# expansion, globbing, backslash removal, and a backtick's substitution. Any of them makes
# the string the program receives a different string from the one written here, so a word
# carrying one is not a literal — see the module docstring for the four commands this set
# exists for.
_EXPANDED_UNQUOTED = frozenset("\\{}[]*?`")

# The same question inside double quotes, where quoting has already suppressed globbing and
# brace expansion. A backslash still escapes and a backtick still substitutes; a single
# quoted string interprets nothing at all and is therefore always the literal it reads as.
_EXPANDED_IN_QUOTES = frozenset("\\`")

#: What :func:`command_prefix` keeps: the program and the leading words that say which of
#: its modes was invoked (`uv run pytest`, `git commit`). Three is where a longer prefix
#: stops naming the act and starts naming its target, which is the part a grant must not
#: be scoped to.
_PREFIX_WORDS = 3

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


def strip_comments(command: str) -> str:
    """``command`` with its shell comments removed.

    A comment changes nothing about what runs — it is text addressed to whoever *reads*
    the command, which is precisely why it must not ride along into a prompt: it is the
    one part of a command whose author is writing to the reviewer rather than to the
    shell. Dropped off the grammar's own `comment` nodes rather than by cutting at `#`,
    since a `#` inside a quoted argument or a URL fragment is not a comment.
    """
    encoded = command.encode()
    spans: list[tuple[int, int]] = []
    _collect_comments(_PARSER.parse(encoded).root_node, spans)
    for start, end in sorted(spans, reverse=True):
        encoded = encoded[:start] + encoded[end:]
    text = encoded.decode(errors="replace")
    return "\n".join(line.rstrip() for line in text.splitlines()).strip()


def _collect_comments(node: Node, into: list[tuple[int, int]]) -> None:
    if node.type == "comment":
        into.append((node.start_byte, node.end_byte))
        return
    for child in node.children:
        _collect_comments(child, into)


def command_prefix(command: str) -> tuple[str, ...] | None:
    """The leading words that name what ``command`` does, or None when it cannot be read.

    The program plus the non-flag words in front of its first flag, capped — `uv run
    pytest`, `git commit`, `brew install`. It is what a standing permission can be scoped
    to without being scoped to one invocation: `pytest tests/test_a.py` and `pytest
    tests/test_b.py` are the same act on different targets, and an operator saying "stop
    asking about this" means the act.

    None where nothing may be inferred: a command with an unbounded construct in it (the
    word that decides the act may be the one we could not read) and one with no command
    this file can name. A pipeline answers for its *first* command only — the caller that
    has to hold every stage to a scope walks :attr:`ShellReach.commands` itself.
    """
    reach = shell_reach(command, root=None)
    if reach.unbounded or not reach.commands:
        return None
    first = reach.commands[0]
    words = [first.program]
    for argument in first.arguments:
        if is_flag(argument) or len(words) >= _PREFIX_WORDS:
            break
        words.append(argument)
    return tuple(words)


def _literal(node: Node) -> str | None:
    """The fixed text of an argument node, or None when it is decided at run time.

    "Decided at run time" covers two kinds of node and not one. The obvious kind is a
    substitution — `"$HOME/foo"` is not `"foo"`, and telling the two apart is exactly what
    a regex cannot do. The other is a word the *shell itself* rewrites before the program
    sees it: a brace, a glob, a bracket class or a backslash escape. Both arrive here as
    None, because in both cases the text on the command line is not the value.
    """
    if node.type in _LITERAL:
        text = node.text.decode(errors="replace") if node.text else ""
        if node.type == "raw_string":
            # Single quotes suppress every expansion there is, so the text between them is
            # the value however it is spelled.
            return text[1:-1]
        return None if _expands(text, _EXPANDED_UNQUOTED) else text
    if node.type == "string":
        if any(child.type in _DYNAMIC for child in node.children):
            return None
        text = node.text.decode(errors="replace") if node.text else ""
        return None if _expands(text, _EXPANDED_IN_QUOTES) else text.strip('"')
    if node.type == "concatenation":
        parts = [_literal(child) for child in node.children]
        if any(part is None for part in parts):
            return None
        return "".join(part for part in parts if part is not None)
    return None


def _expands(text: str, characters: frozenset[str]) -> bool:
    """Whether the shell would still do something to ``text`` before passing it on."""
    return any(character in text for character in characters)


def _unreadable(node: Node) -> str:
    """Why this node's text is not a value, in the words the refusal is written in.

    The distinction is worth making because the two answers point at different fixes: a
    construct we have no rule for is a gap in this module, and a word the shell would
    rewrite is a command that has to be spelled plainly before anything can vouch for it.
    """
    text = node.text.decode(errors="replace") if node.text else ""
    if _expands(text, _EXPANDED_UNQUOTED):
        return "a word the shell would expand or unescape"
    return f"an argument of a kind not read here ({node.type})"


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
        #
        # Read off the grammar's own `destination` field rather than by scanning the
        # children for one that happens to be literal: the redirect operator and a leading
        # file descriptor are children too, and a walk that skipped whatever it could not
        # read would record `> $OUT` and `> {a,b}` as redirects to nowhere.
        target = node.child_by_field_name("destination")
        if target is None:
            self.unbounded.append(f"a redirect with no destination to read ({node.type})")
            return
        if target.type in _DYNAMIC:
            self.unbounded.append(_DYNAMIC[target.type])
            return
        value = _literal(target)
        if value is None:
            self.unbounded.append(_unreadable(target))
            return
        self._path(value, self.writes)

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
            self.unbounded.append(_unreadable(node))
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
