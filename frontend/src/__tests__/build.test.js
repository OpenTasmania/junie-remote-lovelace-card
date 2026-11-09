// @vitest-environment node
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Peter Lawler

import { afterEach, describe, expect, it } from "vitest";
import { existsSync, mkdtempSync, mkdirSync, readFileSync, readdirSync, rmSync, rmdirSync, symlinkSync, writeFileSync } from "node:fs";
import { relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { buildFrontend } from "../../publish.mjs";

const roots = [];
function fixture() {
  const root = mkdtempSync(resolve(process.cwd(), ".build-test-"));
  roots.push(root);
  const output = resolve(root, "published");
  mkdirSync(output);
  const entry = resolve(root, "entry.js");
  writeFileSync(entry, 'export const value = "working";');
  return { root, output, entry };
}

async function compile(f, asset, extra = [], options = {}) {
  return buildFrontend(options.output || f.output, f.root, options.stagingPrefix || resolve(f.root, ".build-test-"), {
    configFile: false,
    logLevel: "silent",
    plugins: [{
      name: "test-asset",
      generateBundle() {
        if (asset) this.emitFile({ type: "asset", fileName: asset, source: "generated" });
      },
    }, ...extra],
    build: {
      lib: { entry: f.entry, formats: ["es"], fileName: () => "junie-remote-card.js" },
    },
  });
}

afterEach(() => {
  for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true });
});

describe("frontend build publication", () => {
  it("ignores generated stage and fixture directories", () => {
    const ignore = readFileSync(fileURLToPath(new URL("../../../.gitignore", import.meta.url)), "utf8");
    expect(ignore).toContain("frontend/.build-stage-*/");
    expect(ignore).toContain("frontend/.build-test-*/");
  });

  it("stages outside the deployable package and removes the stage after success and failure", async () => {
    const f = fixture();
    const packageRoot = resolve(f.root, "custom_components/junie_remote");
    const output = resolve(packageRoot, "frontend");
    const sourceRoot = resolve(f.root, "frontend");
    const stagingPrefix = resolve(sourceRoot, ".build-stage-");
    mkdirSync(output, { recursive: true });
    mkdirSync(sourceRoot, { recursive: true });

    let stage;
    const observeStage = {
      name: "observe-stage",
      configResolved(config) {
        stage = config.build.outDir;
        expect(stage.startsWith(stagingPrefix)).toBe(true);
        expect(relative(packageRoot, stage).startsWith("..")).toBe(true);
      },
      buildStart() {
        expect(existsSync(stage)).toBe(true);
      },
    };

    await compile(f, null, [observeStage], { output, stagingPrefix });
    expect(existsSync(stage)).toBe(false);
    expect(readdirSync(packageRoot)).toEqual(["frontend"]);

    writeFileSync(f.entry, "not valid javascript {");
    await expect(compile(f, null, [observeStage], { output, stagingPrefix })).rejects.toThrow();
    expect(existsSync(stage)).toBe(false);
    expect(readdirSync(packageRoot)).toEqual(["frontend"]);
  });

  it("publishes a loadable bundle and removes only previously owned obsolete assets", async () => {
    const f = fixture();
    writeFileSync(resolve(f.output, "sentinel.txt"), "user data");
    await compile(f, "old-asset.txt");
    expect(readFileSync(resolve(f.output, "old-asset.txt"), "utf8")).toBe("generated");
    await compile(f, "new-asset.txt");
    expect(() => readFileSync(resolve(f.output, "old-asset.txt"))).toThrow();
    expect(readFileSync(resolve(f.output, "new-asset.txt"), "utf8")).toBe("generated");
    expect(readFileSync(resolve(f.output, "sentinel.txt"), "utf8")).toBe("user data");
    const code = readFileSync(resolve(f.output, "junie-remote-card.js"), "utf8");
    const module = await import(`data:text/javascript;base64,${Buffer.from(code).toString("base64")}`);
    expect(module.value).toBe("working");
  });

  it("rejects unknown asset collisions and retains the prior bundle", async () => {
    const f = fixture();
    await compile(f);
    const bundle = readFileSync(resolve(f.output, "junie-remote-card.js"));
    writeFileSync(resolve(f.output, "collision.txt"), "user data");
    writeFileSync(f.entry, 'export const value = "new";');
    await expect(compile(f, "collision.txt")).rejects.toThrow();
    expect(readFileSync(resolve(f.output, "collision.txt"), "utf8")).toBe("user data");
    expect(readFileSync(resolve(f.output, "junie-remote-card.js"))).toEqual(bundle);
  });

  it("retains the prior bundle when the build fails", async () => {
    const f = fixture();
    await compile(f);
    const bundle = readFileSync(resolve(f.output, "junie-remote-card.js"));
    writeFileSync(f.entry, "not valid javascript {");
    await expect(compile(f)).rejects.toThrow();
    expect(readFileSync(resolve(f.output, "junie-remote-card.js"))).toEqual(bundle);
  });

  it("retains the prior bundle when a write hook fails after output generation", async () => {
    const f = fixture();
    await compile(f);
    const bundle = readFileSync(resolve(f.output, "junie-remote-card.js"));
    writeFileSync(f.entry, 'export const value = "new";');
    await expect(compile(f, null, [{ name: "write-failure", writeBundle() { throw new Error("failed write"); } }])).rejects.toThrow();
    expect(readFileSync(resolve(f.output, "junie-remote-card.js"))).toEqual(bundle);
  });

  it("retains the prior bundle if another close hook fails", async () => {
    const f = fixture();
    await compile(f);
    const bundle = readFileSync(resolve(f.output, "junie-remote-card.js"));
    writeFileSync(f.entry, 'export const value = "new";');
    await expect(compile(f, null, [{ name: "close-failure", closeBundle() { throw new Error("failed close"); } }])).rejects.toThrow();
    expect(readFileSync(resolve(f.output, "junie-remote-card.js"))).toEqual(bundle);
  });

  it("rejects symlink destinations without touching the target", async () => {
    const f = fixture();
    await compile(f);
    const outside = resolve(f.root, "outside.txt");
    writeFileSync(outside, "outside");
    symlinkSync(outside, resolve(f.output, "link.txt"));
    await expect(compile(f, "link.txt")).rejects.toThrow();
    expect(readFileSync(outside, "utf8")).toBe("outside");
  });

  it("rejects symlinked output roots and nested directories", async () => {
    const f = fixture();
    await compile(f);
    const outside = resolve(f.root, "outside");
    mkdirSync(outside);
    symlinkSync(outside, resolve(f.output, "assets"));
    await expect(compile(f, "assets/new.txt")).rejects.toThrow();
    expect(() => readFileSync(resolve(outside, "new.txt"))).toThrow();
    const alias = resolve(f.root, "alias");
    symlinkSync(f.output, alias);
    await expect(compile({ ...f, output: alias })).rejects.toThrow();
  });

  it("refuses an unowned primary bundle or modified owned bundle", async () => {
    const f = fixture();
    const path = resolve(f.output, "junie-remote-card.js");
    writeFileSync(path, "user bundle");
    await expect(compile(f)).rejects.toThrow();
    expect(readFileSync(path, "utf8")).toBe("user bundle");
    rmSync(path);
    await compile(f);
    writeFileSync(path, "edited bundle");
    await expect(compile(f)).rejects.toThrow();
    expect(readFileSync(path, "utf8")).toBe("edited bundle");
  });

  it("publishes nested generated files and removes only owned obsolete files", async () => {
    const f = fixture();
    await compile(f, "assets/old.txt");
    writeFileSync(resolve(f.output, "assets/sentinel.txt"), "user data");
    await compile(f, "assets/new.txt");
    expect(() => readFileSync(resolve(f.output, "assets/old.txt"))).toThrow();
    expect(readFileSync(resolve(f.output, "assets/new.txt"), "utf8")).toBe("generated");
    expect(readFileSync(resolve(f.output, "assets/sentinel.txt"), "utf8")).toBe("user data");
  });

  it("refuses to change a secondary output in place", async () => {
    const f = fixture();
    await compile(f, "asset.txt");
    const bundle = readFileSync(resolve(f.output, "junie-remote-card.js"));
    const replacement = {
      name: "changed-asset",
      generateBundle() { this.emitFile({ type: "asset", fileName: "asset.txt", source: "different" }); },
    };
    await expect(compile(f, null, [replacement])).rejects.toThrow();
    expect(readFileSync(resolve(f.output, "asset.txt"), "utf8")).toBe("generated");
    expect(readFileSync(resolve(f.output, "junie-remote-card.js"))).toEqual(bundle);
  });

  it("fails closed on a held publication lock and permits retry", async () => {
    const f = fixture();
    await compile(f);
    const bundle = readFileSync(resolve(f.output, "junie-remote-card.js"));
    const lock = resolve(f.output, ".junie-build.lock");
    mkdirSync(lock);
    writeFileSync(f.entry, 'export const value = "new";');
    const attempts = await Promise.allSettled([compile(f), compile(f)]);
    expect(attempts.map((result) => result.status)).toEqual(["rejected", "rejected"]);
    expect(readFileSync(resolve(f.output, "junie-remote-card.js"))).toEqual(bundle);
    rmdirSync(lock);
    await compile(f);
    expect(readFileSync(resolve(f.output, "junie-remote-card.js"), "utf8")).toContain("new");
  });

  it("keeps manifest and bundle consistent across concurrent independent builds", async () => {
    const f = fixture();
    const second = resolve(f.root, "second.js");
    writeFileSync(second, 'export const value = "another";');
    await Promise.all([compile(f), compile({ ...f, entry: second })]);
    const bundle = readFileSync(resolve(f.output, "junie-remote-card.js"), "utf8");
    expect(bundle.includes("working") || bundle.includes("another")).toBe(true);
    await compile(f);
    expect(readFileSync(resolve(f.output, "junie-remote-card.js"), "utf8")).toContain("working");
  });

  it("retains modified obsolete files and refuses corrupted ownership", async () => {
    const f = fixture();
    await compile(f, "old.txt");
    writeFileSync(resolve(f.output, "old.txt"), "user edit");
    await compile(f);
    expect(readFileSync(resolve(f.output, "old.txt"), "utf8")).toBe("user edit");
    const bundle = readFileSync(resolve(f.output, "junie-remote-card.js"));
    writeFileSync(resolve(f.output, ".junie-build-manifest.json"), "{}");
    await expect(compile(f)).rejects.toThrow();
    expect(readFileSync(resolve(f.output, "junie-remote-card.js"))).toEqual(bundle);
  });

  it("publishes each successful watch rebuild and preserves a failed rebuild", async () => {
    const f = fixture();
    const watcher = await buildFrontend(f.output, f.root, resolve(f.root, ".build-test-"), {
      configFile: false, logLevel: "silent",
      build: { watch: {}, lib: { entry: f.entry, formats: ["es"], fileName: () => "junie-remote-card.js" } },
    });
    function nextBuild() {
      return new Promise((resolveEvent, rejectEvent) => {
        let result;
        const handler = async (event) => {
          if (event.code === "BUNDLE_END") {
            result = "success";
          } else if (event.code === "ERROR") {
            result = "error";
          } else if (event.code === "END") {
            watcher.off("event", handler);
            resolveEvent(result);
          }
        };
        watcher.on("event", handler);
      });
    }
    try {
      expect(await nextBuild()).toBe("success");
      let next = nextBuild();
      await new Promise((resolveTimer) => setTimeout(resolveTimer, 150));
      writeFileSync(f.entry, 'export const value = "second";');
      expect(await next).toBe("success");
      const bundle = readFileSync(resolve(f.output, "junie-remote-card.js"));
      expect(bundle.toString()).toContain("second");
      next = nextBuild();
      await new Promise((resolveTimer) => setTimeout(resolveTimer, 150));
      writeFileSync(f.entry, "not valid javascript {");
      expect(await next).toBe("error");
      expect(readFileSync(resolve(f.output, "junie-remote-card.js"))).toEqual(bundle);
      next = nextBuild();
      await new Promise((resolveTimer) => setTimeout(resolveTimer, 150));
      writeFileSync(f.entry, 'export const value = "recovered";');
      expect(await next).toBe("success");
      expect(readFileSync(resolve(f.output, "junie-remote-card.js"), "utf8")).toContain("recovered");
    } finally { await watcher.close(); }
  }, 15000);
});