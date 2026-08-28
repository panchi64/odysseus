"""Shared response-model base for surfaces whose JSON is camelCase.

Several frontend seams expect camelCase keys (e.g. ``docCount``, ``createdAt``). One
base config — ``alias_generator=to_camel`` with ``populate_by_name=True`` so the model
still builds from snake_case attribute names — keeps that convention in one place rather
than redefined per router.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
