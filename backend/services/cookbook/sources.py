"""Live catalog sources — HuggingFace (authoritative spine) + OpenRouter (capability
overlay).

HuggingFace is the only source with reliable per-quant byte sizes — the numbers the
hardware-fit math needs — so it is the spine: list trending GGUF/MLX models, dedupe
the quant-fork noise by ``base_model`` lineage, and read exact sizes from the repo
file tree. OpenRouter's public models API then supplies clean capability flags
(tool-calling / reasoning / vision), exact-joined to HF via ``hugging_face_id`` — a
production endpoint, unlike the single-maintainer community catalogs. Where OpenRouter
doesn't cover a model, capabilities fall back to HF metadata heuristics.

Everything here is best-effort over plain ``httpx``: parse defensively, and let the
caller (``catalog.py``) handle caching, serve-stale, and degrade.
"""

from __future__ import annotations

import asyncio
import logging
import re

import httpx

from .models import Capabilities, CatalogModel, QuantVariant

logger = logging.getLogger(__name__)

# Tokens dropped before fuzzy-matching a repo id to a benchmark-source model name. Quant/
# format tags (so "Qwen3-32B-4bit" == "Qwen3-32B") AND role/format suffixes (so the HF
# "Qwen/Qwen3.6-32B-Instruct" collapses onto a source's "Qwen3.6 32B") — the lossy join
# was the main reason most models never matched a score. Size tokens ("32b") are kept;
# they disambiguate within a family.
_NAME_DROP = re.compile(
    r"^(gguf|mlx|bf16|fp16|f16|f32|\d+bit|i?q\d.*|instruct|chat|it|base|preview|hf)$",
    re.IGNORECASE,
)


def normalize_name(name: str) -> str:
    """A fuzzy join key: drop the org, split on punctuation, drop quant/format/role
    tokens, lowercase, concatenate. ``Qwen/Qwen3.6-32B-Instruct`` → ``qwen3632b``."""
    bare = name.rsplit("/", 1)[-1]
    parts = re.split(r"[^a-zA-Z0-9]+", bare)
    return "".join(p for p in parts if p and not _NAME_DROP.match(p)).lower()

_HF_BASE = "https://huggingface.co"
_OPENROUTER_MODELS = "https://openrouter.ai/api/v1/models"

# Effective bits-per-weight per quant family (includes format overhead). Keyed by the
# leading token of the quant label; used to estimate runtime memory from a param count.
_QUANT_BITS: dict[str, float] = {
    "IQ1": 1.7, "IQ2": 2.4, "IQ3": 3.1, "IQ4": 4.3,
    "Q2": 2.6, "Q3": 3.4, "Q4": 4.5, "Q5": 5.5, "Q6": 6.6, "Q8": 8.5,
    "F16": 16.0, "FP16": 16.0, "BF16": 16.0, "F32": 32.0,
}
# A GGUF path's quant tag, e.g. "…-Q4_K_M.gguf" → "Q4_K_M", "…-IQ2_XXS.gguf", or a
# full-precision "…-BF16.gguf". Matched against the whole path so a per-quant
# subdirectory layout ("Q4_K_M/model-…0001.gguf") still resolves.
_GGUF_QUANT_RE = re.compile(r"(I?Q\d[_A-Z0-9]*|BF16|F16|F32)", re.IGNORECASE)
# An MLX repo's quant, encoded in the id: "…-4bit", "…-8bit", "…-bf16".
_MLX_QUANT_RE = re.compile(r"-(\d+bit|bf16|fp16|f16)$", re.IGNORECASE)

# Fields to request on a list call. expand[] and full=true don't combine, so everything
# we read must be enumerated (tags for base_model dedup, likes/createdAt for quality).
_COMMON_EXPAND = [
    ("expand[]", f) for f in ("downloads", "likes", "createdAt", "tags", "pipeline_tag")
]
_GGUF_EXPAND = [("expand[]", "gguf"), ("expand[]", "gated"), *_COMMON_EXPAND]
_MLX_EXPAND = [("expand[]", "safetensors"), ("expand[]", "gguf"), *_COMMON_EXPAND]


def bits_for_quant(label: str) -> float:
    """Effective bits-per-weight for a quant label; defaults to 4.5 (a common Q4)."""
    upper = label.upper()
    if mlx := re.match(r"(\d+)BIT", upper):
        return float(mlx.group(1)) + 0.5
    for prefix, bits in _QUANT_BITS.items():
        if upper.startswith(prefix):
            return bits
    return 4.5


def _base_id(repo_id: str, tags: list[str]) -> str:
    """The canonical model a (possibly quant-fork) repo derives from — the dedup key.
    ``base_model:quantized:<base>`` / ``base_model:<base>`` tags are HF-validated."""
    for tag in tags:
        for prefix in ("base_model:quantized:", "base_model:finetune:", "base_model:"):
            if tag.startswith(prefix):
                return tag[len(prefix):]
    return repo_id


def _license_from_tags(tags: list[str]) -> str | None:
    for tag in tags:
        if tag.startswith("license:"):
            return tag[len("license:"):]
    return None


_FAMILIES = (
    "qwen", "llama", "deepseek", "mistral", "mixtral", "gemma", "phi", "yi",
    "glm", "gpt-oss", "kimi", "command", "granite", "olmo", "devstral", "nemotron",
)


def _family(repo_id: str) -> str | None:
    name = repo_id.split("/")[-1].lower()
    for family in _FAMILIES:
        if family in name:
            return family
    return None


def _hf_capabilities(gguf: dict, tags: list[str], pipeline_tag: str | None) -> Capabilities:
    """Capability flags derived from HF metadata — the fallback when OpenRouter
    doesn't cover a model. Vision/embedding from ``pipeline_tag`` are reliable;
    tool-calling from the chat template is a strong heuristic."""
    chat_template = (gguf.get("chat_template") or "") if isinstance(gguf, dict) else ""
    return Capabilities(
        tools=bool(re.search(r"tool", chat_template, re.IGNORECASE)),
        vision=pipeline_tag == "image-text-to-text",
        embedding=pipeline_tag == "feature-extraction",
        thinking="reasoning" in tags or bool(re.search(r"think", chat_template, re.IGNORECASE)),
    )


class HuggingFaceCatalog:
    """Fetches a deduplicated list of local models with exact per-quant sizes."""

    def __init__(self, client: httpx.AsyncClient, *, token: str | None = None,
                 timeout_s: float = 20.0) -> None:
        self._client = client
        self._headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._timeout = timeout_s

    async def _get(self, path: str, params=None):
        resp = await self._client.get(
            f"{_HF_BASE}{path}", params=params, headers=self._headers, timeout=self._timeout
        )
        resp.raise_for_status()
        return resp.json()

    async def _list(self, params: list[tuple[str, str]]) -> list[dict]:
        data = await self._get("/api/models", params)
        return data if isinstance(data, list) else []

    async def _model_meta(self, repo_id: str) -> dict | None:
        """Adoption/recency of a model repo (its real likes/downloads/age) — used to
        score quality from the *base* model rather than a quant re-upload."""
        try:
            data = await self._get(
                f"/api/models/{repo_id}",
                [("expand[]", "likes"), ("expand[]", "downloads"), ("expand[]", "createdAt")],
            )
        except (httpx.HTTPError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    async def _tree_sizes(self, repo_id: str) -> dict[str, int]:
        """Map each weight file in a repo to its byte size, keyed by path."""
        tree = await self._get(f"/api/models/{repo_id}/tree/main", [("recursive", "true")])
        sizes: dict[str, int] = {}
        for entry in tree if isinstance(tree, list) else []:
            if entry.get("type") != "file":
                continue
            path = entry.get("path", "")
            size = entry.get("size") or entry.get("lfs", {}).get("size")
            if size:
                sizes[path] = int(size)
        return sizes

    async def fetch(self, *, limit: int, max_models: int) -> list[CatalogModel]:
        gguf, mlx = await asyncio.gather(
            self._fetch_gguf(limit, max_models),
            self._fetch_mlx(max_models),
        )
        return [*gguf, *mlx]

    async def search(self, query: str, *, max_models: int) -> list[CatalogModel]:
        """The models matching a free-text query (an operator checking a specific model
        against their hardware), scored the same way as the curated catalog."""
        gguf, mlx = await asyncio.gather(
            self._fetch_gguf(max_models, max_models, query=query),
            self._fetch_mlx(max_models, query=query),
        )
        return [*gguf, *mlx]

    async def _fetch_gguf(
        self, limit: int, max_models: int, *, query: str | None = None
    ) -> list[CatalogModel]:
        # Sort by downloads, not trending: with the gguf + text-generation filters this
        # surfaces reputable quant repos of established models (bartowski, unsloth,
        # lmstudio-community, the official base repos) rather than flavor-of-the-week
        # merges, and the base_model dedup below collapses the forks of each base.
        # NOTE: expand[] and full=true don't combine — when expand[] is present HF
        # returns ONLY the expanded fields, so every field we read must be listed here
        # (notably `tags` for base_model dedup, and likes/createdAt for the fallback).
        select: list[tuple[str, str]] = (
            [("search", query)] if query else [("sort", "downloads"), ("direction", "-1")]
        )
        items = await self._list([
            ("filter", "gguf"),
            ("pipeline_tag", "text-generation"),
            *select,
            ("limit", str(limit)),
            *_GGUF_EXPAND,
        ])
        # Group quant-fork repos by their base model; keep the most-downloaded repo as
        # the one whose file tree we read for sizes.
        groups: dict[str, dict] = {}
        for item in items:
            repo_id = item.get("id") or item.get("modelId")
            if not repo_id:
                continue
            tags = item.get("tags", []) or []
            key = _base_id(repo_id, tags)
            downloads = item.get("downloads", 0) or 0
            current = groups.get(key)
            if current is None or downloads > current["downloads"]:
                groups[key] = {"repo": repo_id, "downloads": downloads, "item": item, "base": key}
        top = sorted(groups.values(), key=lambda g: g["downloads"], reverse=True)[:max_models]
        built = await asyncio.gather(*(self._build_gguf(g) for g in top))
        return [m for m in built if m is not None]

    async def _build_gguf(self, group: dict) -> CatalogModel | None:
        repo_id, item, base = group["repo"], group["item"], group["base"]
        try:
            sizes = await self._tree_sizes(repo_id)
        except (httpx.HTTPError, ValueError):
            logger.warning("cookbook: HF tree fetch failed for %s", repo_id, exc_info=True)
            return None
        # Sum file sizes per quant label (handles multi-part split GGUFs). Files whose
        # quant we can't identify are skipped — never bucketed into a catch-all, which
        # would sum unrelated quants into a bogus size.
        per_quant: dict[str, int] = {}
        for path, size in sizes.items():
            if not path.lower().endswith(".gguf"):
                continue
            match = _GGUF_QUANT_RE.search(path)
            if match is None:
                continue
            label = match.group(1).upper()
            per_quant[label] = per_quant.get(label, 0) + size
        if not per_quant:
            return None
        quants = [
            QuantVariant(label=label, bits_per_weight=bits_for_quant(label), size_bytes=size)
            for label, size in sorted(per_quant.items())
        ]
        gguf = item.get("gguf") or {}
        tags = item.get("tags", []) or []
        params = gguf.get("total")
        # Quality signals come from the BASE model's own repo (its real adoption +
        # release date), not the quant re-upload's — a quant fork's stats don't reflect
        # the model's standing. Fall back to the quant repo when there's no distinct base.
        base_meta = await self._model_meta(base) if base != repo_id else None
        meta = base_meta or item
        return CatalogModel(
            id=base,
            name=base.split("/")[-1],
            family=_family(base),
            params_b=round(params / 1e9, 2) if params else None,
            context_default=gguf.get("context_length"),
            capabilities=_hf_capabilities(gguf, tags, item.get("pipeline_tag")),
            license=_license_from_tags(tags),
            gated=bool(item.get("gated")),
            quants=quants,
            created_at=meta.get("createdAt") or item.get("createdAt"),
            downloads=meta.get("downloads") or group["downloads"],
            likes=meta.get("likes", 0) or 0,
        )

    async def _fetch_mlx(self, max_models: int, *, query: str | None = None) -> list[CatalogModel]:
        select: list[tuple[str, str]] = (
            [("search", query)] if query else [("sort", "downloads"), ("direction", "-1")]
        )
        items = await self._list([
            ("author", "mlx-community"),
            ("pipeline_tag", "text-generation"),
            *select,
            ("limit", str(max_models)),
            *_MLX_EXPAND,
        ])
        built = await asyncio.gather(*(self._build_mlx(item) for item in items))
        return [m for m in built if m is not None]

    async def _build_mlx(self, item: dict) -> CatalogModel | None:
        repo_id = item.get("id") or item.get("modelId")
        if not repo_id:
            return None
        match = _MLX_QUANT_RE.search(repo_id)
        label = f"MLX-{match.group(1)}" if match else "MLX"
        try:
            sizes = await self._tree_sizes(repo_id)
        except (httpx.HTTPError, ValueError):
            return None
        total = sum(s for p, s in sizes.items() if p.lower().endswith((".safetensors", ".gguf")))
        if not total:
            return None
        safetensors = item.get("safetensors") or {}
        gguf = item.get("gguf") or {}
        tags = item.get("tags", []) or []
        params = safetensors.get("total") or gguf.get("total")
        quant_label = match.group(1) if match else "16bit"
        return CatalogModel(
            id=repo_id,
            name=repo_id.split("/")[-1],
            family=_family(repo_id),
            params_b=round(params / 1e9, 2) if params else None,
            context_default=gguf.get("context_length"),
            capabilities=_hf_capabilities(gguf, tags, item.get("pipeline_tag")),
            license=_license_from_tags(tags),
            quants=[QuantVariant(label=label, bits_per_weight=bits_for_quant(quant_label),
                                 size_bytes=total)],
            created_at=item.get("createdAt"),
            downloads=item.get("downloads", 0) or 0,
            likes=item.get("likes", 0) or 0,
        )


class OpenRouterEnricher:
    """Overlays crisp capability flags onto the catalog, exact-joined by HF id."""

    def __init__(self, client: httpx.AsyncClient, *, timeout_s: float = 20.0) -> None:
        self._client = client
        self._timeout = timeout_s

    async def apply(self, models: list[CatalogModel]) -> None:
        resp = await self._client.get(_OPENROUTER_MODELS, timeout=self._timeout)
        resp.raise_for_status()
        rows = resp.json().get("data", [])
        by_hf: dict[str, dict] = {}
        for row in rows:
            hf_id = row.get("hugging_face_id")
            if hf_id:
                by_hf[hf_id.lower()] = row
        for model in models:
            row = by_hf.get(model.id.lower())
            if row is None:
                continue
            params = set(row.get("supported_parameters") or [])
            modalities = set((row.get("architecture") or {}).get("input_modalities") or [])
            # OpenRouter is authoritative where it covers a model; keep HF's reliable
            # embedding flag (OpenRouter doesn't host embedding models).
            model.capabilities.tools = "tools" in params
            model.capabilities.thinking = "reasoning" in params or "include_reasoning" in params
            model.capabilities.vision = "image" in modalities
            if not model.context_default and row.get("context_length"):
                model.context_default = int(row["context_length"])
