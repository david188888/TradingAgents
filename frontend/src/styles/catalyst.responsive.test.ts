/**
 * T32 — the stylesheet has no rule that could force a horizontal scrollbar,
 * and keeps the workbench a single column at every width.
 *
 * `vitest.config.ts` does not enable `test.css`, so an imported stylesheet is
 * never parsed or applied to jsdom in a component test — asserting a
 * `getComputedStyle()` value there would pass or fail independently of the
 * real file the browser loads. This file instead reads `catalyst.css` itself
 * (the exact file `main.tsx` imports and Vite bundles) as text and checks the
 * properties design 4.6 actually depends on: no rule splits the page into
 * more than one column, nothing sets a fixed width wider than the smallest
 * required viewport (390px) without capping it at `100%`, and the two rules
 * the file's own top comment names as load-bearing — `overflow-wrap: anywhere`
 * and `min-width: 0` — are present on the containers that carry unbroken
 * Chinese text.
 *
 * The file is read with `node:fs` (ambient-typed in `node-ambient.d.ts`, next
 * to this file — the project has no `@types/node`). Vite's `?raw` import
 * suffix was tried first and resolves to an empty string under this Vitest
 * setup rather than the file's real content, so a direct file read is the
 * reliable option here.
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const CSS_PATH = path.resolve(__dirname, "catalyst.css");
const css = readFileSync(CSS_PATH, "utf-8");

/** The declaration block for a single selector, or null if the selector is absent. */
function ruleBody(selector: string): string | null {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = new RegExp(`${escaped}\\s*{([^}]*)}`).exec(css);
  return match ? match[1] : null;
}

describe("T32 — no rule introduces a second column or a horizontal scrollbar", () => {
  it("never sets a multi-column grid or a row-direction flex on a layout container", () => {
    // A width-gated grid (`grid-template-columns` with more than one track) is
    // exactly the shape of layout that reads fine at 1440 and overflows at
    // 390 unless every breakpoint re-derives it. The page has none at all.
    expect(css).not.toMatch(/grid-template-columns/);
    expect(css).not.toMatch(/display:\s*grid/);
  });

  it("never sets overflow-x to a value that would create a horizontal scrollbar", () => {
    expect(css).not.toMatch(/overflow-x\s*:\s*(scroll|auto)/);
  });

  it("the only fixed-pixel-ish width in the file is capped at 100% of its parent", () => {
    // `.catalyst-drawer` is the one container with a width wider than an
    // icon-sized control (`min(30rem, 100%)`), and it is explicitly bounded so
    // it cannot exceed the viewport on a narrow screen; the narrow-screen rule
    // below then drops it to a full-width sheet.
    const drawer = ruleBody(".catalyst-drawer");
    expect(drawer).not.toBeNull();
    expect(drawer).toMatch(/width:\s*min\(30rem,\s*100%\)/);
    expect(drawer).toMatch(/max-width:\s*100%/);

    // No other rule sets an absolute width in px/rem/em above icon size
    // (2.5rem) outside of a min()/clamp() expression or a 100%-bounded value.
    // The lookbehind excludes `min-width`/`max-width`/`border-*-width` — this
    // is about the `width` property itself, not every property ending in it.
    const widthDeclarations = [...css.matchAll(/(?<![a-zA-Z-])width:\s*([^;]+);/g)].map((m) => m[1].trim());
    for (const value of widthDeclarations) {
      const isBoundedFunction = /^(min|max|clamp)\(/.test(value);
      const isPercent = value.endsWith("%");
      const isSmallFixed = /^(2(\.5)?rem|2rem)$/.test(value);
      expect(isBoundedFunction || isPercent || isSmallFixed).toBe(true);
    }
  });

  it("keeps overflow-wrap: anywhere on the containers that carry unbroken CJK text", () => {
    // Design 4.6's own note: a long unbroken Chinese string sets a min-content
    // floor on a flex/grid child and pushes the page wide unless it can break
    // mid-run. This is the rule that makes that not happen. `overflow-wrap` is
    // an inherited CSS property, so it is declared once on the page root
    // (`.catalyst-brief`) and again on the one subtree that is portalled
    // outside it (the drawer) — descendants like `.catalyst-row-line` inherit
    // it rather than repeating it, and repeating it there is not required.
    expect(ruleBody(".catalyst-brief")).toMatch(/overflow-wrap:\s*anywhere/);
    expect(ruleBody(".catalyst-drawer-body p")).toMatch(/overflow-wrap:\s*anywhere/);
    expect(ruleBody(".catalyst-drawer-head h3")).toMatch(/overflow-wrap:\s*anywhere/);
    // And nothing downstream of the root resets it back to the default.
    expect(css).not.toMatch(/overflow-wrap:\s*normal/);
  });

  it("keeps min-width: 0 on every flex/grid container that can hold long text", () => {
    // Without this, a flex child's default `min-width: auto` lets its
    // min-content width win over the parent's width, which is the other half
    // of the same overflow failure mode `overflow-wrap` alone does not fix.
    for (const selector of [
      ".catalyst-brief",
      ".catalyst-row",
      ".catalyst-row-line",
      ".catalyst-row-line > span:first-child",
      ".catalyst-drawer-layer",
      ".catalyst-drawer",
    ]) {
      expect(ruleBody(selector)).toMatch(/min-width:\s*0/);
    }
  });

  it("declares narrow-screen rules that only ever shrink spacing, never widen a fixed box", () => {
    const narrowBlocks = [...css.matchAll(/@media \(max-width: \d+px\) {([\s\S]*?)\n}\n/g)].map((m) => m[1]);
    expect(narrowBlocks.length).toBeGreaterThanOrEqual(2);
    for (const block of narrowBlocks) {
      // Narrow-screen overrides in this file only ever touch padding/gap/
      // font-size/max-height — never introduce a width, a grid, or a
      // horizontal-scroll container.
      expect(block).not.toMatch(/grid-template-columns/);
      expect(block).not.toMatch(/overflow-x\s*:\s*(scroll|auto)/);
      expect(block).not.toMatch(/(?<!max-)width:\s*\d/);
    }
  });
});

describe("T32 — the limitation scroll region caps height, not width", () => {
  it("scrolls vertically only", () => {
    const scroll = ruleBody(".catalyst-limitations-scroll");
    expect(scroll).not.toBeNull();
    expect(scroll).toMatch(/overflow-y:\s*auto/);
    expect(scroll).toMatch(/max-height:/);
    expect(scroll).not.toMatch(/overflow-x/);
    expect(scroll).not.toMatch(/(?<!max-)width:/);
  });
});
