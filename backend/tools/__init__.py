"""Tools — thin adapters over services/, exposed to the model as toolsets.

Which tools a run sees is *our* policy: a stack of toolset wrappers
(privilege gate → enable gate → namespacing) evaluated against the run's deps.
Sensitive tools are approval-gated (AE-3 / D20). Logic never lives in a tool —
it delegates to a capability in services/.

Stub — no tools yet. See docs/architecture/README.md (Pillar III, §2.2).
"""
