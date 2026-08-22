/**
 * Stages the Pyodide runtime into public/ so the Code Runner's worker can load
 * it from our own origin rather than a CDN.
 *
 * Two details this has to get right:
 *  - `dereference`, because under bun's isolated linker node_modules/pyodide is
 *    a symlink into the global store, and cp would otherwise try to replace the
 *    destination directory with a link (ENOTDIR).
 *  - Clearing the destination first, so a version bump can't leave a previous
 *    Pyodide's files behind for the loader to pick up.
 */
import { cp, mkdir, rm } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = join(here, "..", "node_modules", "pyodide");
const dest = join(here, "..", "public", "pyodide");

await rm(dest, { recursive: true, force: true });
await mkdir(dest, { recursive: true });
await cp(src, dest, { recursive: true, dereference: true });
console.log("Copied Pyodide runtime assets to public/pyodide");
