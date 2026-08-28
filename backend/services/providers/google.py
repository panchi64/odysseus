"""Google — native adapter over Pydantic AI's ``GoogleModel`` (Gemini API).

Talks the Gemini generateContent protocol directly through ``google-genai`` instead
of the OpenAI-compat shim, so native tool use and thinking budgets work as Google
defines them.
"""

from __future__ import annotations

import httpx
from pydantic_ai.models import Model
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google import GoogleProvider as _SdkProvider
from pydantic_ai.settings import ModelSettings

from core.exceptions import DegradedCapabilityError
from services.llm import EndpointSpec
from services.providers.base import ProviderPreset
from services.reasoning import ModelDescriptor

_DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com"
_TIMEOUT = httpx.Timeout(8.0, connect=3.0)


def _models_url(base_url: str) -> str:
    root = base_url.rstrip("/")
    if not root.endswith("/v1beta"):
        root += "/v1beta"
    return root + "/models"


class GoogleNativeProvider:
    id = "google"
    display_name = "Google"
    requires_key = True
    preset = ProviderPreset(
        default_base_url=_DEFAULT_BASE_URL,
        key_hint="AIza…",
        docs_url="https://aistudio.google.com/apikey",
        vision=True,
    )

    def build_model(self, spec: EndpointSpec) -> Model:
        base_url = spec.base_url if spec.base_url.rstrip("/") != _DEFAULT_BASE_URL else None
        provider = _SdkProvider(api_key=spec.api_key or "", base_url=base_url)
        return GoogleModel(spec.model, provider=provider)

    async def discover(
        self, base_url: str, api_key: str | None, *, client: httpx.AsyncClient | None = None
    ) -> list[str]:
        try:
            payload = await self._list_models(base_url, api_key, client=client)
        except (httpx.HTTPError, ValueError) as exc:
            raise DegradedCapabilityError(
                f"could not list models from {base_url!r}: {exc}"
            ) from exc
        models = payload.get("models") if isinstance(payload, dict) else None
        if not isinstance(models, list):
            raise DegradedCapabilityError(
                f"{base_url!r} returned an unrecognized models payload"
            )
        # Gemini names come as "models/<id>" — the stored/served id is the bare one.
        ids = [
            row["name"].removeprefix("models/")
            for row in models
            if isinstance(row, dict) and isinstance(row.get("name"), str) and row["name"]
        ]
        return sorted(dict.fromkeys(i for i in ids if i))

    async def probe(
        self, base_url: str, api_key: str | None, *, client: httpx.AsyncClient | None = None
    ) -> None:
        await self._list_models(base_url, api_key, client=client)

    async def _list_models(
        self, base_url: str, api_key: str | None, *, client: httpx.AsyncClient | None = None
    ) -> object:
        headers = {"x-goog-api-key": api_key} if api_key else {}
        http = client or httpx.AsyncClient(follow_redirects=True)
        try:
            response = await http.get(
                _models_url(base_url), headers=headers, timeout=_TIMEOUT
            )
            response.raise_for_status()
            return response.json()
        finally:
            if client is None:
                await http.aclose()

    def reasoning_off(self, descriptor: ModelDescriptor) -> ModelSettings:
        # Only the Flash/Lite family accepts a zero thinking budget; Pro enforces a
        # floor and rejects 0, so an unrecognized Gemini is left to think.
        model_id = descriptor.model_id.lower()
        if "flash" in model_id or "lite" in model_id:
            return {"google_thinking_config": {"thinking_budget": 0}}
        return {}


PROVIDER = GoogleNativeProvider()
