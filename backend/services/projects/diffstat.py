"""Per-file rows for a branch diff, and the risk verdict on each one.

The merge gate is the one screen where the operator says yes to work they did not do,
and a fourteen-file patch offers no triage: a lockfile rewrite and a comment fix render
identically. So the diff comes back as **rows**, and every row already carries its
verdict — the category the path falls in, how much of a risk changing it is, and a short
phrase saying why.

**The verdict is computed here and nowhere else.** The frontend renders it; it must never
derive it, because then "is `uv.lock` a dependency change" would have two answers that
drift. The ordering is part of the verdict for the same reason — the list arrives sorted
by how much the operator should look at each row, so a client that renders it top to
bottom is already triaging.

Parsed from ``git diff --numstat -z`` joined to ``git diff --name-status -z``: git counts
the lines, and the patch itself may be megabytes. ``-z`` because a path is operator
content — a space, a quote or a non-ASCII byte in a filename must not shift a column.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

#: Ordering weight per risk band. Sorting is the server's verdict too, not the client's.
_RISK_ORDER = {"high": 0, "elevated": 1, "normal": 2}

#: Ordering weight per category, applied within a risk band so the three bands the merge
#: gate separates visually arrive already grouped.
_CATEGORY_ORDER = {
    "dependency": 0,
    "infrastructure": 1,
    "config": 2,
    "code": 3,
    "test": 4,
    "asset": 5,
    "docs": 6,
}

#: Exact filenames that declare what the project depends on. Changing one of these
#: changes what runs, not what the code says, which is why they outrank source.
_DEPENDENCY_NAMES = {
    "package.json",
    "package-lock.json",
    "bun.lock",
    "bun.lockb",
    "yarn.lock",
    "pnpm-lock.yaml",
    "npm-shrinkwrap.json",
    "pyproject.toml",
    "uv.lock",
    "poetry.lock",
    "pipfile",
    "pipfile.lock",
    "setup.py",
    "setup.cfg",
    "cargo.toml",
    "cargo.lock",
    "go.mod",
    "go.sum",
    "gemfile",
    "gemfile.lock",
    "composer.json",
    "composer.lock",
}

#: Exact filenames that describe how the thing is built, shipped or run.
_INFRA_NAMES = {
    "dockerfile",
    "containerfile",
    "makefile",
    "justfile",
    "procfile",
    "jenkinsfile",
    "vagrantfile",
    ".dockerignore",
    ".gitlab-ci.yml",
    "nginx.conf",
    "alembic.ini",
}

_INFRA_SUFFIXES = {".tf", ".tfvars", ".nomad", ".service"}

#: Path fragments that make a file infrastructure whatever it is called.
_INFRA_PARTS = (
    (".github", "workflows"),
    (".circleci",),
    ("migrations", "versions"),
    ("deploy",),
    ("k8s",),
    ("helm",),
    ("terraform",),
)

_CONFIG_SUFFIXES = {".ini", ".cfg", ".conf", ".toml", ".yaml", ".yml", ".properties", ".env"}

_DOC_SUFFIXES = {".md", ".mdx", ".rst", ".txt", ".adoc"}

_ASSET_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".webp",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
    ".mp3",
    ".mp4",
    ".pdf",
    ".zip",
}

#: Git's status letters, spelled out. A rename and a copy carry a similarity score after
#: the letter (``R100``), which is dropped — the score is git's confidence, not a fact
#: about the change, and the operator is being asked about the change.
_STATUS_WORDS = {
    "A": "added",
    "M": "modified",
    "D": "deleted",
    "R": "renamed",
    "C": "copied",
    "T": "type-changed",
    "U": "unmerged",
}


@dataclass(frozen=True)
class FileChange:
    """One file in a branch diff, with the verdict already rendered on it."""

    path: str
    #: Where a rename came from, else None. Named separately rather than folded into the
    #: path so the client can show the move without parsing an arrow out of a string.
    old_path: str | None
    status: str
    insertions: int
    deletions: int
    #: Git counted no lines because it could not read the file as text.
    binary: bool
    category: str
    risk: str
    #: The one-phrase reason for the band, authored here. The screen shows this verbatim.
    reason: str


def file_changes(numstat: str, name_status: str) -> list[FileChange]:
    """The per-file rows for one diff, classified and ordered.

    Both arguments are ``-z`` output for the *same* ref spec. Joined on the file's
    current path: a file git reported in one and not the other (it is generating both
    from one walk, so this should not happen) simply falls back to zero counts.
    """
    counts = _parse_numstat(numstat)
    rows = [
        _classify(path, old_path, status, *counts.get(path, (0, 0, False)))
        for path, old_path, status in _parse_name_status(name_status)
    ]
    rows.sort(
        key=lambda row: (
            _RISK_ORDER.get(row.risk, 9),
            _CATEGORY_ORDER.get(row.category, 9),
            -(row.insertions + row.deletions),
            row.path,
        )
    )
    return rows


def _parse_numstat(raw: str) -> dict[str, tuple[int, int, bool]]:
    """path → (insertions, deletions, binary).

    Records are ``ins\\tdel\\tpath\\0``, except a rename, which ends the record with an
    empty path and follows it with the old and new paths as two more NUL-terminated
    fields. A binary file reports ``-`` for both counts.
    """
    out: dict[str, tuple[int, int, bool]] = {}
    fields = raw.split("\0")
    index = 0
    while index < len(fields):
        field = fields[index]
        index += 1
        if "\t" not in field:
            continue
        added, removed, path = field.split("\t", 2)
        if path == "" and index + 1 < len(fields):
            index += 1  # the old path; the new one is what the row is keyed by
            path = fields[index]
            index += 1
        binary = added == "-" or removed == "-"
        out[path] = (_count(added), _count(removed), binary)
    return out


def _count(value: str) -> int:
    return int(value) if value.isdigit() else 0


def _parse_name_status(raw: str) -> list[tuple[str, str | None, str]]:
    """(path, old_path, status) per record. ``R``/``C`` carry two paths, not one."""
    rows: list[tuple[str, str | None, str]] = []
    fields = raw.split("\0")
    index = 0
    while index < len(fields):
        code = fields[index]
        index += 1
        if not code:
            continue
        status = _STATUS_WORDS.get(code[0], "modified")
        if code[0] in {"R", "C"} and index + 1 < len(fields):
            old_path, path = fields[index], fields[index + 1]
            index += 2
            rows.append((path, old_path, status))
        elif index < len(fields):
            rows.append((fields[index], None, status))
            index += 1
    return rows


def _classify(
    path: str,
    old_path: str | None,
    status: str,
    insertions: int,
    deletions: int,
    binary: bool,
) -> FileChange:
    category, reason = _category(path)
    risk, reason = _risk(category, status, reason)
    return FileChange(
        path=path,
        old_path=old_path,
        status=status,
        insertions=insertions,
        deletions=deletions,
        binary=binary,
        category=category,
        risk=risk,
        reason=reason,
    )


def _category(path: str) -> tuple[str, str]:
    """Which band a path falls in, and the phrase that says why."""
    parts = PurePosixPath(path).parts
    name = parts[-1].lower() if parts else path.lower()
    suffix = PurePosixPath(name).suffix

    if name in _DEPENDENCY_NAMES or name.startswith("requirements"):
        return "dependency", "declares what the project depends on"
    if (
        name in _INFRA_NAMES
        or suffix in _INFRA_SUFFIXES
        or name.startswith(("dockerfile.", "docker-compose", "compose."))
        or _is_infra_path(parts)
    ):
        return "infrastructure", "changes how the project is built or run"
    if _is_test(parts, name):
        return "test", "test code"
    if suffix in _DOC_SUFFIXES or (parts and parts[0] in {"docs", "doc"}):
        return "docs", "documentation"
    if suffix in _ASSET_SUFFIXES:
        return "asset", "a static asset"
    if name.startswith(".env") or suffix in _CONFIG_SUFFIXES or _is_rc(name):
        return "config", "configuration the whole project reads"
    if _is_config_script(name):
        return "config", "configuration the whole project reads"
    return "code", "source"


def _is_infra_path(parts: tuple[str, ...]) -> bool:
    lowered = tuple(part.lower() for part in parts[:-1])
    return any(all(fragment in lowered for fragment in group) for group in _INFRA_PARTS)


def _is_test(parts: tuple[str, ...], name: str) -> bool:
    if any(part.lower() in {"tests", "test", "__tests__", "spec"} for part in parts[:-1]):
        return True
    stem = PurePosixPath(name).stem
    return (
        name.startswith("test_")
        or stem.endswith("_test")
        or ".test." in name
        or ".spec." in name
        or name == "conftest.py"
    )


def _is_rc(name: str) -> bool:
    """A dotfile that configures a tool — ``.eslintrc``, ``.prettierrc.json``, ``.npmrc``."""
    if not name.startswith(".") or name.count(".") < 1:
        return False
    return name.split(".")[1].endswith("rc")


def _is_config_script(name: str) -> bool:
    """A build/tool config that happens to be written in a programming language —
    ``vite.config.ts``, ``tailwind.config.js``. The suffix says source; the name says
    configuration, and the name is the one that matters at a merge gate."""
    return ".config." in name or name in {"tsconfig.json", "jsconfig.json"}


def _risk(category: str, status: str, reason: str) -> tuple[str, str]:
    """The band, and the reason sharpened by what happened to the file.

    A deletion never sits at ``normal``: "was this used?" is the question the merge gate
    exists to raise, and a file that is gone cannot raise it for itself.
    """
    high = category in {"dependency", "infrastructure"}
    if status == "deleted":
        if category == "dependency":
            return "high", "deleted — a dependency manifest is gone"
        if category == "infrastructure":
            return "high", "deleted — part of how the project is built or run is gone"
        return "elevated", "deleted — check nothing still reaches for it"
    if high:
        return "high", reason
    if category == "config":
        return "elevated", reason
    return "normal", reason
