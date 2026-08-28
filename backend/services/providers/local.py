"""Serving-managed local endpoints — the Cookbook's own engines.

Wire-identical to ``openai-compatible`` (every local engine serves the OpenAI
protocol on loopback); a distinct provider so the operator-facing surfaces can tell
"a server I pointed at" from "a model this app serves", and so a managed endpoint
never asks for a key. Created only by ``services/serving`` (``managed=True``), never
offered as a manual choice with a base-URL preset.
"""

from __future__ import annotations

from services.providers.base import ProviderPreset
from services.providers.openai_compat import OpenAICompatProvider


class LocalProvider(OpenAICompatProvider):
    id = "local"
    display_name = "Local (managed)"
    requires_key = False
    preset = ProviderPreset(
        default_base_url=None,
        key_hint=None,
        docs_url=None,
    )


PROVIDER = LocalProvider()
