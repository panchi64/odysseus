# Odysseus — Specification

This directory specifies **what Odysseus must do**: the required behavior, capabilities, and performance characteristics of the system. It is a black-box specification — it describes the system from the outside, not how any of it is implemented.

## Documents

| File | Scope |
|---|---|
| `00-overview.md` | Product vision, principles, and system-wide requirements (`XC-*`) |
| `10-agent-engine.md` | The autonomous tool-using agent (`AE-*`) |
| `11-deep-research.md` | The deep-research capability (`DR-*`) |
| `20-feature-inventory.md` | All remaining features, one section each |

## Conventions

**Requirement IDs.** Every requirement has a stable ID (e.g. `AE-2.3`) so it can be referenced and tracked. Prefixes: `XC-*` system-wide, `AE-*` agent, `DR-*` deep research, and per-feature prefixes in the inventory (`MEM-*`, `EMAIL-*`, …).

**Keywords** (RFC 2119): **MUST** = required; **SHOULD** = strong default, deviate only with reason; **MAY** = optional.

**Altitude.** Requirements describe observable behavior, capabilities, and performance — never internal structure, algorithms, or code organization. A requirement states the *what* and the *constraint*, and leaves the *how* to the implementation.
