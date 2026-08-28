"""Managed SearXNG lifecycle — the parts that don't need a real container runtime:
the disabled/external short-circuits and the generated settings file."""

from __future__ import annotations

import tempfile
from pathlib import Path

from services.searxng import ManagedSearxng


def _manager(**overrides) -> ManagedSearxng:
    defaults = dict(
        enabled=True,
        image="searxng/searxng:latest",
        data_dir=Path(tempfile.mkdtemp()),
        startup_timeout_s=1.0,
    )
    return ManagedSearxng(**{**defaults, **overrides})


async def test_disabled_is_a_noop():
    m = _manager(enabled=False)
    await m.start()
    assert m.base_url is None
    await m.stop()


async def test_external_url_is_used_directly_without_a_container():
    m = _manager(external_base_url="http://my.searx:8080/")
    await m.start()
    assert m.base_url == "http://my.searx:8080"  # trailing slash trimmed, no container
    await m.stop()


def test_settings_enable_json_and_keep_a_stable_secret_key():
    data_dir = Path(tempfile.mkdtemp())
    m = _manager(data_dir=data_dir)

    path = m._write_settings()
    text = path.read_text()
    assert "json" in text  # the JSON API the agent queries is enabled
    assert "limiter: false" in text  # a single local operator, not a public instance

    key_first = (data_dir / "searxng" / "secret_key").read_text()
    m._write_settings()  # a re-boot rewrites settings.yml...
    key_second = (data_dir / "searxng" / "secret_key").read_text()
    assert key_first == key_second  # ...but reuses the persisted key
