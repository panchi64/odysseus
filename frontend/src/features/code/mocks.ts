import type { CodeRun } from "./model";

export const mockRuns: CodeRun[] = [
  {
    id: "r-001",
    language: "python",
    source: "import math\nprint(math.sqrt(2))\nprint('Hello, Odysseus!')",
    output: "1.4142135623730951\nHello, Odysseus!",
    status: "ok",
    durationMs: 82,
    ranAt: "2026-06-07T14:02:00Z",
  },
  {
    id: "r-002",
    language: "javascript",
    source: "const x = [1, 2, 3];\nconsole.log(x.map(n => n * n));",
    output: "[ 1, 4, 9 ]",
    status: "ok",
    durationMs: 14,
    ranAt: "2026-06-07T13:55:00Z",
  },
  {
    id: "r-003",
    language: "python",
    source: "raise ValueError('demo error')",
    output:
      'Traceback (most recent call last):\n  File "<stdin>", line 1, in <module>\nValueError: demo error',
    status: "error",
    durationMs: 11,
    ranAt: "2026-06-07T13:47:00Z",
  },
  {
    id: "r-004",
    language: "html",
    source: "<h1>Hello</h1><p>Rendered output.</p>",
    output: "[HTML rendered in browser preview]",
    status: "ok",
    durationMs: 3,
    ranAt: "2026-06-07T13:40:00Z",
  },
];

export const starterCode: Record<string, string> = {
  python: "# Python 3 · runs in-browser (Pyodide)\nprint('Hello, Odysseus!')\n",
  javascript:
    "// JavaScript · runs in-browser\nconsole.log('Hello, Odysseus!');\n",
  html: "<!-- HTML · rendered in browser -->\n<h1>Hello, Odysseus!</h1>\n",
};

export const mockOutputs: Record<
  string,
  { output: string; status: "ok" | "error"; durationMs: number }
> = {
  python: { output: "Hello, Odysseus!\n", status: "ok", durationMs: 74 },
  javascript: { output: "Hello, Odysseus!\n", status: "ok", durationMs: 9 },
  html: {
    output: "[HTML rendered in browser preview — no console output]",
    status: "ok",
    durationMs: 2,
  },
};
