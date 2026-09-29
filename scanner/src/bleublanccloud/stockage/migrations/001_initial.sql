-- Migration 001 : schéma initial (CLAUDE.md, section 12)

CREATE TABLE organisations (
    id           INTEGER PRIMARY KEY,
    slug         TEXT NOT NULL UNIQUE,
    nom          TEXT NOT NULL,
    type         TEXT NOT NULL CHECK (type IN ('commune', 'departement', 'region', 'autre')),
    code_commune TEXT,
    departement  TEXT,
    region       TEXT,
    population   INTEGER,
    site_web     TEXT,
    source       TEXT NOT NULL,
    cree_le      TEXT NOT NULL
);
CREATE INDEX idx_organisations_departement ON organisations (departement);

CREATE TABLE scans (
    id                INTEGER PRIMARY KEY,
    organisation_id   INTEGER REFERENCES organisations (id) ON DELETE CASCADE,
    domaine           TEXT NOT NULL,
    debut             TEXT NOT NULL,
    fin               TEXT,
    statut            TEXT NOT NULL,
    version_methodo   TEXT NOT NULL,
    erreurs_json      TEXT NOT NULL DEFAULT '[]',
    informations_json TEXT NOT NULL DEFAULT '{}',
    sondes_json       TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX idx_scans_organisation ON scans (organisation_id, debut);

CREATE TABLE constats (
    id             INTEGER PRIMARY KEY,
    scan_id        INTEGER NOT NULL REFERENCES scans (id) ON DELETE CASCADE,
    ordre          INTEGER NOT NULL,
    sonde          TEXT NOT NULL,
    categorie      TEXT NOT NULL,
    cle            TEXT NOT NULL,
    valeur         TEXT NOT NULL,
    fournisseur_id TEXT,
    niveau         TEXT NOT NULL,
    preuve_json    TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX idx_constats_scan ON constats (scan_id, ordre);

CREATE TABLE scores (
    scan_id      INTEGER PRIMARY KEY REFERENCES scans (id) ON DELETE CASCADE,
    score_global INTEGER NOT NULL,
    note         TEXT NOT NULL,
    detail_json  TEXT NOT NULL
);

CREATE TABLE rapports_ia (
    id                 INTEGER PRIMARY KEY,
    scan_id            INTEGER REFERENCES scans (id) ON DELETE CASCADE,
    empreinte_constats TEXT NOT NULL,
    modele             TEXT NOT NULL,
    version_invite     TEXT NOT NULL,
    contenu_json       TEXT,
    statut             TEXT NOT NULL DEFAULT 'valide' CHECK (statut IN ('valide', 'erreur')),
    erreur             TEXT,
    jetons_entree      INTEGER,
    jetons_sortie      INTEGER,
    cree_le            TEXT NOT NULL
);
CREATE INDEX idx_rapports_cache ON rapports_ia (empreinte_constats, modele, version_invite);

CREATE TABLE retraits (
    domaine      TEXT PRIMARY KEY,
    date_demande TEXT NOT NULL,
    motif        TEXT
);

-- Noms des départements et régions (geo.api.gouv.fr), pour l'export et la carte
CREATE TABLE territoires (
    type        TEXT NOT NULL CHECK (type IN ('departement', 'region')),
    code        TEXT NOT NULL,
    nom         TEXT NOT NULL,
    code_parent TEXT,
    PRIMARY KEY (type, code)
);
