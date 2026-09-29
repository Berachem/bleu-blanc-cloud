"""Suites de la campagne complète : nouveaux fournisseurs, réseaux de transit (origine
indéterminée), recalcul des scores sans rescanner et couverture de l'observatoire."""

from __future__ import annotations

import dataclasses
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from bleublanccloud.analyse.attribution import (
    ORIGINE_INDETERMINEE,
    Attributeur,
    constat_hebergement,
    constats_dns_informatifs,
    constats_serveurs,
)
from bleublanccloud.analyse.couverture import mesurer_couverture
from bleublanccloud.analyse.reattribution import info_ip_depuis_preuve, reattribuer_constats
from bleublanccloud.analyse.score import calculer_score
from bleublanccloud.cli import app
from bleublanccloud.configuration import DOSSIER_REFERENTIELS
from bleublanccloud.modeles import Constat, Organisation, RapportIA, ResultatScan
from bleublanccloud.recalcul import couverture_observatoire, recalculer_scores
from bleublanccloud.referentiels import ErreurReferentiel, Referentiels, charger_referentiels
from bleublanccloud.sondes.dns import ChaineResolution, DonneesDns
from bleublanccloud.sondes.ip import InfoIp
from bleublanccloud.stockage.base import Base

COGENT = InfoIp(ip="192.0.2.50", asn=174, nom_as="Cogent Communications, LLC", pays="US")


def attributeur_courant(referentiels: Referentiels) -> Attributeur:
    return Attributeur(referentiels.fournisseurs, referentiels.transitaires.values())


@pytest.fixture
def base() -> Base:
    with Base(":memory:") as b:
        yield b  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# 1. Fournisseurs relevés après la campagne complète
# --------------------------------------------------------------------------- #

ASN_CAMPAGNE_COMPLETE = [
    (15401, "Orange Business Services SA", "orange", "A"),
    (16347, "ADISTA SAS", "adista", "A"),
    (34177, "Celeste SAS", "celeste", "A"),
    (8362, "NordNet SA", "nordnet", "A"),
    (39444, "OWENTIS SAS", "owentis", "A"),
    (41653, "Aqua Ray SAS", "aqua-ray", "A"),
    (50818, "Muona SAS", "muona", "A"),
    (39729, "REGISTER S.P.A.", "register-it", "A"),
    (31178, "Celeonet SAS", "celeonet", "A"),
    (44407, "Linkt SAS", "linkt", "A"),
    (60068, "Datacamp Limited", "datacamp", "B"),
    (60362, "alwaysdata SARL", "alwaysdata", "A"),
    (1921, "RcodeZero Anycast DNS", "rcodezero", "A"),
    (207021, "RcodeZero Anycast DNS", "rcodezero", "A"),
    (20473, "The Constant Company, LLC", "vultr", "D"),
    (41628, "Alter Way SAS", "alter-way", "A"),
    (53589, "PlanetHoster", "planethoster", "B"),
    (34306, "SOCIETE REUNIONNAISE DU RADIOTELEPHONE SCS", "srr", "A"),
    (48426, "OVER-LINK s.a.s.", "over-link", "A"),
    (48594, "WISTEE SAS", "wistee", "A"),
    (49544, "i3D.net B.V", "i3d-net", "A"),
]


@pytest.mark.parametrize(("asn", "nom_as", "fournisseur_id", "niveau"), ASN_CAMPAGNE_COMPLETE)
def test_asn_de_la_campagne_complete_attribues(
    referentiels: Referentiels, asn: int, nom_as: str, fournisseur_id: str, niveau: str
) -> None:
    attributeur = attributeur_courant(referentiels)
    correspondance = attributeur.par_ip(InfoIp(ip="192.0.2.1", asn=asn, nom_as=nom_as))
    assert correspondance is not None
    assert correspondance.fournisseur.id == fournisseur_id
    assert correspondance.methode == "asn"
    assert attributeur.niveau(correspondance.fournisseur) == niveau
    fournisseur = referentiels.fournisseurs[fournisseur_id]
    assert fournisseur.sources and fournisseur.a_verifier


# --------------------------------------------------------------------------- #
# 2. Réseaux de transit : jamais attribués comme hébergeur
# --------------------------------------------------------------------------- #


def test_transitaires_charges_avec_sources(referentiels: Referentiels) -> None:
    assert 174 in referentiels.transitaires["cogent"].asn
    for transitaire in referentiels.transitaires.values():
        assert transitaire.sources and transitaire.a_verifier, transitaire.id


def test_asn_de_transit_jamais_attribue(referentiels: Referentiels) -> None:
    attributeur = attributeur_courant(referentiels)
    assert attributeur.par_ip(COGENT) is None
    transitaire = attributeur.transitaire(COGENT)
    assert transitaire is not None and transitaire.id == "cogent"


def test_hebergement_derriere_un_transitaire_origine_indeterminee(
    referentiels: Referentiels,
) -> None:
    resolution = ChaineResolution(nom="www.exempleville.fr", ipv4=[COGENT.ip])
    constat = constat_hebergement(resolution, COGENT, {}, attributeur_courant(referentiels))
    assert constat is not None
    assert (constat.fournisseur_id, constat.niveau) == (None, "inconnu")
    assert constat.preuve["attribution"] == ORIGINE_INDETERMINEE
    assert constat.preuve["transitaire"] == {
        "id": "cogent",
        "nom": "Cogent Communications",
        "asn": 174,
    }


def test_nom_hote_et_plage_publiee_prioritaires_sur_le_transit(referentiels: Referentiels) -> None:
    attributeur = attributeur_courant(referentiels)
    resolution = ChaineResolution(
        nom="www.exempleville.fr", cnames=["exempleville.cluster021.hosting.ovh.net"],
        ipv4=[COGENT.ip],
    )  # fmt: skip
    constat = constat_hebergement(resolution, COGENT, {}, attributeur)
    assert constat is not None and constat.fournisseur_id == "ovhcloud"
    assert "transitaire" not in constat.preuve

    dans_aws = COGENT.model_copy(update={"plage_cloud": "aws", "prefixe": "192.0.2.0/24"})
    assert attributeur.transitaire(dans_aws) is None
    correspondance = attributeur.par_ip(dans_aws)
    assert correspondance is not None and correspondance.fournisseur.id == "aws"


def test_serveur_dns_derriere_un_transitaire(referentiels: Referentiels) -> None:
    [constat] = constats_serveurs(
        "ns", [("ns1.exempleville.fr", None)], {"ns1.exempleville.fr": COGENT},
        attributeur_courant(referentiels),
    )  # fmt: skip
    assert constat.niveau == "inconnu"
    assert constat.preuve["attribution"] == ORIGINE_INDETERMINEE
    assert constat.preuve["transitaire"]["id"] == "cogent"


def test_score_explique_l_origine_indeterminee(referentiels: Referentiels) -> None:
    resolution = ChaineResolution(nom="www.exempleville.fr", ipv4=[COGENT.ip])
    constat = constat_hebergement(resolution, COGENT, {}, attributeur_courant(referentiels))
    assert constat is not None
    score = calculer_score([constat], ["dns", "http"])
    [hebergement] = [d for d in score.detail if d.categorie == "hebergement"]
    assert hebergement.exclusion == "inconnu"
    assert "origine indéterminée" in hebergement.explication


def _copier_referentiels(dossier: Path) -> None:
    for fichier in DOSSIER_REFERENTIELS.glob("*.yaml"):
        shutil.copy(fichier, dossier / fichier.name)


def test_asn_a_la_fois_transitaire_et_fournisseur_refuse(tmp_path: Path) -> None:
    _copier_referentiels(tmp_path)
    with (tmp_path / "transitaires.yaml").open("a", encoding="utf-8") as fichier:
        fichier.write(
            "\n- id: faux-transit\n  nom: Faux transit\n  asn: [16276]\n"
            '  sources: ["https://bgp.tools/as/16276"]\n'
        )
    with pytest.raises(ErreurReferentiel, match="AS16276"):
        charger_referentiels(tmp_path)


def test_referentiel_des_transitaires_facultatif(tmp_path: Path) -> None:
    _copier_referentiels(tmp_path)
    (tmp_path / "transitaires.yaml").unlink()
    assert charger_referentiels(tmp_path).transitaires == {}


def _resultat(domaine: str, constats: list[Constat], jour: int = 1) -> ResultatScan:
    date = datetime(2026, 9, jour, 3, tzinfo=UTC)
    return ResultatScan(
        domaine=domaine, debut=date, fin=date, statut="termine",
        sondes_reussies=["dns", "http"], constats=constats,
    )  # fmt: skip


def test_statistiques_transit_separees(base: Base) -> None:
    constats = [
        # Scan antérieur à la gestion des transitaires : reconnu par son ASN
        Constat(sonde="ip", categorie="hebergement", cle="hebergeur", valeur="192.0.2.50",
                niveau="inconnu", preuve={"asn": 174, "nom_as": "Cogent Communications, LLC"}),
        Constat(sonde="ip", categorie="dns", cle="ns", valeur="ns1.exempleville.fr",
                niveau="inconnu", preuve={"asn": 64500, "nom_as": "PETIT HEBERGEUR"}),
        Constat(sonde="ip", categorie="messagerie", cle="mx", valeur="mx.exempleville.fr",
                niveau="inconnu", preuve={"asn": 3356, "nom_as": "Level 3", "transitaire": {}}),
    ]  # fmt: skip
    base.enregistrer_scan(None, _resultat("exempleville.fr", constats), None, "1.2")
    assert base.statistiques_inconnus(asn_transit=[174]) == [("dns", "AS64500 PETIT HEBERGEUR", 1)]
    assert base.statistiques_transit([174]) == [
        ("hebergement", "AS174 Cogent Communications, LLC", 1),
        ("messagerie", "AS3356 Level 3", 1),
    ]


# --------------------------------------------------------------------------- #
# 3. Réattribution et recalcul sans rescanner
# --------------------------------------------------------------------------- #


def anciens_referentiels(referentiels: Referentiels) -> Referentiels:
    """Référentiels d'avant la mise à jour : ni ADISTA, ni Celeste, ni transitaires."""
    fournisseurs = {
        cle: f for cle, f in referentiels.fournisseurs.items() if cle not in ("adista", "celeste")
    }
    return dataclasses.replace(referentiels, fournisseurs=fournisseurs, transitaires={})


def constats_scannes(referentiels: Referentiels) -> list[Constat]:
    """Constats tels que les produit un scan avec les référentiels donnés."""
    attributeur = attributeur_courant(referentiels)
    adista = InfoIp(ip="192.0.2.10", asn=16347, nom_as="ADISTA SAS", pays="FR")
    celeste = InfoIp(ip="192.0.2.25", asn=34177, nom_as="Celeste SAS", pays="FR")
    hebergement = constat_hebergement(
        ChaineResolution(nom="www.exempleville.fr", ipv4=[adista.ip]), adista, {}, attributeur
    )
    assert hebergement is not None
    youtube = Constat(
        sonde="http", categorie="services_tiers", cle="iframe", valeur="YouTube",
        fournisseur_id="google", niveau="D",
        preuve={"regle": "youtube", "type_service": "videos", "signal_positif": False},
    )  # fmt: skip
    return [
        hebergement,
        *constats_serveurs(
            "mx", [("mx.exempleville.fr", 10)], {"mx.exempleville.fr": celeste}, attributeur
        ),
        *constats_serveurs(
            "ns",
            [("ns1.exempleville.fr", None), ("dns10.ovh.net", None)],
            {"ns1.exempleville.fr": COGENT},
            attributeur,
        ),
        youtube,
        *constats_dns_informatifs(DonneesDns(domaine="exempleville.fr")),
    ]


def test_info_ip_reconstituee_depuis_la_preuve() -> None:
    preuve = {"hote": "mx.exemple.fr", **COGENT.model_dump(exclude_none=True), "priorite": 5}
    assert info_ip_depuis_preuve(preuve) == COGENT
    assert info_ip_depuis_preuve({"hote": "mx.exemple.fr"}) is None


def test_reattribution_des_constats(referentiels: Referentiels) -> None:
    anciens = constats_scannes(anciens_referentiels(referentiels))
    assert [c.niveau for c in anciens[:3]] == ["inconnu", "inconnu", "inconnu"]

    nouveaux = reattribuer_constats(anciens, attributeur_courant(referentiels), referentiels.regles)
    assert len(nouveaux) == len(anciens)
    assert (nouveaux[0].fournisseur_id, nouveaux[0].niveau) == ("adista", "A")
    assert nouveaux[0].preuve["ip"] == "192.0.2.10"
    assert nouveaux[0].preuve["attribution"]["methode"] == "asn"
    assert (nouveaux[1].fournisseur_id, nouveaux[1].niveau) == ("celeste", "A")
    assert nouveaux[1].preuve["priorite"] == 10
    assert nouveaux[2].niveau == "inconnu"
    assert nouveaux[2].preuve["attribution"] == ORIGINE_INDETERMINEE
    assert nouveaux[3:] == anciens[3:]
    # Relancer la réattribution ne change plus rien
    attributeur = attributeur_courant(referentiels)
    assert reattribuer_constats(nouveaux, attributeur, referentiels.regles) == nouveaux
    # Et un scan fait avec les référentiels courants est déjà à jour
    recents = constats_scannes(referentiels)
    assert reattribuer_constats(recents, attributeur, referentiels.regles) == recents


def test_reattribution_relit_le_niveau_des_services(referentiels: Referentiels) -> None:
    google = referentiels.fournisseurs["google"].model_copy(update={"soumis_cloud_act": False})
    modifies = dataclasses.replace(
        referentiels, fournisseurs={**referentiels.fournisseurs, "google": google}
    )
    anciens = constats_scannes(referentiels)
    nouveaux = reattribuer_constats(anciens, attributeur_courant(modifies), modifies.regles)
    assert anciens[4].niveau == "D" and nouveaux[4].niveau == "B"


def test_reattribution_d_un_cdn_garde_l_origine_revelee(referentiels: Referentiels) -> None:
    attributeur = attributeur_courant(referentiels)
    cloudflare = InfoIp(ip="104.16.1.1", asn=13335, nom_as="Cloudflare, Inc.", pays="US")
    resolution = ChaineResolution(nom="www.exempleville.fr", ipv4=[cloudflare.ip])
    # Origine révélée par un en-tête (Netlify) : seul cet en-tête est conservé dans la preuve
    en_tetes = {"x-nf-request-id": "01ABC", "content-type": "text/html"}
    avec_origine = constat_hebergement(resolution, cloudflare, en_tetes, attributeur)
    assert avec_origine is not None
    assert avec_origine.preuve["origine"]["fournisseur_id"] == "netlify"
    sans_origine = constat_hebergement(resolution, cloudflare, {}, attributeur)
    assert sans_origine is not None and sans_origine.preuve["origine"] == "masquée par le CDN"
    for constat in (avec_origine, sans_origine):
        [recalcule] = reattribuer_constats([constat], attributeur, referentiels.regles)
        assert recalcule == constat


def _enregistrer(base: Base, slug: str, constats: list[Constat], **champs: object) -> int:
    donnees: dict[str, object] = {
        "slug": slug, "nom": slug.title(), "type": "commune", "departement": "54",
        "site_web": f"https://www.{slug}.fr/", "source": "test",
    }  # fmt: skip
    donnees.update(champs)
    org_id = base.enregistrer_organisation(Organisation.model_validate(donnees))
    resultat = _resultat(f"{slug}.fr", constats)
    base.enregistrer_scan(org_id, resultat, calculer_score(constats), "1.2")
    return org_id


RAPPORT = RapportIA(resume_decideur="Résumé.", points_forts=[], risques=[], plan_migration=[])


def test_recalculer_scores_sans_rescanner(base: Base, referentiels: Referentiels) -> None:
    ancienne = _enregistrer(
        base, "exempleville", constats_scannes(anciens_referentiels(referentiels))
    )
    a_jour = _enregistrer(base, "testbourg", constats_scannes(referentiels))
    for org_id in (ancienne, a_jour):
        scan = base.dernier_scan(org_id)
        assert scan is not None
        base.enregistrer_rapport(scan.id, "empreinte", "modele", "1.0", RAPPORT)
    scan_ancien = base.dernier_scan(ancienne)
    assert scan_ancien is not None and scan_ancien.score is not None
    assert scan_ancien.score.provisoire

    # Simulation : rien n'est écrit
    simulation = recalculer_scores(base, referentiels, appliquer=False)
    assert (simulation.scans_examines, simulation.scans_modifies) == (2, 1)
    assert simulation.constats_modifies == 3
    assert simulation.rapports_obsoletes == 1
    assert base.dernier_scan(ancienne) == scan_ancien
    assert base.rapport_du_scan(scan_ancien.id) is not None

    bilan = recalculer_scores(base, referentiels)
    assert bilan.scans_modifies == 1
    [changement] = bilan.changements
    assert changement.organisation_id == ancienne
    assert changement.ancien_provisoire and not changement.nouveau_provisoire
    assert bilan.notes_modifiees == [changement]
    assert bilan.couverture_apres.part_inconnue < bilan.couverture_avant.part_inconnue

    recalcule = base.dernier_scan(ancienne)
    assert recalcule is not None and recalcule.score is not None
    assert recalcule.id == scan_ancien.id  # même scan, pas de nouveau scan
    assert recalcule.resultat.constats[0].fournisseur_id == "adista"
    assert recalcule.score.couverture == 100.0 and not recalcule.score.provisoire
    # Le rapport IA décrivait d'anciens constats : il n'est plus publié
    assert base.rapport_du_scan(recalcule.id) is None
    scan_a_jour = base.dernier_scan(a_jour)
    assert scan_a_jour is not None and base.rapport_du_scan(scan_a_jour.id) is not None

    # Idempotence
    assert recalculer_scores(base, referentiels).scans_modifies == 0


def test_recalcul_du_seul_dernier_scan_ou_de_tout_l_historique(
    base: Base, referentiels: Referentiels
) -> None:
    anciens = constats_scannes(anciens_referentiels(referentiels))
    org_id = _enregistrer(base, "exempleville", anciens)
    base.enregistrer_scan(org_id, _resultat("exempleville.fr", anciens, jour=8),
                          calculer_score(anciens), "1.2")  # fmt: skip
    assert recalculer_scores(base, referentiels, appliquer=False).scans_examines == 1
    assert recalculer_scores(base, referentiels, tous=True).scans_modifies == 2


# --------------------------------------------------------------------------- #
# 4. Couverture de l'observatoire
# --------------------------------------------------------------------------- #


def test_mesurer_couverture(referentiels: Referentiels) -> None:
    complet = calculer_score(constats_scannes(referentiels))
    sans_mx = [
        c
        for c in constats_scannes(anciens_referentiels(referentiels))
        if c.categorie != "messagerie"
    ]
    partiel = calculer_score(sans_mx)
    couverture = mesurer_couverture([complet, partiel])
    assert couverture.nombre_organisations == 2
    # Poids applicable : 100 + 75 (messagerie sans objet) ; inconnu : hébergement (25)
    assert couverture.poids_applicable == 175
    assert couverture.part_inconnue == round(100 * 25 / 175, 1)
    assert couverture.part_indisponible == 0
    assert couverture.nombre_provisoires == 1  # 25 / 75 non évalué : plus de 30 %
    assert couverture.par_categorie["hebergement"].inconnu == 1
    assert couverture.par_categorie["messagerie"].sans_objet == 1
    assert mesurer_couverture([]).part_inconnue == 0


def test_couverture_observatoire_hors_sur_demande(base: Base, referentiels: Referentiels) -> None:
    anciens = constats_scannes(anciens_referentiels(referentiels))
    _enregistrer(base, "exempleville", anciens)
    _enregistrer(base, "sur-demande", anciens, type="sur_demande", source="demande")
    base.enregistrer_scan(None, _resultat("unitaire.fr", anciens), calculer_score(anciens), "1.2")
    couverture = couverture_observatoire(base, referentiels)
    assert couverture.nombre_organisations == 1
    assert couverture.part_inconnue == 50.0  # hébergement (25) + messagerie (25)
    assert couverture.nombre_provisoires == 1


def test_cli_scores_et_inconnus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, referentiels: Referentiels
) -> None:
    chemin = tmp_path / "base.db"
    monkeypatch.setenv("CHEMIN_BASE_SQLITE", str(chemin))
    from bleublanccloud import configuration

    configuration.obtenir_parametres.cache_clear()
    with Base(chemin) as base:
        _enregistrer(base, "exempleville", constats_scannes(anciens_referentiels(referentiels)))
    lanceur = CliRunner()
    try:
        inconnus = lanceur.invoke(app, ["referentiels", "inconnus"])
        assert inconnus.exit_code == 0, inconnus.output
        assert "AS16347" in inconnus.output
        assert "transit" in inconnus.output and "AS174" in inconnus.output

        simulation = lanceur.invoke(app, ["scores", "recalculer", "--dry-run"])
        assert simulation.exit_code == 0, simulation.output
        assert "Simulation" in simulation.output and "Poids inconnu" in simulation.output

        couverture = lanceur.invoke(app, ["scores", "couverture"])
        assert couverture.exit_code == 0, couverture.output
        assert "50,0 %" in couverture.output

        assert lanceur.invoke(app, ["scores", "recalculer"]).exit_code == 0
        couverture = lanceur.invoke(app, ["scores", "couverture"])
        assert "0,0 %" in couverture.output
    finally:
        configuration.obtenir_parametres.cache_clear()
