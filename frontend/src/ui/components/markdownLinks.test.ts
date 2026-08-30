import { describe, expect, test } from "bun:test";
import { Marked } from "marked";
import { isExternalHref, markedLinks, safeHref } from "./markdownLinks";

/** A private `marked` instance configured the way Markdown.tsx configures the
 *  shared one, so these assert what actually reaches `innerHTML`. */
const md = new Marked({ gfm: true, breaks: true }).use(markedLinks);
const render = (src: string): string => md.parse(src, { async: false });

describe("safeHref", () => {
  test("accepts the schemes prose links are made of", () => {
    expect(safeHref("https://example.com/a?b=1")).toBe(
      "https://example.com/a?b=1",
    );
    expect(safeHref("http://example.com")).toBe("http://example.com");
    expect(safeHref("mailto:someone@example.com")).toBe(
      "mailto:someone@example.com",
    );
    expect(safeHref("HTTPS://Example.COM/A")).toBe("HTTPS://Example.COM/A");
  });

  test("rejects script-bearing schemes", () => {
    expect(safeHref("javascript:alert(1)")).toBeNull();
    expect(safeHref("JaVaScRiPt:alert(1)")).toBeNull();
    expect(safeHref("vbscript:msgbox")).toBeNull();
    expect(safeHref("data:text/html,<script>alert(1)</script>")).toBeNull();
    expect(safeHref("file:///etc/passwd")).toBeNull();
  });

  test("rejects a scheme hidden behind entities or control characters", () => {
    expect(safeHref("&#106;avascript:alert(1)")).toBeNull();
    expect(safeHref("&#x6a;avascript:alert(1)")).toBeNull();
    expect(safeHref("java&Tab;script:alert(1)")).toBeNull();
    expect(safeHref("java&colon;script:alert(1)")).toBeNull();
    expect(safeHref("java\tscript:alert(1)")).toBeNull();
    expect(safeHref("  javascript:alert(1)")).toBeNull();
    // Double-encoded: `&amp;#106;` decodes to `&#106;`, then to `j`.
    expect(safeHref("&amp;#106;avascript:alert(1)")).toBeNull();
  });

  test("rejects anything without an explicit outbound scheme", () => {
    // A relative href is a model mistake, not a destination — dropping it keeps
    // a click from navigating the app off its own route.
    expect(safeHref("/settings/models")).toBeNull();
    expect(safeHref("./report.md")).toBeNull();
    expect(safeHref("#section")).toBeNull();
    // Protocol-relative: no scheme of its own, so it inherits — not a link.
    expect(safeHref("//evil.example")).toBeNull();
    expect(safeHref("")).toBeNull();
    expect(safeHref(undefined)).toBeNull();
  });

  test("returns the source href, not a decoded one", () => {
    // `&amp;` has to survive to the DOM so the browser decodes it back to `&`.
    expect(safeHref("https://a.test/?x=1&amp;y=2")).toBe(
      "https://a.test/?x=1&amp;y=2",
    );
  });

  test("rejects an href whose scheme exists only once decoded", () => {
    // The attribute is emitted with its `&` escaped, so the browser never
    // decodes it — accepting this would put a *relative* URL in the DOM.
    expect(safeHref("&#104;ttps://evil.test")).toBeNull();
    expect(safeHref("&#109;ailto:a@b.test")).toBeNull();
  });
});

describe("isExternalHref", () => {
  test("mailto hands off in place; the web opens a tab", () => {
    expect(isExternalHref("mailto:a@b.test")).toBe(false);
    expect(isExternalHref("MAILTO:a@b.test")).toBe(false);
    expect(isExternalHref("https://a.test")).toBe(true);
  });
});

describe("rendered anchors", () => {
  test("an external link opens a new tab with the opener severed", () => {
    const html = render("See [the docs](https://example.com/guide).");
    expect(html).toContain('href="https://example.com/guide"');
    expect(html).toContain('target="_blank"');
    expect(html).toContain('rel="noopener noreferrer"');
  });

  test("the destination is named for hover and for the outbound glyph", () => {
    const html = render("[the docs](https://www.example.com/guide)");
    expect(html).toContain('data-link-external="example.com"');
    expect(html).toContain('title="example.com"');
  });

  test("an author-written markdown title wins over the host", () => {
    const html = render('[docs](https://example.com "The v3 guide")');
    expect(html).toContain('title="The v3 guide"');
  });

  test("a link whose text is its own URL is not titled with itself", () => {
    const html = render("Autolinked: https://example.com/x");
    expect(html).toContain('href="https://example.com/x"');
    expect(html).not.toContain("title=");
  });

  test("mailto links in place, without a blank target", () => {
    const html = render("[write](mailto:a@b.test)");
    expect(html).toContain('href="mailto:a@b.test"');
    expect(html).not.toContain("target=");
    expect(html).not.toContain("data-link-external");
  });

  test("a mailto names the address, having no host to name", () => {
    expect(render("[write](mailto:a@b.test)")).toContain('title="a@b.test"');
  });

  test("a self-titling autolink is recognised through escaped quotes", () => {
    // `marked` escapes the `'` in the rendered text; the comparison has to see
    // past that or it adds a title to a link that already reads as its URL.
    const html = render("https://a.test/it's");
    expect(html).not.toContain("title=");
  });

  test("inline formatting inside the link text survives", () => {
    expect(render("[**bold** link](https://a.test)")).toContain(
      "<strong>bold</strong> link",
    );
  });

  test("a rejected href degrades to the link's own text", () => {
    const html = render("Click [here](javascript:alert(1)) now.");
    expect(html).toContain("here");
    expect(html).not.toContain("<a");
    expect(html).not.toContain("javascript:");
  });

  test("a quote in the href cannot break out of the attribute", () => {
    const html = render('[x](https://a.test/" onmouseover="alert(1))');
    expect(html).not.toContain('onmouseover="alert(1)"');
    expect(html).toContain("&quot;");
  });
});

describe("images", () => {
  test("an image never carries a remote src into the DOM", () => {
    // No click gates an `<img>`: a real `src` here would fetch from the remote
    // host the instant the answer rendered. The address is parked instead, for
    // the hydration pass to resolve through the backend proxy.
    const html = render("![a chart](https://pics.example/chart.png)");
    expect(html).toContain("<img");
    expect(html).toContain('data-remote-src="https://pics.example/chart.png"');
    // A bare ` src=` attribute, as distinct from ` data-remote-src=`.
    expect(html).not.toMatch(/\ssrc=/);
    expect(html).toContain('alt="a chart"');
  });

  test("the host is named on hover, as it is for a link", () => {
    expect(render("![c](https://www.pics.example/c.png)")).toContain(
      'title="pics.example"',
    );
  });

  test("an image with a rejected address degrades to its alt text", () => {
    for (const src of [
      "javascript:alert(1)",
      "data:image/svg+xml,<svg onload=alert(1)>",
      "./local/chart.png",
      "mailto:a@b.test",
    ]) {
      const html = render(`![the chart](${src})`);
      expect(html).not.toContain("<img");
      expect(html).toContain("the chart");
    }
  });

  test("an alt cannot break out of its attribute", () => {
    const html = render('![a" onerror="alert(1)](https://pics.example/c.png)');
    expect(html).not.toContain('onerror="alert(1)"');
    expect(html).toContain("&quot;");
  });
});

describe("raw HTML", () => {
  test("a script block becomes text, not a script", () => {
    const html = render("<script>alert(1)</script>");
    expect(html).not.toContain("<script>");
    expect(html).toContain("&lt;script&gt;");
  });

  test("an inline event handler becomes text", () => {
    const html = render("a <img src=x onerror=alert(1)> b");
    expect(html).not.toContain("<img");
    expect(html).toContain("&lt;img");
  });

  test("a raw anchor cannot route around the link renderer", () => {
    const html = render('<a href="javascript:alert(1)">raw</a>');
    expect(html).not.toContain("<a ");
    expect(html).toContain("&lt;a href=");
  });

  test("comments are dropped rather than shown", () => {
    expect(render("<!-- hidden -->")).not.toContain("hidden");
  });
});

describe("markdown the change must not disturb", () => {
  test("code spans and fences keep their angle brackets", () => {
    expect(render("`<div>`")).toContain("<code>&lt;div&gt;</code>");
    expect(render("```\n<div>\n```")).toContain("&lt;div&gt;");
  });

  test("a link inside a fence stays source text", () => {
    expect(render("```\n[x](https://a.test)\n```")).not.toContain("<a ");
  });
});
