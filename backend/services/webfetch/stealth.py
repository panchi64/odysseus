"""Make the controlled browser present as an ordinary user's Chrome.

A headless, automated browser leaks tells a real one doesn't — a ``HeadlessChrome``
user-agent, ``navigator.webdriver === true``, an empty plugin list, a SwiftShader WebGL
renderer. Sites key off these to serve bot pages, blocks, or stripped-down content, so the
agent would not see what a person browsing manually sees. This applies the well-known set
of evasions: a realistic Chrome user-agent matched to the actual engine version, a normal
locale/timezone/viewport, and an init script (run before any page script, in every
context) that masks the automation fingerprint.

This is **fingerprint normalization, not anti-bot evasion**: it gets ordinary sites to
return their real content. It deliberately does NOT defeat residential-proxy / CAPTCHA bot
walls (Cloudflare/DataDome class) — that needs a proxy network we don't run.
"""

from __future__ import annotations

# Runs before any page script in every context, masking the standard automation tells.
INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
window.chrome = window.chrome || { runtime: {} };
const _query = window.navigator.permissions && window.navigator.permissions.query;
if (_query) {
  window.navigator.permissions.query = (p) =>
    p && p.name === 'notifications'
      ? Promise.resolve({ state: Notification.permission })
      : _query(p);
}
const _getParameter = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function (p) {
  if (p === 37445) return 'Intel Inc.';                // UNMASKED_VENDOR_WEBGL
  if (p === 37446) return 'Intel Iris OpenGL Engine';  // UNMASKED_RENDERER_WEBGL
  return _getParameter.call(this, p);
};
"""

_DEFAULT_MAJOR = "120"


def realistic_user_agent(browser_version: str | None) -> str:
    """A normal desktop Chrome UA, matched to the engine's actual major version so the UA
    and feature set agree. The container runs Linux Chromium, so the UA claims Linux —
    internally consistent (no Mac/Linux platform mismatch for a site to notice)."""
    major = _DEFAULT_MAJOR
    if browser_version:
        head = browser_version.split(".", 1)[0]
        if head.isdigit():
            major = head
    return (
        f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{major}.0.0.0 Safari/537.36"
    )


def context_options(*, user_agent: str, locale: str, timezone_id: str) -> dict:
    """Stealth-friendly ``new_context`` kwargs: a realistic UA, locale/timezone, a normal
    desktop viewport, and an Accept-Language header consistent with the locale."""
    return {
        "user_agent": user_agent,
        "locale": locale,
        "timezone_id": timezone_id,
        "viewport": {"width": 1280, "height": 800},
        "device_scale_factor": 1,
        "extra_http_headers": {"Accept-Language": f"{locale},en;q=0.9"},
    }
