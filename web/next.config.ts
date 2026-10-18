import path from "node:path";
import { fileURLToPath } from "node:url";

import type { NextConfig } from "next";

/** web/ is self-contained (Vercel builds it as the project root): nothing outside it is bundled,
 * and a stray lockfile in a parent directory must not move the root. */
const webDir = path.dirname(fileURLToPath(import.meta.url));

const nextConfig: NextConfig = {
  // NEXT_DIST_DIR keeps a production build out of the dev server's output (README, "Measure the JS").
  distDir: process.env.NEXT_DIST_DIR ?? ".next",
  cacheComponents: true,
  partialPrefetching: true,
  poweredByHeader: false,
  // The Postgres driver of the app's own accounts (lib/auth.ts) runs as a Node module, not bundled.
  serverExternalPackages: ["pg"],
  turbopack: {
    root: webDir,
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
