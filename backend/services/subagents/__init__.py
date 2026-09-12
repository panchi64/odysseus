"""Sub-agents — autonomous agents the model launches, running on the ordinary engine.

The package is four small pieces and no machinery:

- ``spec.py`` — what a sub-agent *is*, as data.
- ``roster.py`` — the ones this installation ships with, and how a roster is merged and
  described to the model.
- ``definitions.py`` — the ones a *project* declares in its own files, read into the same
  record so nothing downstream can tell the two apart.
- ``launcher.py`` — the seam ``tools/`` resolves, implemented at the wiring layer.
- (the implementation itself lives in ``harness/manifests/_subagents.py``, where turn
  composition is reachable.)

What is deliberately absent is a run loop, a scheduler, a progress protocol, or a message
format of its own. A sub-agent is a conversation composed by the same ``compose_turn``
every other turn goes through; the shortness of this package is the evidence for that.
"""

from __future__ import annotations

from services.subagents.launcher import (
    LaunchedSubagent,
    SubagentLauncher,
    SubagentParent,
    SubagentUnavailableError,
    SubagentView,
)
from services.subagents.roster import (
    BUILTIN,
    EXPLORER,
    REVIEWER,
    TEST_RUNNER,
    WORKER,
    builtin_roster,
    describe_roster,
    merged_roster,
)
from services.subagents.spec import SubagentSpec, WorkspacePolicy

__all__ = [
    "BUILTIN",
    "EXPLORER",
    "REVIEWER",
    "TEST_RUNNER",
    "LaunchedSubagent",
    "SubagentLauncher",
    "SubagentParent",
    "SubagentSpec",
    "SubagentUnavailableError",
    "SubagentView",
    "WORKER",
    "WorkspacePolicy",
    "builtin_roster",
    "describe_roster",
    "merged_roster",
]
