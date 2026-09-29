-- Migration 003 : photos des organisations (Wikimedia Commons, auto-hébergées)

CREATE TABLE photos (
    organisation_id INTEGER PRIMARY KEY REFERENCES organisations (id) ON DELETE CASCADE,
    statut          TEXT NOT NULL CHECK (statut IN ('ok', 'absente', 'refusee', 'erreur')),
    wikidata        TEXT,          -- identifiant Wikidata (ex. Q1289)
    fichier         TEXT,          -- titre du fichier sur Commons (« File:… »)
    auteur          TEXT,          -- texte brut (HTML retiré)
    licence         TEXT,          -- ex. « CC BY-SA 4.0 »
    url_licence     TEXT,
    url_source      TEXT,          -- page du fichier sur Commons
    largeur         INTEGER,
    hauteur         INTEGER,
    chemin          TEXT,          -- fichier local, relatif au dossier des photos
    motif           TEXT,          -- raison d'un refus ou d'une erreur
    maj_le          TEXT NOT NULL
);
