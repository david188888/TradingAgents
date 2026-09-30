/**
 * Minimal ambient typing for the handful of Node builtins
 * `catalyst.responsive.test.ts` uses to read `catalyst.css` as raw text.
 *
 * The project has no `@types/node` dependency, and Vite's `?raw` import
 * suffix — the alternative that would need no Node APIs at all — resolves to
 * an empty string under this Vitest setup rather than the file's real
 * content (verified directly; not a typing gap). A real Node file read is the
 * reliable option, so this declares just enough of `node:fs`/`node:path` for
 * that one file, rather than adding a new dependency for a single test.
 */
declare module "node:fs" {
  export function readFileSync(path: string, encoding: "utf-8" | "utf8"): string;
}

declare module "node:path" {
  function resolve(...segments: string[]): string;
  const path: { resolve: typeof resolve };
  export default path;
}

declare const __dirname: string;
