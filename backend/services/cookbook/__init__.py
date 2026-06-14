"""The Cookbook capability — hardware detection + hardware-fit model recommendation.

`CookbookService` is the facade; the value types describe the host and the catalog.
Download/serve (the rest of the Cookbook) build on this package as they land.
"""

from __future__ import annotations

from .models import (
    Capabilities,
    CatalogModel,
    CompatibleModel,
    HardwareProfile,
    QuantVariant,
)
from .service import CookbookService

__all__ = [
    "Capabilities",
    "CatalogModel",
    "CompatibleModel",
    "CookbookService",
    "HardwareProfile",
    "QuantVariant",
]
