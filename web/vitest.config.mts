import path from "node:path";
import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const webDir = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      // Mirrors tsconfig.json "paths": "@/*" -> "./*".
      "@": webDir,
      // Next resolves `server-only` itself (it is no package of ours); tests of server modules get
      // Next's own empty variant, the one it uses on the server.
      "server-only": path.join(webDir, "node_modules/next/dist/compiled/server-only/empty.js"),
    },
  },
  test: {
    environment: "jsdom",
    include: ["**/*.test.{ts,tsx,mts}"],
    exclude: ["node_modules/**", ".next/**", ".next-build/**"],
    restoreMocks: true,
    unstubGlobals: true,
  },
});
