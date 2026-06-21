"""The Cookbook capability — host hardware detection.

`CookbookService` is the facade; `HardwareProfile` (and its nested types) describe the
host. Download/serve (the rest of the Cookbook) build on this package as they land.
"""

from __future__ import annotations

from .models import HardwareProfile
from .service import CookbookService

__all__ = [
    "CookbookService",
    "HardwareProfile",
]
