"""Accès à la base SQLite : migrations, organisations, scans, scores, rapports IA."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Collection, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any, Literal

from bleublanccloud.modeles import (
    Constat,
    InformationsComplementaires,
    Organisation,
    RapportIA,
    ResultatScan,
    Retrait,
    Score,
)

DOSSIER_MIGRATIONS = Path(__file__).parent / "migrations"
LIBELLES_RESOLUTION = {
    "sans_adresse": "aucune adresse IP",
    "echec_dns": "échec DNS",
    "asn_introuvable": "opérateur de l'IP introuvable",
}


CTE_DERNIERS_SCANS = """
derniers_scans AS (
    SELECT id FROM (
        SELECT id, ROW_NUMBER() OVER (
            PARTITION BY COALESCE('organisation:' || organisation_id, 'domaine:' || domaine)
            ORDER BY debut DESC, id DESC
        ) AS rang
        FROM scans
    )
    WHERE rang = 1
)
"""
"""Dernier scan de chaque organisation (les scans sans organisation sont groupés par domaine)."""


def _maintenant() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class OrganisationEnregistree:
    id: int
    organisation: Organisation


@dataclass(frozen=True)
class ScanEnregistre:
    id: int
    organisation_id: int | None
    resultat: ResultatScan
    version_methodo: str
    score: Score | None


@dataclass(frozen=True)
class RapportEnregistre:
    contenu: RapportIA
    modele: str
    version_invite: str
    cree_le: datetime


StatutDemande = Literal["nouvelle", "a_publier", "traitee", "refusee", "erreur", "echec"]
"""Cycle d'une demande : nouvelle → a_publier → traitee, ou refusee, ou erreur (réessayée)
puis echec après le nombre maximal de tentatives."""


@dataclass
class DemandeEnregistree:
    """Suivi d'un ticket « Analyser mon site » (le contenu du ticket n'est jamais stocké)."""

    depot: str
    numero: int
    auteur: str
    statut: StatutDemande
    recue_le: datetime
    domaine: str | None = None
    motif: str | None = None
    tentatives: int = 0
    organisation_id: int | None = None
    acceptee_le: datetime | None = None
    commentee_le: datetime | None = None
    cloturee_le: datetime | None = None


def _date_ou_rien(valeur: str | None) -> datetime | None:
    return datetime.fromisoformat(valeur) if valeur else None


def _iso_ou_rien(valeur: datetime | None) -> str | None:
    return valeur.astimezone(UTC).isoformat() if valeur else None


class Base:
    """Base SQLite du projet. S'utilise comme gestionnaire de contexte."""

    def __init__(self, chemin: Path | str) -> None:
        if str(chemin) != ":memory:":
            Path(chemin).parent.mkdir(parents=True, exist_ok=True)
        self.connexion = sqlite3.connect(str(chemin))
        self.connexion.row_factory = sqlite3.Row
        self.connexion.execute("PRAGMA foreign_keys = ON")
        if str(chemin) != ":memory:":
            self.connexion.execute("PRAGMA journal_mode = WAL")

    def __enter__(self) -> Base:
        self.migrer()
        return self

    def __exit__(
        self,
        type_exception: type[BaseException] | None,
        exception: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        self.fermer()

    def fermer(self) -> None:
        self.connexion.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.connexion:
            yield self.connexion

    # ------------------------------------------------------------------ #
    # Migrations
    # ------------------------------------------------------------------ #

    def migrer(self) -> list[str]:
        """Applique, dans l'ordre, les migrations SQL numérotées non encore appliquées."""
        self.connexion.execute(
            "CREATE TABLE IF NOT EXISTS migrations (version TEXT PRIMARY KEY, appliquee_le TEXT)"
        )
        deja = {r["version"] for r in self.connexion.execute("SELECT version FROM migrations")}
        appliquees: list[str] = []
        for fichier in sorted(DOSSIER_MIGRATIONS.glob("*.sql")):
            version = fichier.stem
            if version in deja:
                continue
            with self.connexion:
                self.connexion.executescript(fichier.read_text(encoding="utf-8"))
                self.connexion.execute(
                    "INSERT INTO migrations (version, appliquee_le) VALUES (?, ?)",
                    (version, _maintenant()),
                )
            appliquees.append(version)
        return appliquees

    # ------------------------------------------------------------------ #
    # Organisations et territoires
    # ------------------------------------------------------------------ #

    def enregistrer_organisation(self, organisation: Organisation) -> int:
        """Crée ou met à jour une organisation (clé : slug)."""
        with self.transaction() as c:
            c.execute(
                """
                INSERT INTO organisations (slug, nom, type, code_commune, departement, region,
                                           population, site_web, source, cree_le)
                VALUES (:slug, :nom, :type, :code_commune, :departement, :region,
                        :population, :site_web, :source, :cree_le)
                ON CONFLICT (slug) DO UPDATE SET
                    nom = excluded.nom, type = excluded.type,
                    code_commune = excluded.code_commune, departement = excluded.departement,
                    region = excluded.region, population = excluded.population,
                    site_web = COALESCE(excluded.site_web, organisations.site_web),
                    source = excluded.source
                """,
                {**organisation.model_dump(), "cree_le": _maintenant()},
            )
            ligne = c.execute(
                "SELECT id FROM organisations WHERE slug = ?", (organisation.slug,)
            ).fetchone()
        return int(ligne["id"])

    def _organisation(self, ligne: sqlite3.Row) -> OrganisationEnregistree:
        champs = {k: ligne[k] for k in ligne.keys() if k not in ("id", "cree_le")}  # noqa: SIM118
        return OrganisationEnregistree(int(ligne["id"]), Organisation.model_validate(champs))

    def organisations(
        self, limite: int | None = None, avec_site: bool = False
    ) -> list[OrganisationEnregistree]:
        requete = "SELECT * FROM organisations"
        if avec_site:
            requete += " WHERE site_web IS NOT NULL AND site_web != ''"
        requete += " ORDER BY population DESC NULLS LAST, nom"
        if limite is not None:
            requete += f" LIMIT {int(limite)}"
        return [self._organisation(ligne) for ligne in self.connexion.execute(requete)]

    def organisation_par_slug(self, slug: str) -> OrganisationEnregistree | None:
        ligne = self.connexion.execute(
            "SELECT * FROM organisations WHERE slug = ?", (slug,)
        ).fetchone()
        return self._organisation(ligne) if ligne else None

    def organisation_par_id(self, identifiant: int) -> OrganisationEnregistree | None:
        ligne = self.connexion.execute(
            "SELECT * FROM organisations WHERE id = ?", (identifiant,)
        ).fetchone()
        return self._organisation(ligne) if ligne else None

    def enregistrer_territoire(
        self, type_territoire: str, code: str, nom: str, code_parent: str | None = None
    ) -> None:
        with self.transaction() as c:
            c.execute(
                """
                INSERT INTO territoires (type, code, nom, code_parent) VALUES (?, ?, ?, ?)
                ON CONFLICT (type, code) DO UPDATE SET nom = excluded.nom,
                    code_parent = excluded.code_parent
                """,
                (type_territoire, code, nom, code_parent),
            )

    def territoires(self, type_territoire: str) -> dict[str, tuple[str, str | None]]:
        lignes = self.connexion.execute(
            "SELECT code, nom, code_parent FROM territoires WHERE type = ?", (type_territoire,)
        )
        return {ligne["code"]: (ligne["nom"], ligne["code_parent"]) for ligne in lignes}

    # ------------------------------------------------------------------ #
    # Scans, constats, scores
    # ------------------------------------------------------------------ #

    def enregistrer_scan(
        self,
        organisation_id: int | None,
        resultat: ResultatScan,
        score: Score | None,
        version_methodo: str,
    ) -> int:
        """Enregistre un scan, ses constats et son score dans une seule transaction."""
        with self.transaction() as c:
            curseur = c.execute(
                """
                INSERT INTO scans (organisation_id, domaine, debut, fin, statut, version_methodo,
                                   erreurs_json, informations_json, sondes_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    organisation_id,
                    resultat.domaine,
                    resultat.debut.isoformat(),
                    resultat.fin.isoformat(),
                    resultat.statut,
                    version_methodo,
                    json.dumps(resultat.erreurs, ensure_ascii=False),
                    resultat.informations.model_dump_json(),
                    json.dumps(resultat.sondes_reussies),
                ),
            )
            scan_id = int(curseur.lastrowid or 0)
            c.executemany(
                """
                INSERT INTO constats (scan_id, ordre, sonde, categorie, cle, valeur,
                                      fournisseur_id, niveau, preuve_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        scan_id,
                        ordre,
                        constat.sonde,
                        constat.categorie,
                        constat.cle,
                        constat.valeur,
                        constat.fournisseur_id,
                        constat.niveau,
                        json.dumps(constat.preuve, ensure_ascii=False, default=str),
                    )
                    for ordre, constat in enumerate(resultat.constats)
                ],
            )
            if score is not None:
                c.execute(
                    "INSERT INTO scores (scan_id, score_global, note, detail_json) "
                    "VALUES (?, ?, ?, ?)",
                    (scan_id, score.score_global, score.note, score.model_dump_json()),
                )
        return scan_id

    def _scan(self, ligne: sqlite3.Row) -> ScanEnregistre:
        constats = [
            Constat(
                sonde=r["sonde"],
                categorie=r["categorie"],
                cle=r["cle"],
                valeur=r["valeur"],
                fournisseur_id=r["fournisseur_id"],
                niveau=r["niveau"],
                preuve=json.loads(r["preuve_json"]),
            )
            for r in self.connexion.execute(
                "SELECT * FROM constats WHERE scan_id = ? ORDER BY ordre", (ligne["id"],)
            )
        ]
        resultat = ResultatScan(
            domaine=ligne["domaine"],
            debut=datetime.fromisoformat(ligne["debut"]),
            fin=datetime.fromisoformat(ligne["fin"] or ligne["debut"]),
            statut=ligne["statut"],
            sondes_reussies=json.loads(ligne["sondes_json"]),
            constats=constats,
            informations=InformationsComplementaires.model_validate_json(
                ligne["informations_json"]
            ),
            erreurs=json.loads(ligne["erreurs_json"]),
        )
        ligne_score = self.connexion.execute(
            "SELECT detail_json FROM scores WHERE scan_id = ?", (ligne["id"],)
        ).fetchone()
        score = Score.model_validate_json(ligne_score["detail_json"]) if ligne_score else None
        return ScanEnregistre(
            id=int(ligne["id"]),
            organisation_id=ligne["organisation_id"],
            resultat=resultat,
            version_methodo=ligne["version_methodo"],
            score=score,
        )

    def scan(self, scan_id: int) -> ScanEnregistre | None:
        ligne = self.connexion.execute("SELECT * FROM scans WHERE id = ?", (scan_id,)).fetchone()
        return self._scan(ligne) if ligne else None

    def dernier_scan(self, organisation_id: int, avec_score: bool = True) -> ScanEnregistre | None:
        requete = "SELECT s.* FROM scans s"
        if avec_score:
            requete += " JOIN scores sc ON sc.scan_id = s.id"
        requete += " WHERE s.organisation_id = ? ORDER BY s.debut DESC, s.id DESC LIMIT 1"
        ligne = self.connexion.execute(requete, (organisation_id,)).fetchone()
        return self._scan(ligne) if ligne else None

    def dernier_scan_note_du_domaine(self, domaine: str, depuis: datetime) -> ScanEnregistre | None:
        """Scan noté le plus récent d'un domaine depuis une date (réutilisation d'une fiche)."""
        ligne = self.connexion.execute(
            """
            SELECT s.* FROM scans s JOIN scores sc ON sc.scan_id = s.id
            WHERE s.domaine = ? AND s.debut >= ? AND s.organisation_id IS NOT NULL
            ORDER BY s.debut DESC, s.id DESC LIMIT 1
            """,
            (domaine, depuis.astimezone(UTC).isoformat()),
        ).fetchone()
        return self._scan(ligne) if ligne else None

    def scans_notes(
        self, tous: bool = False, observatoire: bool = False
    ) -> Iterator[ScanEnregistre]:
        """Scans notés : le dernier de chaque organisation (ou tous l'historique si `tous`).

        `observatoire` écarte les scans unitaires sans organisation et les analyses sur
        demande (comme les statistiques du site).
        """
        lignes = self.connexion.execute(
            """
            WITH notes AS (
                SELECT s.id, ROW_NUMBER() OVER (
                    PARTITION BY COALESCE('organisation:' || s.organisation_id,
                                          'domaine:' || s.domaine)
                    ORDER BY s.debut DESC, s.id DESC
                ) AS rang
                FROM scans s JOIN scores sc ON sc.scan_id = s.id
            )
            SELECT s.* FROM scans s
            JOIN notes n ON n.id = s.id
            LEFT JOIN organisations o ON o.id = s.organisation_id
            WHERE (n.rang = 1 OR :tous)
              AND (NOT :observatoire OR (o.id IS NOT NULL AND o.type != 'sur_demande'))
            ORDER BY s.id
            """,
            {"tous": tous, "observatoire": observatoire},
        ).fetchall()
        for ligne in lignes:
            yield self._scan(ligne)

    def mettre_a_jour_scan(
        self,
        scan_id: int,
        constats: list[Constat],
        informations: InformationsComplementaires,
        score: Score,
        revise: bool,
    ) -> None:
        """Remplace les constats (même nombre, même ordre) et le score d'un scan recalculé.

        `revise` : constats ou score modifiés, ce qui rend obsolètes les rapports IA
        antérieurs (date enregistrée dans `scans.recalcule_le`).
        """
        with self.transaction() as c:
            c.executemany(
                """
                UPDATE constats SET sonde = ?, categorie = ?, cle = ?, valeur = ?,
                                    fournisseur_id = ?, niveau = ?, preuve_json = ?
                WHERE scan_id = ? AND ordre = ?
                """,
                [
                    (
                        constat.sonde,
                        constat.categorie,
                        constat.cle,
                        constat.valeur,
                        constat.fournisseur_id,
                        constat.niveau,
                        json.dumps(constat.preuve, ensure_ascii=False, default=str),
                        scan_id,
                        ordre,
                    )
                    for ordre, constat in enumerate(constats)
                ],
            )
            c.execute(
                """
                UPDATE scans SET informations_json = ?, version_methodo = ?,
                                 recalcule_le = CASE WHEN ? THEN ? ELSE recalcule_le END
                WHERE id = ?
                """,
                (
                    informations.model_dump_json(),
                    score.version_methodo,
                    revise,
                    _maintenant(),
                    scan_id,
                ),
            )
            c.execute(
                """
                INSERT INTO scores (scan_id, score_global, note, detail_json) VALUES (?, ?, ?, ?)
                ON CONFLICT (scan_id) DO UPDATE SET score_global = excluded.score_global,
                    note = excluded.note, detail_json = excluded.detail_json
                """,
                (scan_id, score.score_global, score.note, score.model_dump_json()),
            )

    def historique_scores(self, organisation_id: int) -> list[tuple[str, int, str]]:
        """(date, score, note) de tous les scans notés d'une organisation (phase 8)."""
        lignes = self.connexion.execute(
            """
            SELECT s.debut, sc.score_global, sc.note FROM scans s
            JOIN scores sc ON sc.scan_id = s.id
            WHERE s.organisation_id = ? ORDER BY s.debut
            """,
            (organisation_id,),
        )
        return [(r["debut"], int(r["score_global"]), r["note"]) for r in lignes]

    def statistiques_inconnus(
        self, limite: int = 30, asn_transit: Collection[int] = ()
    ) -> list[tuple[str, str, int]]:
        """Preuves non attribuées les plus fréquentes (pour enrichir fournisseurs.yaml).

        Seul le dernier scan de chaque organisation est pris en compte (les scans unitaires
        sans organisation sont regroupés par domaine), et une même preuve n'est comptée
        qu'une fois par organisation : le nombre retourné est un nombre d'organisations.
        Les adresses annoncées par un opérateur de transit (`asn_transit`) sont écartées :
        elles relèvent de `statistiques_transit`.
        """
        return self._statistiques_non_attribues(limite, asn_transit, transit=False)

    def statistiques_transit(
        self, asn_transit: Collection[int], limite: int = 30
    ) -> list[tuple[str, str, int]]:
        """Origines indéterminées : adresses annoncées par un opérateur de transit (même
        comptage que `statistiques_inconnus`)."""
        return self._statistiques_non_attribues(limite, asn_transit, transit=True)

    def _statistiques_non_attribues(
        self, limite: int, asn_transit: Collection[int], transit: bool
    ) -> list[tuple[str, str, int]]:
        lignes = self.connexion.execute(
            f"""
            WITH {CTE_DERNIERS_SCANS}
            SELECT c.scan_id, c.categorie, c.valeur, c.preuve_json FROM constats c
            JOIN derniers_scans d ON d.id = c.scan_id
            WHERE c.niveau = 'inconnu' AND c.categorie IN ('hebergement', 'messagerie', 'dns')
            """
        )
        transitaires = set(asn_transit)
        scans_par_cle: dict[tuple[str, str], set[int]] = {}
        for ligne in lignes:
            preuve: dict[str, Any] = json.loads(ligne["preuve_json"])
            est_transit = "transitaire" in preuve or preuve.get("asn") in transitaires
            if est_transit != transit:
                continue
            if preuve.get("asn"):
                cle = f"AS{preuve['asn']} {preuve.get('nom_as') or ''}".strip()
            elif preuve.get("resolution") in LIBELLES_RESOLUTION:
                # Échec de résolution : le nom complet aide à diagnostiquer
                cle = f"{ligne['valeur']} ({LIBELLES_RESOLUTION[preuve['resolution']]})"
            else:
                cle = ".".join(str(ligne["valeur"]).split(".")[-2:])
            scans_par_cle.setdefault((ligne["categorie"], cle), set()).add(ligne["scan_id"])
        comptes = [(cat, cle, len(scans)) for (cat, cle), scans in scans_par_cle.items()]
        return sorted(comptes, key=lambda e: (-e[2], e[0], e[1]))[:limite]

    # ------------------------------------------------------------------ #
    # Demandes d'analyse (tickets Codeberg)
    # ------------------------------------------------------------------ #

    def _demande(self, ligne: sqlite3.Row) -> DemandeEnregistree:
        return DemandeEnregistree(
            depot=ligne["depot"],
            numero=int(ligne["numero"]),
            auteur=ligne["auteur"],
            statut=ligne["statut"],
            recue_le=datetime.fromisoformat(ligne["recue_le"]),
            domaine=ligne["domaine"],
            motif=ligne["motif"],
            tentatives=int(ligne["tentatives"]),
            organisation_id=ligne["organisation_id"],
            acceptee_le=_date_ou_rien(ligne["acceptee_le"]),
            commentee_le=_date_ou_rien(ligne["commentee_le"]),
            cloturee_le=_date_ou_rien(ligne["cloturee_le"]),
        )

    def demande(self, depot: str, numero: int) -> DemandeEnregistree | None:
        ligne = self.connexion.execute(
            "SELECT * FROM demandes WHERE depot = ? AND numero = ?", (depot, numero)
        ).fetchone()
        return self._demande(ligne) if ligne else None

    def enregistrer_demande(self, demande: DemandeEnregistree) -> None:
        """Crée ou met à jour le suivi d'une demande."""
        with self.transaction() as c:
            c.execute(
                """
                INSERT INTO demandes (depot, numero, auteur, domaine, statut, motif, tentatives,
                                      organisation_id, recue_le, acceptee_le, commentee_le,
                                      cloturee_le, maj_le)
                VALUES (:depot, :numero, :auteur, :domaine, :statut, :motif, :tentatives,
                        :organisation_id, :recue_le, :acceptee_le, :commentee_le,
                        :cloturee_le, :maj_le)
                ON CONFLICT (depot, numero) DO UPDATE SET
                    domaine = excluded.domaine, statut = excluded.statut,
                    motif = excluded.motif, tentatives = excluded.tentatives,
                    organisation_id = excluded.organisation_id,
                    acceptee_le = excluded.acceptee_le, commentee_le = excluded.commentee_le,
                    cloturee_le = excluded.cloturee_le, maj_le = excluded.maj_le
                """,
                {
                    "depot": demande.depot,
                    "numero": demande.numero,
                    "auteur": demande.auteur,
                    "domaine": demande.domaine,
                    "statut": demande.statut,
                    "motif": demande.motif,
                    "tentatives": demande.tentatives,
                    "organisation_id": demande.organisation_id,
                    "recue_le": _iso_ou_rien(demande.recue_le),
                    "acceptee_le": _iso_ou_rien(demande.acceptee_le),
                    "commentee_le": _iso_ou_rien(demande.commentee_le),
                    "cloturee_le": _iso_ou_rien(demande.cloturee_le),
                    "maj_le": _maintenant(),
                },
            )

    def demandes_acceptees_depuis(self, depuis: datetime) -> list[DemandeEnregistree]:
        """Demandes acceptées (comptées dans les limites) depuis une date, tous dépôts."""
        lignes = self.connexion.execute(
            "SELECT * FROM demandes WHERE acceptee_le >= ? ORDER BY acceptee_le",
            (depuis.astimezone(UTC).isoformat(),),
        )
        return [self._demande(ligne) for ligne in lignes]

    # ------------------------------------------------------------------ #
    # Contours des communes (carte de situation)
    # ------------------------------------------------------------------ #

    def enregistrer_contour(
        self,
        code_commune: str,
        coordonnees: list[list[list[list[float]]]],
        source: str,
        maj_le: datetime,
    ) -> None:
        """Enregistre (ou remplace) le contour simplifié d'une commune (MultiPolygon)."""
        with self.transaction() as c:
            c.execute(
                "INSERT OR REPLACE INTO contours (code_commune, geometrie_json, source, maj_le) "
                "VALUES (?, ?, ?, ?)",
                (
                    code_commune,
                    json.dumps(coordonnees, separators=(",", ":")),
                    source,
                    maj_le.astimezone(UTC).isoformat(),
                ),
            )

    def contour_commune(self, code_commune: str) -> list[list[list[list[float]]]] | None:
        ligne = self.connexion.execute(
            "SELECT geometrie_json FROM contours WHERE code_commune = ?", (code_commune,)
        ).fetchone()
        return json.loads(ligne["geometrie_json"]) if ligne else None

    def codes_communes_avec_contour(self) -> set[str]:
        return {
            r["code_commune"] for r in self.connexion.execute("SELECT code_commune FROM contours")
        }

    def codes_communes_cibles(self) -> list[str]:
        """Codes INSEE des organisations de type commune (cibles de l'observatoire)."""
        lignes = self.connexion.execute(
            "SELECT DISTINCT code_commune FROM organisations "
            "WHERE type = 'commune' AND code_commune IS NOT NULL ORDER BY code_commune"
        )
        return [r["code_commune"] for r in lignes]

    # ------------------------------------------------------------------ #
    # Rapports IA
    # ------------------------------------------------------------------ #

    def rapport_en_cache(
        self, empreinte: str, modele: str, version_invite: str
    ) -> RapportEnregistre | None:
        ligne = self.connexion.execute(
            """
            SELECT * FROM rapports_ia
            WHERE empreinte_constats = ? AND modele = ? AND version_invite = ?
              AND statut = 'valide'
            ORDER BY id DESC LIMIT 1
            """,
            (empreinte, modele, version_invite),
        ).fetchone()
        return self._rapport(ligne) if ligne else None

    def _rapport(self, ligne: sqlite3.Row) -> RapportEnregistre:
        return RapportEnregistre(
            contenu=RapportIA.model_validate_json(ligne["contenu_json"]),
            modele=ligne["modele"],
            version_invite=ligne["version_invite"],
            cree_le=datetime.fromisoformat(ligne["cree_le"]),
        )

    def enregistrer_rapport(
        self,
        scan_id: int,
        empreinte: str,
        modele: str,
        version_invite: str,
        contenu: RapportIA | None,
        erreur: str | None = None,
        jetons: tuple[int, int] | None = None,
    ) -> None:
        with self.transaction() as c:
            c.execute(
                """
                INSERT INTO rapports_ia (scan_id, empreinte_constats, modele, version_invite,
                                         contenu_json, statut, erreur, jetons_entree,
                                         jetons_sortie, cree_le)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scan_id,
                    empreinte,
                    modele,
                    version_invite,
                    contenu.model_dump_json() if contenu else None,
                    "valide" if contenu else "erreur",
                    erreur,
                    jetons[0] if jetons else None,
                    jetons[1] if jetons else None,
                    _maintenant(),
                ),
            )

    def rapport_du_scan(self, scan_id: int) -> RapportEnregistre | None:
        """Dernier rapport valide du scan, s'il n'a pas été rendu obsolète par un recalcul
        (constats ou score modifiés après sa rédaction)."""
        ligne = self.connexion.execute(
            """
            SELECT r.* FROM rapports_ia r JOIN scans s ON s.id = r.scan_id
            WHERE r.scan_id = ? AND r.statut = 'valide'
              AND (s.recalcule_le IS NULL OR r.cree_le >= s.recalcule_le)
            ORDER BY r.id DESC LIMIT 1
            """,
            (scan_id,),
        ).fetchone()
        return self._rapport(ligne) if ligne else None

    # ------------------------------------------------------------------ #
    # Retraits
    # ------------------------------------------------------------------ #

    def synchroniser_retraits(self, retraits: dict[str, Retrait]) -> None:
        """Recopie retraits.yaml dans la base (la source de vérité reste le YAML)."""
        with self.transaction() as c:
            c.execute("DELETE FROM retraits")
            c.executemany(
                "INSERT INTO retraits (domaine, date_demande, motif) VALUES (?, ?, ?)",
                [(r.domaine, r.date_demande, r.motif) for r in retraits.values()],
            )
