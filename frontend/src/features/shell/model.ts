/** Host shell feature data contracts. */

export type ShellLineKind = "command" | "stdout" | "stderr";

export interface ShellLine {
  id: string;
  kind: ShellLineKind;
  text: string;
  at: string;
}
