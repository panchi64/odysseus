"""The harness — the app-assembly layer that turns capabilities into one running product.

Sits at the top of the stack beside ``app.py`` (peer of ``routes``), so it may import
any layer below. Nothing below imports it.
"""

from harness.lifecycle import LifecycleRegistry

__all__ = ["LifecycleRegistry"]
