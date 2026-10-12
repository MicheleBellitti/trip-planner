import path from "node:path";
import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const webDir = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  plugins: [react()],
  resolve: {
    // Mirrors tsconfig.json "paths": "@/*" -> "./*".
    alias: { "@": webDir },
  },
  test: {
    environment: "jsdom",
    include: ["**/*.test.{ts,tsx,mts}"],
    exclude: ["node_modules/**", ".next/**", ".next-build/**"],
    restoreMocks: true,
    unstubGlobals: true,
  },
});
