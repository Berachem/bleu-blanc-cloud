-- Migration 006 : nouveau type d'organisation « universite » (ADR-0006).
--
-- SQLite ne permet pas de modifier une contrainte CHECK : la table est reconstruite, comme
-- dans la migration 002 (procédure officielle, clés étrangères désactivées le temps de la
-- copie pour ne supprimer aucun scan, aucune photo ni aucun contour par cascade).

PRAGMA foreign_keys = OFF;
BEGIN;

CREATE TABLE organisations_v3 (
    id           INTEGER PRIMARY KEY,
    slug         TEXT NOT NULL UNIQUE,
    nom          TEXT NOT NULL,
    type         TEXT NOT NULL CHECK (type IN (
                     'commune', 'departement', 'region', 'universite', 'autre', 'sur_demande'
                 )),
    code_commune TEXT,
    departement  TEXT,
    region       TEXT,
    population   INTEGER,
    site_web     TEXT,
    source       TEXT NOT NULL,
    cree_le      TEXT NOT NULL
);
INSERT INTO organisations_v3 (id, slug, nom, type, code_commune, departement, region,
                              population, site_web, source, cree_le)
    SELECT id, slug, nom, type, code_commune, departement, region,
           population, site_web, source, cree_le
    FROM organisations;
DROP TABLE organisations;
ALTER TABLE organisations_v3 RENAME TO organisations;
CREATE INDEX idx_organisations_departement ON organisations (departement);

COMMIT;
PRAGMA foreign_keys = ON;
