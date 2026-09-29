-- Migration 002 : analyses sur demande (tickets Codeberg)
--
-- 1. Nouveau type d'organisation « sur_demande ». SQLite ne permet pas de modifier une
--    contrainte CHECK : la table est reconstruite (procédure officielle, clés étrangères
--    désactivées le temps de la copie pour ne supprimer aucun scan par cascade).
-- 2. Table « demandes » : suivi de chaque ticket (limites, réessais, réponse envoyée).

PRAGMA foreign_keys = OFF;
BEGIN;

CREATE TABLE organisations_v2 (
    id           INTEGER PRIMARY KEY,
    slug         TEXT NOT NULL UNIQUE,
    nom          TEXT NOT NULL,
    type         TEXT NOT NULL
                 CHECK (type IN ('commune', 'departement', 'region', 'autre', 'sur_demande')),
    code_commune TEXT,
    departement  TEXT,
    region       TEXT,
    population   INTEGER,
    site_web     TEXT,
    source       TEXT NOT NULL,
    cree_le      TEXT NOT NULL
);
INSERT INTO organisations_v2 (id, slug, nom, type, code_commune, departement, region,
                              population, site_web, source, cree_le)
    SELECT id, slug, nom, type, code_commune, departement, region,
           population, site_web, source, cree_le
    FROM organisations;
DROP TABLE organisations;
ALTER TABLE organisations_v2 RENAME TO organisations;
CREATE INDEX idx_organisations_departement ON organisations (departement);

CREATE TABLE demandes (
    depot           TEXT NOT NULL,              -- dépôt Codeberg « propriétaire/nom »
    numero          INTEGER NOT NULL,           -- numéro du ticket
    auteur          TEXT NOT NULL,              -- compte Codeberg (jamais publié)
    domaine         TEXT,                       -- domaine validé, NULL si invalide
    statut          TEXT NOT NULL CHECK (statut IN (
                        'nouvelle', 'a_publier', 'traitee', 'refusee', 'erreur', 'echec')),
    motif           TEXT,                       -- code du refus ou de l'erreur
    tentatives      INTEGER NOT NULL DEFAULT 0, -- erreurs techniques successives
    organisation_id INTEGER REFERENCES organisations (id) ON DELETE SET NULL,
    recue_le        TEXT NOT NULL,
    acceptee_le     TEXT,                       -- compte dans les limites quotidiennes
    commentee_le    TEXT,                       -- réponse finale publiée dans le ticket
    cloturee_le     TEXT,                       -- ticket fermé par le robot
    maj_le          TEXT NOT NULL,
    PRIMARY KEY (depot, numero)
);
CREATE INDEX idx_demandes_acceptee ON demandes (acceptee_le);

COMMIT;
PRAGMA foreign_keys = ON;
