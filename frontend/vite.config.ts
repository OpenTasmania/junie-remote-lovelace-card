// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Peter Lawler

/// <reference types="vitest" />
import { defineConfig } from "vite";
import { resolve } from "path";

// Ensure Node 20 compatibility for vitest error formatting
if (!("groupBy" in Map)) {
  (Map as any).groupBy = function (items: any[], callback: (item: any) => any) {
    const map = new Map();
    for (const item of items) {
      const key = callback(item);
      if (!map.has(key)) map.set(key, []);
      map.get(key).push(item);
    }
    return map;
  };
}
if (!("groupBy" in Object)) {
  (Object as any).groupBy = function (items: any[], callback: (item: any) => any) {
    const obj: Record<string, any[]> = {};
    for (const item of items) {
      const key = callback(item);
      if (!obj[key]) obj[key] = [];
      obj[key].push(item);
    }
    return obj;
  };
}

export default defineConfig({
  test: {
    environment: "happy-dom",
    globals: true,
  },
  build: {
    lib: {
      entry: resolve(__dirname, "src/index.ts"),
      formats: ["es"],
      fileName: () => "junie-remote-card.js",
    },
    rollupOptions: {
      output: {
        inlineDynamicImports: true,
        banner: "/*! SPDX-License-Identifier: MIT | Copyright (c) 2026 Peter Lawler */",
      },
    },
  },
  define: {
    "process.env.NODE_ENV": JSON.stringify("production"),
  },
});
