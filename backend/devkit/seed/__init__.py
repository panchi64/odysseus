"""The fixture pack — what a seeded dev instance contains.

Importing this package is what registers the fixtures, so **a new fixture is a new module
plus one line here**. The version the launcher compares against is derived from these
files, so adding one also re-seeds existing workspaces on their next ``up`` without
anyone remembering to say so.

Order matters only in one place: :mod:`devkit.seed.base` binds a model, and nothing that
drives a conversation can run before it.
"""

from devkit.seed import base, conversations, surfaces  # noqa: F401 — imported to register
from devkit.seed.registry import SeedContext, run_seed, seed_version

__all__ = ["SeedContext", "run_seed", "seed_version"]
