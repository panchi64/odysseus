import type { CodeLanguage } from "./model";

/** Starter source shown when a language is first selected or RESET is pressed. */
export const starterCode: Record<CodeLanguage, string> = {
  python: "# Python 3 · runs in-browser (Pyodide)\nprint('Hello, Odysseus!')\n",
  javascript:
    "// JavaScript · runs in-browser\nconsole.log('Hello, Odysseus!');\n",
  html: "<!-- HTML · rendered in browser -->\n<h1>Hello, Odysseus!</h1>\n",
};
