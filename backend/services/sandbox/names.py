"""What this instance calls the containers and networks it creates.

One module for the whole scheme because two halves of it have to agree and are otherwise
written pages apart: the builders that *name* a workspace's runtime objects, and the
filters boot reconciliation uses to *find* them again after a crash. Reconciliation
removes everything its filters match without asking — so a builder that drifted from a
filter would either strand leftovers forever or, far worse, collect something that was
never ours.

The prefix is the only variable, and it is what separates two instances sharing a host.
Every filter is anchored immediately before a fixed role segment (``sbx``, ``net``, …),
which is what makes the separation total: ``^odysseus-(sbx|…)-`` cannot match
``odysseus-dev-sbx-…``, because ``dev`` sits where the role has to be. Neither instance
can see the other's containers, in either direction, however the prefixes nest.
"""

from __future__ import annotations

from dataclasses import dataclass

#: The role segment each kind of object carries, between the prefix and the key.
_SESSION = "sbx"
_PREVIEW = "pre"
_SIDECAR = "egress"
_NETWORK = "net"

#: The roles reconciliation collects as containers. ``net`` is absent on purpose — it is
#: a network, listed and removed by a different runtime subcommand.
_CONTAINER_ROLES = (_SESSION, _PREVIEW, _SIDECAR)


@dataclass(frozen=True, slots=True)
class ContainerNames:
    """The naming scheme, bound to one instance's prefix.

    Passed down rather than re-derived: the session that creates a container and the
    reconciliation that later removes it must be working from the same one, and a value
    object makes that structural instead of a convention two files both have to keep.
    """

    prefix: str = "odysseus"

    def session(self, key: str) -> str:
        """The workspace container for a conversation."""
        return f"{self.prefix}-{_SESSION}-{key}"

    def preview(self, key: str) -> str:
        """The container serving that workspace's live preview."""
        return f"{self.prefix}-{_PREVIEW}-{key}"

    def sidecar(self, key: str) -> str:
        """The egress proxy on that workspace's network. Also its DNS name there, so
        this is what the proxy environment inside the containers has to point at."""
        return f"{self.prefix}-{_SIDECAR}-{key}"

    def network(self, key: str) -> str:
        """The internal network the workspace and its sidecar share."""
        return f"{self.prefix}-{_NETWORK}-{key}"

    @property
    def container_filter(self) -> str:
        """The runtime ``name=`` filter matching every container this scheme creates."""
        return f"^{self.prefix}-({'|'.join(_CONTAINER_ROLES)})-"

    @property
    def network_filter(self) -> str:
        """The runtime ``name=`` filter matching every network this scheme creates."""
        return f"^{self.prefix}-{_NETWORK}-"


#: The scheme an instance that never configures a prefix uses — the operator's own. A
#: shared singleton rather than a default constructed per call site, so the parameter
#: default is a value and not a call, and so there is one object to compare against.
DEFAULT_NAMES = ContainerNames()
