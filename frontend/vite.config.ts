import { defineConfig } from "vite";
import { nitroV2Plugin as nitro } from "@solidjs/vite-plugin-nitro-2";
import { solidStart } from "@solidjs/start/config";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [solidStart({ ssr: false }), tailwindcss(), nitro()],
  // Pyodide ships its own wasm/loader; excluding it keeps Vite from trying to pre-bundle it.
  optimizeDeps: { exclude: ["pyodide"] },
  assetsInclude: ["**/*.wasm"],
  // Module workers (pyodide.worker.ts, pdf.js) use dynamic imports, which Rollup can't bundle into iife workers.
  worker: { format: "es" },
});
