# services/research/research_handler.py
"""Re-export of the canonical research handler.

The real `ResearchHandler` lives in `src/research_handler.py` — it owns the
task registry, owner-scoped persistence, hard-timeout/partial-result handling,
visual-report generation, and the consumed/archived lifecycle.

This module previously held a SECOND, divergent copy of that class which had
drifted badly (no owner scoping, deleted results on clear, no hidden-images or
hard-timeout support). To keep a single source of truth, the service facade now
re-exports the canonical implementation instead of maintaining a fork.
"""
from src.research_handler import ResearchHandler, RESEARCH_DATA_DIR

__all__ = ["ResearchHandler", "RESEARCH_DATA_DIR"]
