import { defineConfig } from "astro/config";
import react from "@astrojs/react";

// Set BASE_PATH only when building a project-site preview, e.g. /breach-dashboard-v2/.
const base = process.env.BASE_PATH || "/";
if (!base.startsWith("/") || base.startsWith("//") || base.includes("..")) {
  throw new Error(
    "BASE_PATH must be an absolute URL path, such as /breach-dashboard-v2/.",
  );
}

export default defineConfig({
  output: "static",
  base,
  trailingSlash: "always",
  integrations: [react()],
  devToolbar: { enabled: false },
});
