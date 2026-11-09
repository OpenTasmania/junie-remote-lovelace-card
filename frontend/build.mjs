// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Peter Lawler

import { fileURLToPath } from "node:url";
import { dirname, join, resolve } from "node:path";
import { buildFrontend } from "./publish.mjs";

const __dirname = dirname(fileURLToPath(import.meta.url));
const destination = join(__dirname, "../custom_components/junie_remote/frontend");
const viteRoot = __dirname;
const stagingPrefix = resolve(__dirname, ".build-stage-");
const watch = process.argv.includes("--watch");
const result = await buildFrontend(destination, viteRoot, stagingPrefix, { build: watch ? { watch: {} } : {} });
if (watch) {
  result.on("event", (event) => {
    if (event.code === "ERROR") console.error("Frontend watch build failed:", event.error);
    if (event.code === "BUNDLE_END") console.log("Frontend watch build published.");
  });
  for (const signal of ["SIGINT", "SIGTERM"]) {
    process.once(signal, async () => { await result.close(); process.exit(0); });
  }
}