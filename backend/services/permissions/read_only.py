"""The claim the deterministic stage rests on: which programs only ever observe.

Split from ``judge.py`` because the two rot differently. The rule — what an allowlist
means and when it may be applied at all — changes when the policy changes. This table
changes when somebody re-reads a man page, and every row is a *claim about a program* that
a reader has to be able to check on its own. Keeping them together meant the claim was
skimmed as data on the way to the rule, and a claim nobody checks is how `sort -o out.txt`
came to be cleared as a read.

**What a row promises.** A program's entry lists the flags that would make it do something
other than observe and return — write a file, run another program, touch the host. An
**empty** set is the strongest claim in the file: *this program cannot do anything but
observe, however it is invoked*. A program whose other forms cannot be stated as a set of
flags is absent, and absent means escalate, not forbid.

**Why some obvious names are missing.** `sed` hides `-i` in a short-flag cluster, `awk`
writes from inside its own program text, `xargs` runs someone else's, `tar` extracts.
Three more were removed after being read properly: `date` sets the clock from a bare
operand on BSD, `hostname` sets the host name from one, and `uniq`'s *second operand is an
output file* — none of those is a flag, so no row here could state the rule, and a row that
states half a rule is worse than no row.
"""

from __future__ import annotations

from collections.abc import Mapping

#: Programs that only ever observe, each with the flags that would make it do otherwise.
#: An empty set means the program cannot do anything but observe, however it is invoked.
READ_ONLY_PROGRAMS: Mapping[str, frozenset[str]] = {
    # Pure computation over their arguments: no file is opened either way.
    "basename": frozenset(),
    "dirname": frozenset(),
    "echo": frozenset(),
    "false": frozenset(),
    "printf": frozenset(),
    "pwd": frozenset(),
    "readlink": frozenset(),
    "realpath": frozenset(),
    "true": frozenset(),
    "whoami": frozenset(),
    "id": frozenset(),
    "uname": frozenset(),
    # Read a file (or a directory) and write to stdout. None of them has an output-file
    # option, and none takes an operand that is a destination rather than a source.
    "cat": frozenset(),
    "cksum": frozenset(),
    "cmp": frozenset(),
    "column": frozenset(),
    "comm": frozenset(),
    "cut": frozenset(),
    "df": frozenset(),
    "diff": frozenset(),
    "du": frozenset(),
    "head": frozenset(),
    "ls": frozenset(),
    "md5sum": frozenset(),
    "nl": frozenset(),
    "sha1sum": frozenset(),
    "sha256sum": frozenset(),
    "shasum": frozenset(),
    "stat": frozenset(),
    # `-f/--file` reads its patterns from a file rather than writing one; where that file
    # may live is the containment check's question, not this table's.
    "grep": frozenset(),
    "jq": frozenset(),
    "tr": frozenset(),
    "wc": frozenset(),
    "which": frozenset(),
    # A follow (`-f`) blocks rather than writes, and the shell tool's own timeout bounds
    # it, so the read-only claim stands unqualified.
    "tail": frozenset(),
    # `-C` compiles the magic file it was given into a `.mgc` beside it.
    "file": frozenset({"-C", "--compile"}),
    # Everything `find` does beyond listing is one of these predicates, and they are exact
    # tokens rather than clustered short flags, so the denial is complete.
    "find": frozenset(
        {
            "-delete",
            "-exec",
            "-execdir",
            "-ok",
            "-okdir",
            "-fls",
            "-fprint",
            "-fprint0",
            "-fprintf",
        }
    ),
    # `--pre` runs a program of the caller's choosing once per file searched, which is
    # arbitrary execution wearing a search's clothes; `--hostname-bin` runs one to label
    # hyperlinks. `--pre-glob` only narrows `--pre`, and is listed so the row states the
    # whole mechanism rather than the half that is dangerous alone.
    "rg": frozenset({"--pre", "--pre-glob", "--hostname-bin"}),
    # `-o` writes its result to a file, and `--compress-program` hands a spill of temp
    # files to a program named on the command line. `-T` puts those temp files wherever it
    # is pointed, which is a write the path arguments never mention.
    "sort": frozenset({"-o", "--output", "--compress-program", "-T", "--temporary-directory"}),
}


#: Diff-family options that stop a reading subcommand from only reading: `--output` writes
#: the diff to a file, and `--ext-diff`/`--textconv` run the external drivers configured in
#: `.gitattributes` — programs whose names are in the repository, not in this command.
_GIT_DIFF_ACTIONS = frozenset({"--output", "--ext-diff", "--textconv"})

#: Programs where the *subcommand* is the act, each reading subcommand carrying the flags
#: that would stop it from only reading. `git` is the one that matters: it is the most-run
#: program in a code thread and most of what it does is read, but the same binary also
#: commits, pushes and resets.
#:
#: A flag **before** the subcommand is refused outright by the rule rather than enumerated
#: here — see ``judge.py``'s subcommand denial.
READ_ONLY_SUBCOMMANDS: Mapping[str, Mapping[str, frozenset[str]]] = {
    "git": {
        "blame": frozenset({"--textconv"}),
        # `--filters` and `--textconv` push the object through the repository's configured
        # clean/smudge filters, which are programs.
        "cat-file": frozenset({"--filters", "--textconv"}),
        "describe": frozenset(),
        "diff": _GIT_DIFF_ACTIONS,
        # `-O`/`--open-files-in-pager` opens every match in the configured pager, which is
        # a program the repository's own config may name.
        "grep": frozenset({"-O", "--open-files-in-pager", "--textconv"}),
        "log": _GIT_DIFF_ACTIONS,
        "ls-files": frozenset(),
        "ls-tree": frozenset(),
        "rev-parse": frozenset(),
        "shortlog": _GIT_DIFF_ACTIONS,
        "show": _GIT_DIFF_ACTIONS,
        "status": frozenset(),
    },
}
