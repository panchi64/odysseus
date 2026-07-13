import { cp, mkdir } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = join(here, "..", "node_modules", "pyodide");
const dest = join(here, "..", "public", "pyodide");
await mkdir(dest, { recursive: true });
await cp(src, dest, { recursive: true });
console.log("Copied Pyodide runtime assets to public/pyodide");
