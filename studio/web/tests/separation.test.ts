// Studio is a separate application: it reaches Autology only through the platform's HTTP API.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const ROOT = join(__dirname, "..");
function files(dir: string): string[] {
  return readdirSync(dir).flatMap((f) => {
    const p = join(dir, f);
    return statSync(p).isDirectory() ? files(p) : /\.(ts|tsx)$/.test(p) ? [p] : [];
  });
}
const SOURCES = ["app", "components", "lib", "runtime"].flatMap((d) => files(join(ROOT, d)));

describe("separation from the engine", () => {
  it("has sources to check", () => expect(SOURCES.length).toBeGreaterThan(6));

  it("imports nothing that could reach a database, the file system, processes or the engine", () => {
    for (const f of SOURCES) {
      const src = readFileSync(f, "utf8");
      expect(src, f).not.toMatch(/from ["'](node:)?(fs|child_process|net|sqlite3?|better-sqlite3|pg)["']/);
      expect(src, f).not.toMatch(/autology\/(server|store|platform)|\.db["']/);
    }
  });

  it("reads configuration only in the server-side relay, and never exposes it to the browser", () => {
    for (const f of SOURCES) {
      const src = readFileSync(f, "utf8");
      if (/process\.env/.test(src)) expect(f.endsWith(join("lib", "forward.ts")), f).toBe(true);
      expect(src, f).not.toMatch(/NEXT_PUBLIC_/);
    }
  });

  it("client components never write tokens to localStorage", () => {
    for (const f of SOURCES) expect(readFileSync(f, "utf8"), f).not.toMatch(/localStorage/);
  });
});
