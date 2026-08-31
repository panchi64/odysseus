"""The permission axis: what a level is (:mod:`levels`), what it rules (:mod:`decide`),
and — at the one level whose meaning is that the operator's answers are given for them —
what an action would do (:mod:`capability`, :mod:`shell_ast`) and who says so
(:mod:`judge`, :mod:`reviewer`). Imported through the package, so a caller names one home
for all of it."""

from services.permissions.capability import ActionKind, Capability, capability_of
from services.permissions.decide import (
    Decision,
    ReviewOutcome,
    ReviewStage,
    blocked_message,
    decide,
    review,
    review_refusal,
)
from services.permissions.judge import Judgement, judge
from services.permissions.levels import (
    DEFAULT_PERMISSION,
    PERMISSION_LEVELS,
    PERMISSIONS,
    PLANNING_TOOLS,
    STRICTEST_PERMISSION,
    ApprovalPolicy,
    PermissionLevel,
    PermissionSpec,
    WriteScope,
    beyond_scope,
    permission_level,
    permission_spec,
    tools_beyond_scope,
)
from services.permissions.reviewer import (
    Reviewer,
    ReviewRequest,
    ReviewVerdict,
    make_utility_reviewer,
    review_transcript,
)
from services.permissions.shell_ast import ShellCommand

__all__ = [
    "DEFAULT_PERMISSION",
    "PERMISSIONS",
    "PERMISSION_LEVELS",
    "PLANNING_TOOLS",
    "STRICTEST_PERMISSION",
    "ActionKind",
    "ApprovalPolicy",
    "Capability",
    "Decision",
    "Judgement",
    "PermissionLevel",
    "PermissionSpec",
    "ReviewOutcome",
    "ReviewRequest",
    "ReviewStage",
    "ReviewVerdict",
    "Reviewer",
    "ShellCommand",
    "WriteScope",
    "beyond_scope",
    "blocked_message",
    "capability_of",
    "decide",
    "judge",
    "make_utility_reviewer",
    "permission_level",
    "permission_spec",
    "review",
    "review_refusal",
    "review_transcript",
    "tools_beyond_scope",
]
