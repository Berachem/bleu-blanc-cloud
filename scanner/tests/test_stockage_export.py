"""Tests du stockage SQLite, de l'export statique, des schémas et des alternatives."""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from bleublanccloud.analyse.alternatives import choisir_alternatives
from bleublanccloud.analyse.score import VERSION_METHODO, calculer_score
from bleublanccloud.cli import app
from bleublanccloud.export.demonstration import generer_demonstration
from bleublanccloud.export.schemas import ecrire_schema, schema_donnees_site
from bleublanccloud.export.site_statique import domaine_organisation, exporter
from bleublanccloud.modeles import (
    Constat,
    EntreeIndex,
    MetaExport,
    Organisation,
    OrganisationExport,
    RapportIA,
    ResultatScan,
    Retrait,
)
from bleublanccloud.referentiels import Referentiels
from bleublanccloud.stockage.base import Base


def organisation(slug: str = "exempleville-99999", **champs: object) -> Organisation:
    donnees: dict[str, object] = {
        "slug": slug,
        "nom": "Commune d'Exempleville",
        "type": "commune",
        "code_commune": "99999",
        "departement": "33",
        "region": "75",
        "population": 48_200,
        "site_web": "https://www.exempleville.fr/",
        "source": "test",
    }
    donnees.update(champs)
    return Organisation.model_validate(donnees)


def resultat(domaine: str = "exempleville.fr", jour: int = 1) -> ResultatScan:
    constats = [
        Constat(sonde="ip", categorie="hebergement", cle="hebergeur", valeur="51.91.0.1",
                fournisseur_id="ovhcloud", niveau="A", preuve={"ip": "51.91.0.1"}),
        Constat(sonde="dns", categorie="messagerie", cle="mx", valeur="v.mail.protection.outlook.com",  # noqa: E501
                fournisseur_id="microsoft", niveau="D"),
        Constat(sonde="dns", categorie="dns", cle="ns", valeur="dns10.ovh.net",
                fournisseur_id="ovhcloud", niveau="A"),
        Constat(sonde="http", categorie="services_tiers", cle="script_tiers", valeur="YouTube",
                fournisseur_id="google", niveau="D",
                preuve={"regle": "youtube", "type_service": "videos"}),
        Constat(sonde="http", categorie="mesure_audience", cle="cookie", valeur="Google Analytics",
                fournisseur_id="google", niveau="D",
                preuve={"regle": "google-analytics", "type_service": "analytique"}),
    ]  # fmt: skip
    date = datetime(2026, 9, jour, 3, tzinfo=UTC)
    return ResultatScan(
        domaine=domaine,
        debut=date,
        fin=date,
        statut="termine",
        sondes_reussies=["dns", "http"],
        constats=constats,
    )


@pytest.fixture
def base() -> Base:
    with Base(":memory:") as b:
        yield b  # type: ignore[misc]


def test_migrations_idempotentes(tmp_path: Path) -> None:
    chemin = tmp_path / "donnees" / "test.db"
    with Base(chemin) as b:
        assert b.migrer() == []
    with Base(chemin) as b:
        versions = [r["version"] for r in b.connexion.execute("SELECT version FROM migrations")]
    assert versions == ["001_initial"]


def test_organisation_upsert(base: Base) -> None:
    identifiant = base.enregistrer_organisation(organisation())
    meme = base.enregistrer_organisation(organisation(population=50_000, site_web=None))
    assert identifiant == meme
    enregistree = base.organisation_par_slug("exempleville-99999")
    assert enregistree is not None
    assert enregistree.organisation.population == 50_000
    # Un site web absent lors d'une mise à jour ne doit pas effacer le précédent
    assert enregistree.organisation.site_web == "https://www.exempleville.fr/"
    assert base.organisation_par_slug("inconnue") is None


def test_organisations_tri_et_filtre(base: Base) -> None:
    base.enregistrer_organisation(organisation("a", population=10))
    base.enregistrer_organisation(organisation("b", population=1000))
    base.enregistrer_organisation(organisation("c", population=None, site_web=None))
    assert [o.organisation.slug for o in base.organisations()] == ["b", "a", "c"]
    assert [o.organisation.slug for o in base.organisations(avec_site=True, limite=1)] == ["b"]


def test_scan_aller_retour(base: Base) -> None:
    org_id = base.enregistrer_organisation(organisation())
    res = resultat()
    score = calculer_score(res.constats, res.sondes_reussies)
    scan_id = base.enregistrer_scan(org_id, res, score, VERSION_METHODO)
    relu = base.scan(scan_id)
    assert relu is not None
    assert relu.resultat == res
    assert relu.score == score
    assert base.scan(9999) is None


def test_dernier_scan_et_historique(base: Base) -> None:
    org_id = base.enregistrer_organisation(organisation())
    for jour in (1, 8, 15):
        res = resultat(jour=jour)
        base.enregistrer_scan(org_id, res, calculer_score(res.constats), VERSION_METHODO)
    base.enregistrer_scan(org_id, resultat(jour=22), None, VERSION_METHODO)
    dernier = base.dernier_scan(org_id)
    assert dernier is not None and dernier.resultat.debut.day == 15
    sans_score = base.dernier_scan(org_id, avec_score=False)
    assert sans_score is not None and sans_score.score is None
    assert len(base.historique_scores(org_id)) == 3


def test_rapports_ia_cache(base: Base) -> None:
    org_id = base.enregistrer_organisation(organisation())
    scan_id = base.enregistrer_scan(org_id, resultat(), None, VERSION_METHODO)
    rapport = RapportIA(resume_decideur="Résumé.", points_forts=[], risques=[], plan_migration=[])
    base.enregistrer_rapport(scan_id, "empreinte", "modele", "1.0", None, erreur="invalide")
    assert base.rapport_en_cache("empreinte", "modele", "1.0") is None
    base.enregistrer_rapport(scan_id, "empreinte", "modele", "1.0", rapport, jetons=(100, 50))
    cache = base.rapport_en_cache("empreinte", "modele", "1.0")
    assert cache is not None and cache.contenu == rapport
    assert base.rapport_en_cache("empreinte", "autre-modele", "1.0") is None
    assert base.rapport_du_scan(scan_id) is not None


def test_territoires_et_retraits(base: Base) -> None:
    base.enregistrer_territoire("departement", "33", "Gironde", "75")
    base.enregistrer_territoire("departement", "33", "Gironde", "75")
    assert base.territoires("departement") == {"33": ("Gironde", "75")}
    base.synchroniser_retraits({"a.fr": Retrait(domaine="a.fr", date_demande="2026-01-01")})
    assert base.connexion.execute("SELECT COUNT(*) FROM retraits").fetchone()[0] == 1


def test_statistiques_inconnus(base: Base) -> None:
    res = resultat()
    res.constats.append(
        Constat(sonde="ip", categorie="hebergement", cle="hebergeur", valeur="192.0.2.1",
                niveau="inconnu", preuve={"asn": 64500, "nom_as": "PETIT HEBERGEUR"})
    )  # fmt: skip
    res.constats.append(
        Constat(
            sonde="dns", categorie="dns", cle="ns", valeur="ns1.prestataire.fr", niveau="inconnu"
        )
    )
    base.enregistrer_scan(None, res, None, VERSION_METHODO)
    stats = base.statistiques_inconnus()
    assert ("hebergement", "AS64500 PETIT HEBERGEUR", 1) in stats
    assert ("dns", "prestataire.fr", 1) in stats


# --------------------------------------------------------------------------- #
# Alternatives et export
# --------------------------------------------------------------------------- #


def test_choisir_alternatives(referentiels: Referentiels) -> None:
    res = resultat()
    score = calculer_score(res.constats)
    ids = [a.id for a in choisir_alternatives(score, res.constats, referentiels.alternatives)]
    assert "peertube" in ids  # vidéos
    assert "matomo-auto-heberge" in ids  # mesure d'audience
    assert "suite-territoriale" in ids  # messagerie
    assert not any(referentiels.alternatives[i].categorie == "hebergement" for i in ids)


def test_alternatives_cdn_prioritaire(referentiels: Referentiels) -> None:
    constats = [
        Constat(sonde="ip", categorie="hebergement", cle="cdn", valeur="104.16.1.1",
                fournisseur_id="cloudflare", niveau="C"),
    ]  # fmt: skip
    score = calculer_score(constats, ["dns"])
    ids = [a.id for a in choisir_alternatives(score, constats, referentiels.alternatives)]
    assert ids[0] == "bunny-cdn"


def test_exporter(base: Base, referentiels: Referentiels, tmp_path: Path) -> None:
    base.enregistrer_territoire("departement", "33", "Gironde", "75")
    base.enregistrer_territoire("region", "75", "Nouvelle-Aquitaine")
    org_id = base.enregistrer_organisation(organisation())
    res = resultat()
    base.enregistrer_scan(org_id, res, calculer_score(res.constats), VERSION_METHODO)
    sans_scan = base.enregistrer_organisation(organisation("sans-scan", nom="Sans scan"))
    assert sans_scan
    (tmp_path / "organisations").mkdir()
    (tmp_path / "organisations" / "ancienne.json").write_text("{}")

    rapport = exporter(base, referentiels, tmp_path)
    assert rapport.nombre_organisations == 1
    assert rapport.fichiers_supprimes == 1

    meta = MetaExport.model_validate_json((tmp_path / "meta.json").read_text())
    assert meta.nombre_organisations == 1 and meta.version_methodo == VERSION_METHODO
    index = [
        EntreeIndex.model_validate(e) for e in json.loads((tmp_path / "index.json").read_text())
    ]
    assert [e.slug for e in index] == ["exempleville-99999"]
    detail = OrganisationExport.model_validate_json(
        (tmp_path / "organisations" / "exempleville-99999.json").read_text()
    )
    assert detail.departement_nom == "Gironde"
    assert detail.region_nom == "Nouvelle-Aquitaine"
    assert set(detail.fournisseurs) == {"ovhcloud", "microsoft", "google"}
    assert detail.fournisseurs["microsoft"].niveau == "D"
    assert detail.alternatives
    departements = json.loads((tmp_path / "departements.json").read_text())
    assert departements[0]["code"] == "33" and departements[0]["nombre_organisations"] == 1
    assert len(json.loads((tmp_path / "alternatives.json").read_text())) == len(
        referentiels.alternatives
    )
    texte = (tmp_path / "organisations" / "exempleville-99999.json").read_text()
    assert "@" not in texte.replace("@context", "")  # aucune adresse e-mail exportée


def test_exporter_ignore_les_retraits(
    base: Base, referentiels: Referentiels, tmp_path: Path
) -> None:
    org_id = base.enregistrer_organisation(organisation())
    res = resultat()
    base.enregistrer_scan(org_id, res, calculer_score(res.constats), VERSION_METHODO)
    avec_retrait = dataclasses.replace(
        referentiels,
        retraits={"exempleville.fr": Retrait(domaine="exempleville.fr", date_demande="2026-01-01")},
    )
    rapport = exporter(base, avec_retrait, tmp_path)
    assert rapport.nombre_organisations == 0
    assert rapport.ignorees == ["exempleville-99999 (retrait demandé)"]


def test_domaine_organisation() -> None:
    assert domaine_organisation(organisation()) == "exempleville.fr"
    assert domaine_organisation(organisation(site_web=None)) is None
    assert domaine_organisation(organisation(site_web="pas une url")) is None


def test_schema_donnees_site(tmp_path: Path) -> None:
    schema = schema_donnees_site()
    assert {"MetaExport", "EntreeIndex", "OrganisationExport", "Constat", "Score"} <= set(
        schema["$defs"]
    )
    chemin = ecrire_schema(tmp_path)
    assert json.loads(chemin.read_text())["title"] == "DonneesSite"


def test_demonstration(referentiels: Referentiels) -> None:
    organisations = generer_demonstration(referentiels)
    notes = {o.score.note for o in organisations}
    assert notes == {"A", "B", "C", "D", "E"}
    assert all(o.domaine.endswith(".example") for o in organisations)
    assert all(o.slug.endswith("-demo") for o in organisations)
    for o in organisations:
        for etape in o.rapport_ia.contenu.plan_migration if o.rapport_ia else []:
            assert etape.alternative_id is None or etape.alternative_id in referentiels.alternatives


def test_cli_export_demo_schemas(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHEMIN_BASE_SQLITE", str(tmp_path / "base.db"))
    from bleublanccloud import configuration

    configuration.obtenir_parametres.cache_clear()
    lanceur = CliRunner()
    assert lanceur.invoke(app, ["demo", "--vers", str(tmp_path / "demo")]).exit_code == 0
    assert (tmp_path / "demo" / "meta.json").exists()
    assert lanceur.invoke(app, ["schemas", "--vers", str(tmp_path / "types")]).exit_code == 0
    resultat_export = lanceur.invoke(app, ["exporter", "--vers", str(tmp_path / "export")])
    assert resultat_export.exit_code == 0, resultat_export.output
    assert "0 organisation" in resultat_export.output
    configuration.obtenir_parametres.cache_clear()


def test_exporter_recalcule_un_score_d_une_ancienne_methodologie(
    base: Base, referentiels: Referentiels, tmp_path: Path
) -> None:
    org_id = base.enregistrer_organisation(organisation())
    res = resultat()
    res.constats = [
        Constat(sonde="ip", categorie="hebergement", cle="hebergeur", valeur="192.0.2.1",
                niveau="inconnu"),
        Constat(sonde="dns", categorie="messagerie", cle="mx", valeur="mx.ovh.net",
                fournisseur_id="ovhcloud", niveau="A"),
        Constat(sonde="dns", categorie="dns", cle="ns", valeur="ns.inconnu.fr", niveau="inconnu"),
    ]  # fmt: skip
    ancien = calculer_score(res.constats).model_copy(update={"version_methodo": "1.0"})
    ancien = ancien.model_copy(update={"provisoire": False, "couverture": 100.0})
    base.enregistrer_scan(org_id, res, ancien, "1.0")

    exporter(base, referentiels, tmp_path)
    detail = OrganisationExport.model_validate_json(
        (tmp_path / "organisations" / "exempleville-99999.json").read_text()
    )
    assert detail.score.version_methodo == VERSION_METHODO
    assert detail.score.provisoire and detail.score.couverture == 65.0
    [entree] = json.loads((tmp_path / "index.json").read_text())
    assert entree["note_provisoire"] is True
