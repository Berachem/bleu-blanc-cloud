// Configuration Astro : site 100 % statique, aucune ressource externe.
import { defineConfig } from "astro/config";
import { SITE } from "./src/config.ts";

export default defineConfig({
  // Domaine lu dans DOMAINE_SITE (défaut : bleublanccloud.fr), voir src/config.ts
  site: SITE.url,
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
