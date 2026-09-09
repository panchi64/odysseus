"""One instance's containers must be invisible to another's.

The stake is higher than a name collision. Boot reconciliation *deletes* by pattern —
it lists everything matching its filters and force-removes it, on the reasoning that
startup is the one moment nothing carrying our names can be in use. That reasoning holds
for exactly one instance per host, so a second one booting under the same prefix would
collect the first's live workspaces mid-conversation, and the managed SearXNG and
web-fetch containers would be force-removed out from under it by name.

Two properties, then: the default prefix still produces exactly the names the operator's
running instance already uses (this must not rename anything for them), and a second
prefix produces names that neither instance's filters can reach.
"""

from __future__ import annotations

import re

from services.sandbox.names import DEFAULT_NAMES, ContainerNames
from services.searxng import ManagedSearxng
from services.webfetch.browser import ManagedBrowser

_DEV = ContainerNames("odysseus-dev")


def _searxng(prefix: str, tmp_path) -> ManagedSearxng:
    return ManagedSearxng(
        enabled=False,
        image="searxng/searxng:latest",
        data_dir=tmp_path,
        startup_timeout_s=1.0,
        container_prefix=prefix,
    )


def _browser(prefix: str) -> ManagedBrowser:
    return ManagedBrowser(
        enabled=False,
        image="chromedp/headless-shell:latest",
        startup_timeout_s=1.0,
        concurrency=1,
        user_agent="",
        locale="en-US",
        timezone_id="UTC",
        container_prefix=prefix,
    )


def test_the_default_prefix_keeps_every_name_the_operator_already_runs(tmp_path):
    # A rename here would orphan the containers of an instance mid-upgrade: the new
    # process would neither find nor reconcile what the old one left behind.
    assert _searxng("odysseus", tmp_path)._container == "odysseus-searxng"
    browser = _browser("odysseus")
    assert browser._container == "odysseus-webfetch"
    assert browser._proxy_container == "odysseus-webfetch-proxy"
    assert DEFAULT_NAMES.session("abc") == "odysseus-sbx-abc"
    assert DEFAULT_NAMES.preview("abc") == "odysseus-pre-abc"
    assert DEFAULT_NAMES.sidecar("abc") == "odysseus-egress-abc"
    assert DEFAULT_NAMES.network("abc") == "odysseus-net-abc"


def test_a_second_prefix_renames_the_managed_web_containers(tmp_path):
    assert _searxng("odysseus-dev", tmp_path)._container == "odysseus-dev-searxng"
    browser = _browser("odysseus-dev")
    assert browser._container == "odysseus-dev-webfetch"
    assert browser._proxy_container == "odysseus-dev-webfetch-proxy"


def test_the_proxy_joins_its_own_browsers_namespace_not_the_default_one():
    # The sidecar enforces SSRF for the browser it shares a network namespace with. A
    # pair that straddled two prefixes would point the dev instance's proxy at the
    # operator's browser — the fence on one process guarding another's traffic.
    flags = _browser("odysseus-dev")._proxy_flags()
    assert "container:odysseus-dev-webfetch" in flags
    assert "container:odysseus-webfetch" not in flags


def test_reconciliation_only_ever_matches_its_own_instances_names():
    ours = [DEFAULT_NAMES.session("a"), DEFAULT_NAMES.preview("a"), DEFAULT_NAMES.sidecar("a")]
    theirs = [_DEV.session("a"), _DEV.preview("a"), _DEV.sidecar("a")]

    # Each filter matches every container its own scheme creates...
    assert all(re.search(DEFAULT_NAMES.container_filter, name) for name in ours)
    assert all(re.search(_DEV.container_filter, name) for name in theirs)
    assert re.search(DEFAULT_NAMES.network_filter, DEFAULT_NAMES.network("a"))
    assert re.search(_DEV.network_filter, _DEV.network("a"))

    # ...and nothing the other's does, in either direction. The nesting is the case
    # worth pinning: "odysseus-dev" starts with "odysseus", so only the anchor plus the
    # fixed role segment keeps the operator's filter off the dev instance's containers.
    assert not any(re.search(DEFAULT_NAMES.container_filter, name) for name in theirs)
    assert not any(re.search(_DEV.container_filter, name) for name in ours)
    assert not re.search(DEFAULT_NAMES.network_filter, _DEV.network("a"))
    assert not re.search(_DEV.network_filter, DEFAULT_NAMES.network("a"))
