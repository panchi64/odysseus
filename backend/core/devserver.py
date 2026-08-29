"""Auto-reload knowledge, in one place.

The development reloader watches the working directory for ``*.py``, and two directories
under it hold **runtime state, not source**: ``data/`` (the DB, uploads, corpus files, the
sandbox workspace, the browser profile — anything the running app writes for itself) and
``.venv``. A run that writes ``*.py`` into either — an upload, a file the agent creates in
its workspace, a ``uv sync`` — tears the server down *in the middle of the work that
caused it*, and the operator sees ``Shutting down`` with no error attached to the thing
that died.

``dev.py`` starts uvicorn with the exclusions this module builds. Plain
``uvicorn app:app --reload`` does not, which is why the app also asks this module whether
it was started that way — the flag is muscle memory and lives in everyone's shell history,
and the failure it causes looks nothing like its cause.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from pathlib import Path

# The message the app logs when it finds itself under an unguarded reloader. Here rather
# than at the call site so the fix and the warning about its absence stay in step.
UNGUARDED_RELOAD_WARNING = (
    "auto-reload is watching runtime state: anything the app writes under %s will "
    "restart this server mid-request, which looks like the work dying for no reason. "
    "Start the dev server with `uv run python dev.py` instead."
)


def reload_excludes(data_dir: Path, root: Path) -> list[str]:
    """Absolute paths of directories the reloader must ignore, as uvicorn wants them.

    Both properties are load-bearing, for different reasons:

    *Absolute*, because uvicorn only matches an exclusion against a changed file's parent
    directories when the entry resolves to a directory; a relative entry is kept as a
    filename glob and matches nothing.

    *Existing*, because that is how uvicorn decides which of the two it has. An absolute
    path to a directory that isn't there yet falls back to the glob branch — and an
    absolute glob is not merely useless there: ``Path.match`` rejects a non-relative
    pattern outright on Python 3.14, so the reloader would raise on the first file change
    instead of quietly ignoring the entry. Dropping the missing ones keeps the list honest
    in both directions.
    """
    candidates = (data_dir, root / ".venv")
    return [str(path) for path in candidates if path.is_dir()]


def _flag_values(argv: Iterable[str], flag: str) -> Iterator[str]:
    """Every value given to ``flag``, in both ``--flag value`` and ``--flag=value`` form."""
    argv = list(argv)
    for index, arg in enumerate(argv):
        if arg == flag and index + 1 < len(argv):
            yield argv[index + 1]
        elif arg.startswith(f"{flag}="):
            yield arg.split("=", 1)[1]


def reload_watches_runtime_state(argv: list[str], data_dir: Path) -> bool:
    """Whether this process runs under a reloader that still watches ``data_dir``.

    Keyed on ``--reload`` being on the *command line*, which is exactly the distinction
    that matters: ``dev.py`` enables reload programmatically, so the flag's presence means
    someone bypassed it.

    An explicit ``--reload-exclude`` covering the data directory clears the warning — but
    only an absolute one, because a relative exclusion is silently ignored by uvicorn and
    protects nothing. Warning about a relative exclusion is the point, not a false alarm.
    """
    if "--reload" not in argv:
        return False
    for raw in _flag_values(argv, "--reload-exclude"):
        excluded = Path(raw)
        if excluded.is_absolute() and (excluded == data_dir or excluded in data_dir.parents):
            return False
    return True
