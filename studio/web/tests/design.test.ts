// The design tokens: one palette per theme, and text that stays readable on it. Colours are a presentation matter;
// nothing here decides what a person may do.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(join(__dirname, "..", "app", "globals.css"), "utf8");
const runtime = readFileSync(join(__dirname, "..", "runtime", "runtime.css"), "utf8");
const shell = readFileSync(join(__dirname, "..", "runtime", "RuntimeApp.tsx"), "utf8");

function tokens(block: string): Record<string, string> {
  return Object.fromEntries([...block.matchAll(/(--[a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\b/g)].map((m) => [m[1], m[2]]));
}
const light = tokens(css.slice(css.indexOf(":root {"), css.indexOf("color-scheme: light")));
const dark = { ...light, ...tokens(css.slice(css.indexOf(':root[data-theme="dark"]'), css.indexOf("* { box-sizing"))) };
const darkAuto = { ...light, ...tokens(css.slice(css.indexOf("@media (prefers-color-scheme: dark)"), css.indexOf(':root[data-theme="dark"]'))) };

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
const contrast = (a: string, b: string) => { const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x); return (hi + 0.05) / (lo + 0.05); };

describe("design tokens", () => {
  it("give both themes the same roles, and the two dark declarations the same values", () => {
    for (const role of ["--bg", "--panel", "--surface", "--panel-2", "--ink", "--muted", "--line", "--accent", "--accent-ink", "--accent-text", "--ok", "--bad"]) {
      expect(light[role], role).toMatch(/^#/);
      expect(dark[role], role).toMatch(/^#/);
    }
    expect(darkAuto).toEqual(dark);       // "follow the system" and "dark" are one theme, not two that drift apart
  });

  it("keep text readable in both themes (WCAG AA for normal text: 4.5 to 1)", () => {
    for (const [name, t] of [["light", light], ["dark", dark]] as const) {
      const pairs: [string, string][] = [["--ink", "--bg"], ["--ink", "--panel"], ["--ink", "--surface"], ["--muted", "--bg"], ["--muted", "--panel"],
        ["--muted", "--panel-2"], ["--accent-text", "--bg"], ["--accent-text", "--panel"], ["--accent-ink", "--accent"], ["--bad", "--panel"],
        ["--ok", "--panel"], ["--warn-ink", "--warn-bg"], ["--ink", "--panel-2"]];
      for (const [fg, bg] of pairs) expect(contrast(t[fg], t[bg]), `${name}: ${fg} on ${bg}`).toBeGreaterThanOrEqual(4.5);
    }
    // the filled accent is a gradient: the text on it is readable at both ends, in both themes
    for (const [block, ink] of [[css.slice(0, css.indexOf("color-scheme: light")), light["--accent-ink"]],
                                [css.slice(css.indexOf(':root[data-theme="dark"]')), dark["--accent-ink"]]] as const) {
      const stops = /--accent-fill:\s*linear-gradient\([^,]+,\s*(#[0-9a-f]{6}),\s*(#[0-9a-f]{6})\)/i.exec(block)!;
      for (const stop of stops.slice(1, 3)) expect(contrast(ink, stop), `text on ${stop}`).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("let an application choose an accent by name only, and say how old its screen is", () => {
    expect([...new Set([...runtime.matchAll(/\.rt\[data-accent="([a-z]+)"\] \{ --rt-accent/g)].map((m) => m[1]))].sort())
      .toEqual(["amber", "blue", "green", "slate", "teal", "violet"]);     // the closed list of the manifest, and nothing else
    expect(shell).toContain('data-testid="rt-fresh"');
    expect(shell).toContain("Engine data read at");                         // the Engine's answer, by this browser's clock
    expect(css).toContain("prefers-reduced-motion");
  });
});
