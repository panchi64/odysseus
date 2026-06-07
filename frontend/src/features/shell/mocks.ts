import type { ShellLine } from "./model";

export const mockInitialLines: ShellLine[] = [
  { id: "l-001", kind: "command", text: "uv sync", at: "2026-06-07T13:50:00Z" },
  {
    id: "l-002",
    kind: "stdout",
    text: "Resolved 142 packages in 1.2s",
    at: "2026-06-07T13:50:01Z",
  },
  {
    id: "l-003",
    kind: "stdout",
    text: "Installed 142 packages in 0.8s",
    at: "2026-06-07T13:50:02Z",
  },
  {
    id: "l-004",
    kind: "command",
    text: "uv run pytest tests/ -x -q",
    at: "2026-06-07T13:51:00Z",
  },
  {
    id: "l-005",
    kind: "stdout",
    text: "......................",
    at: "2026-06-07T13:51:03Z",
  },
  {
    id: "l-006",
    kind: "stdout",
    text: "22 passed in 3.14s",
    at: "2026-06-07T13:51:04Z",
  },
];

/** Mock output lines for a given command. */
export function mockOutputFor(cmd: string): string[] {
  const c = cmd.trim().toLowerCase();
  if (c.startsWith("ls"))
    return ["app.py  core/  data/  routes/  services/  src/  static/  tests/"];
  if (c.startsWith("ps"))
    return [
      "  PID TTY  TIME CMD",
      " 1024 ?    0:02 uvicorn",
      " 1025 ?    0:00 chromadb",
    ];
  if (c.startsWith("df"))
    return [
      "Filesystem      Size  Used Avail Use%",
      "/dev/disk3s1     228G  41G  187G  18%  /",
    ];
  if (c.startsWith("pwd"))
    return ["/Users/panchi/Documents/projects/personal/ai/odysseus"];
  if (c.startsWith("uname"))
    return ["Darwin 25.5.0 Darwin Kernel Version 25.5.0"];
  if (c.startsWith("echo")) return [cmd.replace(/^echo\s*/i, "")];
  if (c === "whoami") return ["odysseus-operator"];
  if (c.startsWith("cat")) return ["[binary or file contents truncated]"];
  return [`${cmd}: command output (mock)`];
}
