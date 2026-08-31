"""The deterministic stage: what it reads off a command, and what it refuses to vouch for.

Three halves, tested apart because they fail apart. The **extraction** says what a command
would reach; the **allowlist** claims which programs only observe; the **judge** applies
one to the other. A bug in the first is a command described as less than it is, and a bug
in the second is a promise about a program that its man page does not make — both of them
failures the third cannot catch, so most of what is pinned here is the extraction refusing
to describe and the table's exceptions actually biting, rather than the judge refusing to
approve.

Every "not approved" below is an *escalation*, never a refusal: the call goes to the model
reviewer. That is what makes the allowlist affordable to keep narrow, and it is why the
tests are written as "this does not pass the cheap stage" rather than "this is forbidden".
"""

from __future__ import annotations

from pathlib import Path

import pytest

from services.permissions.capability import ActionKind, capability_of, shell_capability
from services.permissions.judge import judge
from services.permissions.read_only import READ_ONLY_PROGRAMS, READ_ONLY_SUBCOMMANDS

ROOT = Path("/tmp/odysseus-judge-workspace")


def cleared(command: str, *, root: Path | None = ROOT) -> bool:
    return judge(shell_capability("shell_run_command", command, root=root)).approved


def reason(command: str, *, root: Path | None = ROOT) -> str:
    return judge(shell_capability("shell_run_command", command, root=root)).reason


class TestWhatTheWalkReads:
    """The extraction, on its own — before any policy is applied to it."""

    def test_a_pipeline_is_every_command_in_it(self):
        capability = shell_capability("shell_run_command", "git diff | head -20", root=ROOT)
        assert capability.programs == ("git", "head")
        assert capability.commands[0].arguments == ("diff",)
        assert capability.commands[1].arguments == ("-20",)
        assert capability.bounded

    def test_a_redirect_is_a_write_even_when_it_reads(self):
        # `< file` only reads, and is still recorded as a write. Calling a read a write
        # can only escalate; the reverse mistake cannot be made safe afterwards.
        assert shell_capability("shell_run_command", "ls > out.txt", root=ROOT).writes == (
            "out.txt",
        )
        assert shell_capability("shell_run_command", "wc -l < in.txt", root=ROOT).writes == (
            "in.txt",
        )

    def test_an_assignment_is_recorded_against_the_command_it_prefixes(self):
        capability = shell_capability("shell_run_command", "LD_PRELOAD=x ls", root=ROOT)
        assert capability.env_writes == ("LD_PRELOAD",)
        assert capability.programs == ("ls",)

    def test_only_arguments_that_could_leave_the_directory_count_as_paths(self):
        # A bare word is at worst a file beside the ones already there. Recording every
        # one as a read would bury the arguments that matter under a page of patterns.
        capability = shell_capability("shell_run_command", "grep -rn needle src", root=ROOT)
        assert capability.reads == ()
        assert shell_capability("shell_run_command", "cat src/a.py", root=ROOT).reads == (
            "src/a.py",
        )

    def test_a_url_is_read_as_network_reach_and_not_as_a_path(self):
        capability = shell_capability("shell_run_command", "curl https://example.com", root=ROOT)
        assert capability.network
        assert capability.reads == ()

    def test_a_quoted_literal_is_a_literal_and_an_interpolated_one_is_not(self):
        assert shell_capability("shell_run_command", 'cat "a.txt"', root=ROOT).bounded
        assert not shell_capability("shell_run_command", 'cat "$HOME/a.txt"', root=ROOT).bounded

    @pytest.mark.parametrize(
        "command",
        [
            "grep --file=/etc/passwd foo",  # a long flag's value, after its `=`
            "grep -f/etc/passwd foo",  # a short flag's value, glued to the letter
            "grep -f /etc/passwd foo",  # ...and standing on its own, as an operand
        ],
    )
    def test_a_path_attached_to_a_flag_is_still_a_path(self, command):
        # The reading a flag hides behind. A walk that skipped every word starting with
        # `-` saw `--output=/Users/me/.ssh/authorized_keys` as no path at all.
        capability = shell_capability("shell_run_command", command, root=ROOT)
        assert capability.escapes == ("/etc/passwd",)

    def test_a_flag_that_carries_no_path_still_names_none(self):
        # The other half: `-rn`, `-20` and `--oneline` must not become paths, or every
        # ordinary read would escalate on its own flags.
        for command in ("grep -rn needle src", "git log --oneline -20", "ls -la"):
            assert shell_capability("shell_run_command", command, root=ROOT).reads == ()


class TestUnknownShapesEscalate:
    """The rule the whole design rests on: what was not read is never treated as absent."""

    @pytest.mark.parametrize(
        "command",
        [
            "if true; then ls; fi",  # a conditional
            "for f in *; do cat $f; done",  # a loop
            "(cd /tmp && ls)",  # a subshell
            "ls() { rm -rf /; }",  # a function definition
            "cat <<'EOF'\nx\nEOF",  # a heredoc
        ],
    )
    def test_a_construct_with_no_rule_is_recorded_rather_than_skipped(self, command):
        capability = shell_capability("shell_run_command", command, root=ROOT)
        assert not capability.bounded
        assert not judge(capability).approved

    @pytest.mark.parametrize(
        "command",
        [
            "echo $HOME",
            "ls ${DIR}",
            "ls $(cat targets)",
            "cat <(ls)",
            "echo $((1 + 1))",
        ],
    )
    def test_a_value_decided_at_run_time_is_never_interpolated_away(self, command):
        # The single most tempting shortcut — "it is probably a path in the workspace" —
        # and the one that turns the allowlist into decoration.
        assert not shell_capability("shell_run_command", command, root=ROOT).bounded
        assert not cleared(command)

    def test_a_program_name_assembled_at_run_time_is_not_a_command(self):
        capability = shell_capability("shell_run_command", "$TOOL --version", root=ROOT)
        assert capability.programs == ()
        assert not capability.bounded

    def test_an_environment_assignment_never_passes(self):
        # `LD_PRELOAD=… ls` is not `ls`, and the set of variables that change what a
        # program does is open-ended enough that enumerating them is a losing game.
        assert not cleared("LD_PRELOAD=/tmp/x.so ls")
        assert "LD_PRELOAD" in reason("LD_PRELOAD=/tmp/x.so ls")

    def test_a_command_that_does_not_parse_is_read_as_unparsed(self):
        # tree-sitter recovers rather than raising, so a broken command comes back as a
        # tree with error nodes — which must be seen, not walked past.
        assert not shell_capability("shell_run_command", "ls |", root=ROOT).bounded


class TestTheAllowlist:
    """What actually clears without a model call."""

    @pytest.mark.parametrize(
        "command",
        [
            "ls -la",
            "pwd",
            "cat src/main.py",
            "grep -rn needle src",
            "find . -name '*.py'",
            "wc -l src/main.py",
            "git status",
            "git diff | head -20",
            "git log --oneline -20",
            "ls src && ls tests",
            "cat a.txt # a comment",
        ],
    )
    def test_the_ordinary_reads_of_a_code_thread_cost_nothing(self, command):
        assert cleared(command)

    @pytest.mark.parametrize(
        "command",
        [
            "rm -rf build",
            "git commit -m wip",
            "git push",
            "npm install",
            "python -c 'print(1)'",
            "sed -i s/a/b/ f.txt",
            "awk '{print > \"out\"}' f.txt",
            "xargs rm < list",
            "chmod +x run.sh",
        ],
    )
    def test_anything_that_could_change_something_escalates(self, command):
        assert not cleared(command)

    def test_a_writing_flag_disqualifies_an_otherwise_reading_program(self):
        assert cleared("find . -name x")
        assert not cleared("find . -delete")
        assert not cleared("find . -exec rm {} ;")

    @pytest.mark.parametrize(
        ("program", "flag"),
        [
            (program, flag)
            for program, flags in sorted(READ_ONLY_PROGRAMS.items())
            for flag in sorted(flags)
        ],
    )
    def test_every_exception_the_table_claims_is_one_it_enforces(self, program, flag):
        # A test per row, derived from the row rather than restating it: an entry whose
        # denial set is decoration — a flag nothing matches, a program whose set was
        # emptied — is a program the stage would clear while promising it could not.
        assert not cleared(f"{program} {flag} x")

    @pytest.mark.parametrize(
        ("subcommand", "flag"),
        [
            (subcommand, flag)
            for subcommand, flags in sorted(READ_ONLY_SUBCOMMANDS["git"].items())
            for flag in sorted(flags)
        ],
    )
    def test_a_reading_subcommand_has_its_own_exceptions(self, subcommand, flag):
        # `git log` reads, and `git log --ext-diff` runs whatever the repository's own
        # config names — so the subcommand allowlist needs the same per-entry denial the
        # program allowlist has, or being a reading subcommand is where the check stops.
        assert cleared(f"git {subcommand}")
        assert not cleared(f"git {subcommand} {flag} x")

    def test_a_denied_flag_cannot_be_smuggled_past_by_spelling(self):
        # `-o`, `-oout.txt` and `--output=out.txt` are one flag written three ways. A
        # table matched against raw tokens states a rule about the first and none at all
        # about the other two.
        for command in ("sort -o out", "sort -oout", "sort --output out", "sort --output=out"):
            assert not cleared(command)

    def test_a_subcommand_program_is_cleared_on_its_subcommand(self):
        assert cleared("git show HEAD")
        assert not cleared("git reset --hard")
        # No subcommand at all is not a read — it is a form this stage has no rule for.
        assert not cleared("git --version")

    @pytest.mark.parametrize(
        "command",
        [
            "git --git-dir=other/.git log",  # a repository that is not this one
            "git --exec-path=bin log",  # the binaries git itself runs
            "git -c core.pager=x log",  # the config the subcommand obeys
            "git -C src status",  # the directory the whole thing happens in
            "git --no-pager log",  # harmless, and indistinguishable from the rest
        ],
    )
    def test_nothing_is_read_past_a_flag_before_the_subcommand(self, command):
        # Every one of these stays inside the workspace, so containment says nothing about
        # them: what refuses them is the rule that a global flag redirects the act, and
        # that a global flag taking a separate value moves where the subcommand even sits.
        assert not cleared(command)

    @pytest.mark.parametrize(
        "command",
        [
            "date -s 2020-01-01",  # a bare operand sets the clock on BSD
            "hostname newhost",  # ...and here too
            "uniq in.txt out.txt",  # the second operand is an output file
        ],
    )
    def test_a_program_whose_writing_form_is_not_a_flag_is_not_on_the_list(self, command):
        # The table can only state a rule about flags, so a program that writes from an
        # operand cannot be described by one — and half a rule is worse than no row.
        assert not cleared(command)
        assert "not on the read-only list" in reason(command)

    def test_a_path_qualified_invocation_is_not_the_allowlisted_program(self):
        # `/bin/ls` and `./ls` are different binaries as far as the name says, and the
        # containment check has already had its say about the path.
        assert not cleared("/bin/ls")
        assert not cleared("./ls")


class TestContainment:
    """Where a path may land, measured against the run's workspace."""

    @pytest.mark.parametrize(
        "command",
        [
            "cat ../../../etc/passwd",
            "cat /etc/passwd",
            "cat ~/.ssh/id_rsa",
            "ls ~",
        ],
    )
    def test_a_read_that_leaves_the_workspace_escalates(self, command):
        assert not cleared(command)

    def test_home_is_refused_rather_than_resolved(self):
        # `~` is the operator's own directory by definition, so a command naming it is
        # reaching past the workspace whatever the rest of the path says — and resolving
        # it would only ask about a directory this process may not even share.
        capability = shell_capability("shell_run_command", "cat ~/notes.md", root=ROOT)
        assert capability.escapes == ("~/notes.md",)

    def test_with_no_workspace_an_absolute_path_reads_as_having_left(self):
        # There is nothing to measure against, and "we could not tell" has to read the
        # same as "it left". A plain relative read is still fine.
        assert not cleared("cat /etc/passwd", root=None)
        assert not cleared("cat ../outside.txt", root=None)
        assert cleared("cat notes.md", root=None)


class TestTheOtherKindsOfAction:
    """Everything that is not a shell command, and why none of it clears."""

    def test_only_a_shell_command_can_be_cleared_at_all(self):
        for tool, args in (
            ("mail_send", {"to": "a@b.c", "subject": "hi"}),
            ("vault_get_entry", {"name": "bank"}),
            ("external_notion_create_page", {"title": "x"}),
            ("files_write_file", {"path": "a.txt", "content": "x"}),
        ):
            assert not judge(capability_of(tool, args, root=ROOT)).approved

    def test_an_interpreter_program_is_not_bounded_by_its_arguments(self):
        capability = capability_of("code_execute", {"code": "print(1)"}, root=ROOT)
        assert capability.kind is ActionKind.OPAQUE
        assert not capability.bounded
        # ...but the bash form is a command line, and reads like one.
        assert capability_of(
            "code_execute", {"code": "ls -la", "language": "bash"}, root=ROOT
        ).kind is ActionKind.SHELL

    def test_a_tool_whose_effect_is_its_own_is_never_called_fully_read(self):
        # `bounded` promises that the fields beside it describe the *whole* act. For a
        # tool whose effect is not written in its arguments they describe none of it, so
        # an empty `unbounded` there would be the extraction claiming a completeness it
        # has no basis for — the one mistake this module exists to avoid.
        capability = capability_of("mail_send", {"to": "a@b.c"}, root=ROOT)
        assert capability.kind is ActionKind.OPAQUE
        assert not capability.bounded

    def test_an_external_call_is_named_by_its_keys_and_never_its_values(self):
        capability = capability_of(
            "external_notion_create_page", {"token": "hunter2", "title": "x"}, root=ROOT
        )
        assert "hunter2" not in capability.summary
        assert "token" in capability.summary

    def test_a_file_write_is_its_resolved_target(self):
        capability = capability_of("files_write_file", {"path": "src/a.py"}, root=ROOT)
        assert capability.writes == ("src/a.py",)
        assert capability.escapes == ()
        assert capability_of("files_write_file", {"path": "/etc/hosts"}, root=ROOT).escapes


class TestTheTablesStayHonest:
    """The allowlist is a claim about programs, and a claim can rot."""

    def test_no_program_is_on_both_tables(self):
        # A program whose subcommand decides is not also a program that always reads;
        # listing it twice would make one of the two rules unreachable and silent.
        assert not set(READ_ONLY_PROGRAMS) & set(READ_ONLY_SUBCOMMANDS)

    def test_every_denied_flag_is_a_flag(self):
        # A "writing flag" that does not start with `-` could never match an argument,
        # so it would read as a guarantee while doing nothing.
        denials = [*READ_ONLY_PROGRAMS.values()]
        denials += [flags for by_subcommand in READ_ONLY_SUBCOMMANDS.values()
                    for flags in by_subcommand.values()]
        for flags in denials:
            assert all(flag.startswith("-") for flag in flags)
