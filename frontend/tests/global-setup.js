/* global-setup.js — build the bundle once before the suite runs.

   The smoke tests drive the real backend, and the backend serves whatever
   config.frontend_dir() resolves to. Without this step a stale (or missing)
   frontend/dist would be tested instead of the working tree, which is the
   worst possible failure mode: green tests against code that is not the code
   under review.

   Set QAQC_SKIP_BUILD=1 to reuse an existing build when iterating on tests. */

import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const frontendDir = path.dirname(path.dirname(fileURLToPath(import.meta.url)));

export default function globalSetup() {
  if (process.env.QAQC_SKIP_BUILD === "1") {
    if (!existsSync(path.join(frontendDir, "dist", "index.html"))) {
      throw new Error("QAQC_SKIP_BUILD=1 but frontend/dist/index.html does not exist. Run `npm run build` first.");
    }
    return;
  }
  execFileSync("npm", ["run", "build"], {
    cwd: frontendDir,
    stdio: "inherit",
    shell: process.platform === "win32",
  });
}
