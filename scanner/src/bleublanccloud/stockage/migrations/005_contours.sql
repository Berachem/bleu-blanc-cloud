-- Migration 005 : contours des communes pour la carte de situation des fiches
-- (remplace les photos Wikimedia ; l'ancienne table « photos » n'est plus utilisée).

CREATE TABLE contours (
    code_commune   TEXT PRIMARY KEY,   -- code INSEE
    geometrie_json TEXT NOT NULL,      -- coordonnées MultiPolygon simplifiées (WGS 84)
    source         TEXT NOT NULL,      -- ex. « geo.api.gouv.fr / IGN, licence Etalab 2.0 »
    maj_le         TEXT NOT NULL
);
