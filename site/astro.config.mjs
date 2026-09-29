// Configuration Astro : site 100 % statique, aucune ressource externe.
import { defineConfig } from "astro/config";

export default defineConfig({
  site: "https://bleublanccloud.berachem.dev",
  output: "static",
  trailingSlash: "ignore",
  build: {
    format: "directory",
    inlineStylesheets: "always",
  },
  devToolbar: { enabled: false },
});
