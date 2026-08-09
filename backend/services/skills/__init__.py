"""Skills — reusable know-how the agent applies to future tasks (`SKILL-1`…`SKILL-3`).

Two pieces: :mod:`services.skills.bundle` is the pure Agent Skills format layer (parse,
validate, render, zip), and :mod:`services.skills.store` persists bundles sealed at rest and
serves them to the REST surface and the agent's toolset.
"""

from .bundle import (
    BUNDLE_MAX_BYTES,
    SKILL_FILE,
    SPEC_FIELDS,
    ImportedBundle,
    ParsedSkill,
    parse_skill_md,
    read_bundle,
    read_import,
    render_skill_md,
    validate_description,
    validate_name,
    write_bundle,
)
from .store import (
    SkillCatalogEntry,
    SkillFileView,
    SkillStore,
    SkillSummaryView,
    SkillView,
)

__all__ = [
    "BUNDLE_MAX_BYTES",
    "SKILL_FILE",
    "SPEC_FIELDS",
    "ImportedBundle",
    "ParsedSkill",
    "SkillCatalogEntry",
    "SkillFileView",
    "SkillStore",
    "SkillSummaryView",
    "SkillView",
    "parse_skill_md",
    "read_bundle",
    "read_import",
    "render_skill_md",
    "validate_description",
    "validate_name",
    "write_bundle",
]
