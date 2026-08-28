"""Backup & restore (`BACKUP-1`, `BACKUP-2`).

Three parts, deliberately separable:

- ``manifest`` — *what* goes in a backup, discovered from the ``__backup__`` markers the
  entities carry, so nothing central has to be edited when a feature adds a table.
- ``envelope`` — *the file*: one JSON envelope whose payload is sealed under a separate,
  operator-supplied backup secret, portable to any other host.
- ``service`` — *the work*: gather and open, seal and write; merge on import without
  duplicating, stamping every incoming record with the importing operator's id.
"""

from .envelope import BackupFormatError, BackupSecretError
from .manifest import BackupEntity, discover_entities, sections
from .service import (
    BackupImportReport,
    BackupManifest,
    BackupManifestItem,
    BackupPayloadError,
    BackupService,
)

__all__ = [
    "BackupEntity",
    "BackupFormatError",
    "BackupImportReport",
    "BackupManifest",
    "BackupManifestItem",
    "BackupPayloadError",
    "BackupSecretError",
    "BackupService",
    "discover_entities",
    "sections",
]
