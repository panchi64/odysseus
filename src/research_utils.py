# src/research_utils.py
"""Shared utilities for the deep research system.

Centralizes text cleaning, quality filtering, and other logic
used across deep_research.py, research_handler.py, and visual_report.py.
"""

# ---------------------------------------------------------------------------
# Thinking / reasoning block stripping
# ---------------------------------------------------------------------------

def strip_thinking(text):
    """Strip thinking / reasoning patterns from LLM output.

    Delegates to `src.text_helpers.strip_think` (single source of truth).
    Kept as an alias here so existing `from src.research_utils import strip_thinking`
    callers don't break. Preserves None passthrough — many callers pass an
    `Optional[str]` LLM result and expect None back when the call failed.
    """
    if text is None:
        return None
    from src.text_helpers import strip_think
    return strip_think(text, prose=False, prompt_echo=True)


# ---------------------------------------------------------------------------
# Source quality filtering
# ---------------------------------------------------------------------------

# Markers indicating the EXTRACTION failed — i.e. the LLM reported the page had
# nothing useful, rather than returning real content. If any marker is found
# (case-insensitive), the finding is filtered out.
#
# These must be phrases that read as meta-commentary about a failed extraction,
# NOT bare topic words. Earlier versions listed single nouns like "cookie" and
# "copyright", which silently discarded perfectly good findings whenever the
# subject matter happened to mention HTTP cookies, the EU cookie law, copyright
# reform, page footers, etc. Keep this list to failure-signal phrases only.
LOW_QUALITY_MARKERS = [
    "insufficient to",
    "content is insufficient",
    "no substantive data",
    "does not contain relevant",
    "not relevant to the goal",
    "no relevant information",
    "unable to extract",
    "completely unrelated",
    "boilerplate",
]


def is_low_quality(summary: str) -> bool:
    """Check if a finding summary indicates useless or irrelevant content."""
    try:
        if not summary:
            return True
        low = summary.lower()
        return any(marker in low for marker in LOW_QUALITY_MARKERS)
    except Exception:
        return False  # fail open
