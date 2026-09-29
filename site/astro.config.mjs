// Configuration Astro : site 100 % statique, aucune ressource externe.
import { defineConfig } from "astro/config";

export default defineConfig({
  site: "https://bleublanccloud.berachem.dev",
  output: "static",
  trailingSlash: "ignore",
  // La compression supprime certains espaces entre texte et liens : on la désactive.
  compressHTML: false,
  build: {
    format: "directory",
    inlineStylesheets: "always",
  },
  devToolbar: { enabled: false },
});
