// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Peter Lawler

import { createHash, randomUUID } from "node:crypto";
import { EventEmitter } from "node:events";
import {
  lstatSync, mkdirSync, mkdtempSync, readFileSync, renameSync, rmdirSync, rmSync, unlinkSync, writeFileSync,
} from "node:fs";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { build } from "vite";

const manifestName = ".junie-build-manifest.json";
const lockName = ".junie-build.lock";
const bundleName = "junie-remote-card.js";
const digest = (data) => createHash("sha256").update(data).digest("hex");

function stat(path) {
  try { return lstatSync(path); } catch (error) {
    if (error.code === "ENOENT") return null;
    throw error;
  }
}

function checkDirectory(path) {
  const absolute = resolve(path);
  let current = sep;
  for (const part of absolute.split(sep).filter(Boolean)) {
    current = join(current, part);
    const info = stat(current);
    if (!info || !info.isDirectory() || info.isSymbolicLink()) {
      throw new Error(`Not a real directory: ${current}`);
    }
  }
}

function checkedPath(root, name, createParents = false) {
  if (typeof name !== "string" || !name || isAbsolute(name) || name.includes("\\") ||
      name.split("/").some((part) => !part || part === "." || part === "..") ||
      [manifestName, lockName].includes(name.split("/")[0])) {
    throw new Error(`Invalid output name: ${name}`);
  }
  let parent = root;
  const parts = name.split("/");
  for (const part of parts.slice(0, -1)) {
    parent = join(parent, part);
    if (!stat(parent) && createParents) mkdirSync(parent);
    const info = stat(parent);
    if (!info) return join(root, name);
    if (!info.isDirectory() || info.isSymbolicLink()) throw new Error(`Unsafe directory: ${parent}`);
  }
  const path = join(parent, parts.at(-1));
  const info = stat(path);
  if (info && (!info.isFile() || info.isSymbolicLink())) throw new Error(`Unsafe file: ${path}`);
  return path;
}

function readManifest(root) {
  const path = join(root, manifestName);
  const info = stat(path);
  if (!info) return {};
  if (!info.isFile() || info.isSymbolicLink()) throw new Error("Unsafe build manifest");
  const data = JSON.parse(readFileSync(path, "utf8"));
  if (data.version !== 1 || !data.files || typeof data.files !== "object" || Array.isArray(data.files)) {
    throw new Error("Invalid build manifest");
  }
  for (const [name, hash] of Object.entries(data.files)) {
    checkedPath(root, name);
    if (typeof hash !== "string" || !/^[0-9a-f]{64}$/.test(hash)) throw new Error("Invalid build hash");
  }
  return data.files;
}

function tempFile(directory, data) {
  const path = join(directory, `.junie-tmp-${randomUUID()}`);
  writeFileSync(path, data, { flag: "wx" });
  return path;
}

function publish(root, outputs) {
  checkDirectory(root);
  const lock = join(root, lockName);
  try { mkdirSync(lock); } catch (error) {
    throw new Error(`Build publication lock unavailable: ${lock}`, { cause: error });
  }
  const temps = [];
  const created = [];
  let manifestReplaced = false;
  let committed = false;
  let previousManifest;
  try {
    const old = readManifest(root);
    const manifestPath = join(root, manifestName);
    previousManifest = stat(manifestPath) ? readFileSync(manifestPath) : null;
    if (!outputs.has(bundleName)) throw new Error("Build did not produce the card bundle");
    const next = Object.create(null);
    for (const [name, content] of outputs) {
      const path = checkedPath(root, name);
      const info = stat(path);
      const hash = digest(content);
      next[name] = hash;
      if (info) {
        if (!Object.hasOwn(old, name) || digest(readFileSync(path)) !== old[name]) {
          throw new Error(`Unowned or modified output: ${name}`);
        }
        if (name !== bundleName && hash !== old[name]) {
          throw new Error(`Additional output must use a new name when content changes: ${name}`);
        }
      }
    }
    const obsolete = [];
    for (const [name, hash] of Object.entries(old)) {
      if (outputs.has(name)) continue;
      const path = checkedPath(root, name);
      if (stat(path) && digest(readFileSync(path)) === hash) obsolete.push([name, hash]);
      else if (stat(path)) console.warn(`Retaining modified obsolete output: ${name}`);
    }
    const pending = new Map();
    for (const [name, content] of outputs) {
      const path = checkedPath(root, name, true);
      if (stat(path) && name !== bundleName) continue;
      const temp = tempFile(dirname(path), content);
      temps.push(temp);
      pending.set(name, temp);
    }
    const manifestTemp = tempFile(root, JSON.stringify({ version: 1, files: next }, null, 2) + "\n");
    temps.push(manifestTemp);
    for (const [name, temp] of pending) {
      if (name === bundleName) continue;
      const path = checkedPath(root, name);
      if (stat(path)) throw new Error(`Output appeared during publication: ${name}`);
      renameSync(temp, path);
      created.push(path);
    }
    renameSync(manifestTemp, manifestPath);
    manifestReplaced = true;
    const bundlePath = checkedPath(root, bundleName);
    renameSync(pending.get(bundleName), bundlePath);
    committed = true;
    for (const [name, hash] of obsolete) {
      try {
        const path = checkedPath(root, name);
        if (stat(path) && digest(readFileSync(path)) === hash) unlinkSync(path);
        else if (stat(path)) console.warn(`Retaining changed obsolete output: ${name}`);
      } catch (error) {
        console.warn(`Obsolete output retained for manual review: ${name}: ${error.message}`);
      }
    }
  } catch (error) {
    if (!committed) {
      for (const path of created) { try { unlinkSync(path); } catch {} }
      if (manifestReplaced) {
        try {
          if (previousManifest === null) unlinkSync(join(root, manifestName));
          else renameSync(tempFile(root, previousManifest), join(root, manifestName));
        } catch (rollbackError) {
          console.error(`Manifest rollback failed; manual review required: ${rollbackError.message}`);
        }
      }
    }
    throw error;
  } finally {
    for (const path of temps) { try { unlinkSync(path); } catch {} }
    try { rmdirSync(lock); } catch (error) {
      console.warn(`Build lock retained for manual review: ${lock}: ${error.message}`);
    }
  }
}

export async function buildFrontend(destination, viteRoot, stagingPrefix, config = {}) {
  const root = resolve(destination);
  checkDirectory(root);
  const stage = mkdtempSync(stagingPrefix);
  let outputs = new Map();
  const capture = {
    name: "capture-frontend-outputs",
    buildStart() { outputs = new Map(); },
    writeBundle(_, bundle) {
      for (const name of Object.keys(bundle)) {
        const path = checkedPath(stage, name);
        if (relative(stage, path).startsWith("..") || outputs.has(name)) throw new Error("Invalid staged output");
        outputs.set(name, readFileSync(path));
      }
    },
  };
  function removeStage() {
    try { rmSync(stage, { recursive: true, force: true }); } catch (error) {
      console.warn(`Build staging directory retained for manual review: ${stage}: ${error.message}`);
    }
  }
  try {
    const result = await build({
      ...config,
      root: viteRoot,
      plugins: [...(config.plugins || []), capture],
      build: { ...config.build, outDir: stage, emptyOutDir: true },
    });
    if (!config.build?.watch) {
      publish(root, outputs);
      removeStage();
      return result;
    }
    const events = new EventEmitter();
    let queue = Promise.resolve();
    result.on("event", (event) => {
      const completedOutputs = outputs;
      queue = queue.then(async () => {
        if (event.code === "BUNDLE_END") {
          try {
            await event.result.close();
            publish(root, completedOutputs);
          } catch (error) {
            events.emit("event", { code: "ERROR", error });
            return;
          }
        }
        events.emit("event", event);
      });
    });
    events.close = async () => {
      await result.close();
      await queue;
      removeStage();
    };
    return events;
  } catch (error) {
    removeStage();
    throw error;
  }
}