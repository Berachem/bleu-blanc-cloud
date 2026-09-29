"""Tests de la méthodologie de score (version 1.2) et de ses cas limites."""

from __future__ import annotations

import pytest

from bleublanccloud.analyse.score import (
    POIDS,
    VERSION_METHODO,
    ScoreImpossible,
    arrondir,
    calculer_couverture,
    calculer_score,
    est_provisoire,
    note_depuis_score,
)
from bleublanccloud.modeles import Constat, Niveau


def c(
    categorie: str,
    niveau: Niveau,
    valeur: str = "x",
    cle: str = "c",
    regle: str | None = None,
) -> Constat:
    preuve = {"regle": regle} if regle else {}
    return Constat(
        sonde="test",
        categorie=categorie,  # type: ignore[arg-type]
        cle=cle,
        valeur=valeur,
        fournisseur_id=None if niveau == "inconnu" else "f",
        niveau=niveau,
        preuve=preuve,
    )


def socle_a() -> list[Constat]:
    """Organisation entièrement européenne."""
    return [
        c("hebergement", "A", "51.91.0.1"),
        c("messagerie", "A", "mx1.mail.ovh.net", "mx"),
        c("dns", "A", "dns10.ovh.net", "ns"),
    ]


def detail(score, categorie):  # type: ignore[no-untyped-def]
    return next(d for d in score.detail if d.categorie == categorie)


def test_tout_europeen_note_a() -> None:
    score = calculer_score(socle_a())
    assert (score.score_global, score.note, score.version_methodo) == (100, "A", VERSION_METHODO)
    assert score.categories_non_evaluables == []
    assert sum(d.poids_effectif for d in score.detail) == pytest.approx(100)


def test_exemple_complet() -> None:
    constats = [
        c("hebergement", "A"),
        c("messagerie", "D", "ville.mail.protection.outlook.com", "mx"),
        c("dns", "A"),
        c("suites_saas", "D", "Microsoft 365", regle="microsoft-365"),
        c("services_tiers", "D", "YouTube", regle="youtube"),
        c("services_tiers", "D", "Google Fonts", regle="google-fonts"),
        c("services_tiers", "D", "Ressources Google", regle="fournisseur:google"),
        c("services_tiers", "A", "tarteaucitron", regle="tarteaucitron"),
        c("mesure_audience", "D", "Google Analytics", regle="google-analytics"),
        c("informatif", "inconnu", "Aucune politique DMARC"),
    ]
    score = calculer_score(constats)
    # (25×100 + 25×0 + 10×100 + 15×75 + 15×40 + 10×0) / 100 = 52,25
    assert (score.score_global, score.note) == (52, "C")
    assert detail(score, "suites_saas").score == 75
    assert detail(score, "services_tiers").score == 40
    assert detail(score, "mesure_audience").score == 0
    assert detail(score, "messagerie").points_perdus_global == 25


def test_fournisseur_inconnu_exclu_et_poids_redistribue() -> None:
    constats = [c("hebergement", "inconnu"), *socle_a()[1:]]
    score = calculer_score(constats)
    hebergement = detail(score, "hebergement")
    assert hebergement.evaluable is False
    assert hebergement.poids_effectif == 0
    assert "hebergement" in score.categories_non_evaluables
    assert score.score_global == 100
    # Le poids de l'hébergement (25) est redistribué sur les 75 restants
    assert detail(score, "messagerie").poids_effectif == pytest.approx(25 / 75 * 100, abs=0.01)


def test_cdn_extra_europeen_niveau_c() -> None:
    constats = [c("hebergement", "C", "104.16.1.1", "cdn"), *socle_a()[1:]]
    score = calculer_score(constats)
    assert detail(score, "hebergement").score == 40
    # 25×40 + 75×100 = 8500 → 85 → A (seuil inclus)
    assert (score.score_global, score.note) == (85, "A")


def test_plusieurs_mx_le_moins_bon_est_retenu() -> None:
    constats = [
        c("hebergement", "A"),
        c("messagerie", "A", "mx1.mail.ovh.net", "mx"),
        c("messagerie", "D", "secours.pphosted.com", "mx"),
        c("messagerie", "inconnu", "mx.inconnu.fr", "mx"),
        c("dns", "A"),
    ]
    score = calculer_score(constats)
    messagerie = detail(score, "messagerie")
    assert messagerie.score == 0
    assert [j.constat_index for j in messagerie.justifications] == [2]
    assert messagerie.justifications[0].points_retires == 100
    assert "non identifié" in messagerie.explication


def test_plusieurs_mx_de_meme_niveau_partagent_la_perte() -> None:
    constats = [
        c("messagerie", "B", "mx1.infomaniak.ch", "mx"),
        c("messagerie", "B", "mx2.infomaniak.ch", "mx"),
    ]
    messagerie = detail(calculer_score(constats), "messagerie")
    assert messagerie.score == 70
    assert [j.points_retires for j in messagerie.justifications] == [15, 15]


def test_mx_tous_inconnus_exclus() -> None:
    constats = [*socle_a()[:1], c("messagerie", "inconnu", "mx.inconnu.fr", "mx"), socle_a()[2]]
    score = calculer_score(constats)
    assert detail(score, "messagerie").evaluable is False


def test_sans_messagerie_categorie_non_applicable() -> None:
    constats = [c("hebergement", "A"), c("dns", "D")]
    score = calculer_score(constats)
    assert "non applicable" in detail(score, "messagerie").explication
    # (25×100 + 10×0 + 15×100 + 15×100 + 10×100) / 75 = 86,67 → 87
    assert (score.score_global, score.note) == (87, "A")


def test_penalite_plancher_a_zero() -> None:
    constats = socle_a() + [
        c("suites_saas", "D", f"Service {i}", regle=f"service-{i}") for i in range(6)
    ]
    suites = detail(calculer_score(constats), "suites_saas")
    assert suites.score == 0
    assert sum(j.points_retires for j in suites.justifications) == 100


def test_un_service_compte_une_seule_fois() -> None:
    constats = [
        *socle_a(),
        c("services_tiers", "D", "YouTube", regle="youtube"),
        c("services_tiers", "D", "YouTube", regle="youtube"),
    ]
    assert detail(calculer_score(constats), "services_tiers").score == 80


def test_services_b_et_c_non_penalises() -> None:
    constats = [
        *socle_a(),
        c("services_tiers", "B", "OpenStreetMap", regle="openstreetmap"),
        c("suites_saas", "B", "Infomaniak", regle="infomaniak-ksuite"),
    ]
    score = calculer_score(constats)
    assert detail(score, "services_tiers").score == 100
    assert detail(score, "suites_saas").score == 100
    assert "aucun de niveau D" in detail(score, "services_tiers").explication


@pytest.mark.parametrize(
    ("niveaux", "attendu"),
    [([], 100), (["A"], 100), (["B"], 70), (["A", "D"], 0), (["C"], 40)],
)
def test_mesure_audience(niveaux: list[Niveau], attendu: float) -> None:
    constats = socle_a() + [c("mesure_audience", n, f"Outil {n}") for n in niveaux]
    assert detail(calculer_score(constats), "mesure_audience").score == attendu


def test_site_injoignable_categories_web_non_evaluables() -> None:
    score = calculer_score(socle_a(), sondes_reussies=["dns"])
    assert set(score.categories_non_evaluables) == {"services_tiers", "mesure_audience"}
    assert "site web" in detail(score, "services_tiers").explication


def test_aucune_categorie_evaluable() -> None:
    with pytest.raises(ScoreImpossible):
        calculer_score([], sondes_reussies=[])


def test_justifications_egales_aux_points_retires() -> None:
    constats = [
        c("hebergement", "D"),
        c("messagerie", "B", "a", "mx"),
        c("dns", "C"),
        c("suites_saas", "D", "S1", regle="s1"),
        c("services_tiers", "D", "T1", regle="t1"),
        c("mesure_audience", "D", "GA", regle="ga"),
    ]
    for categorie in calculer_score(constats).detail:
        assert categorie.score is not None
        total = sum(j.points_retires for j in categorie.justifications)
        assert total == pytest.approx(100 - categorie.score, abs=0.05), categorie.categorie


@pytest.mark.parametrize(
    ("score", "note"),
    [(100, "A"), (85, "A"), (84, "B"), (70, "B"), (69, "C"), (50, "C"), (49, "D"), (30, "D"),
     (29, "E"), (0, "E")],
)  # fmt: skip
def test_seuils_des_notes(score: int, note: str) -> None:
    assert note_depuis_score(score) == note


def test_arrondi_commercial() -> None:
    assert arrondir(52.5) == 53
    assert arrondir(52.49) == 52


def test_poids_totaux() -> None:
    assert sum(POIDS.values()) == 100


# --------------------------------------------------------------------------- #
# Couverture et note provisoire (v1.2)
# --------------------------------------------------------------------------- #


def test_version_1_2() -> None:
    assert VERSION_METHODO == "1.2"


def test_couverture_complete() -> None:
    score = calculer_score(socle_a())
    assert (score.couverture, score.provisoire) == (100.0, False)
    assert all(d.exclusion is None for d in score.detail)


def test_hebergement_inconnu_non_provisoire() -> None:
    # 25 % du poids inconnu : sous le seuil de 30 %
    constats = [c("hebergement", "inconnu"), *socle_a()[1:]]
    score = calculer_score(constats)
    assert detail(score, "hebergement").exclusion == "inconnu"
    assert (score.couverture, score.provisoire) == (75.0, False)


def test_hebergement_et_dns_inconnus_provisoire() -> None:
    # 25 + 10 = 35 % du poids inconnu : note provisoire
    constats = [c("hebergement", "inconnu"), c("messagerie", "A", cle="mx"), c("dns", "inconnu")]
    score = calculer_score(constats)
    assert (score.couverture, score.provisoire) == (65.0, True)
    assert score.note == "A"  # la note reste calculée, seulement marquée provisoire


def test_site_injoignable_provisoire() -> None:
    # Services tiers + mesure d'audience indisponibles (25 %) + DNS inconnu (10 %)
    constats = [c("hebergement", "A"), c("messagerie", "A", cle="mx"), c("dns", "inconnu")]
    score = calculer_score(constats, sondes_reussies=("dns",))
    assert detail(score, "services_tiers").exclusion == "indisponible"
    assert score.provisoire


def test_messagerie_sans_objet_hors_couverture() -> None:
    # Pas de MX : la catégorie est sans objet et sort du poids applicable (75)
    constats = [c("hebergement", "A"), c("dns", "A", cle="ns")]
    score = calculer_score(constats)
    assert detail(score, "messagerie").exclusion == "sans_objet"
    assert (score.couverture, score.provisoire) == (100.0, False)
    # Hébergement inconnu en plus : 25 / 75 = 33 % → provisoire
    score = calculer_score([c("hebergement", "inconnu"), c("dns", "A", cle="ns")])
    assert score.couverture == pytest.approx(66.7)
    assert score.provisoire


def test_seuil_strictement_superieur_a_30() -> None:
    assert not est_provisoire(70.0)
    assert est_provisoire(69.9)


def test_calculer_couverture_cas_limites() -> None:
    assert calculer_couverture({"hebergement": None, "messagerie": "sans_objet"}) == 100.0
    assert calculer_couverture({"messagerie": "sans_objet"}) == 0.0
    assert calculer_couverture({"hebergement": "indisponible", "dns": None}) == pytest.approx(28.6)


def test_ancien_score_sans_couverture_reste_lisible() -> None:
    from bleublanccloud.modeles import Score

    ancien = calculer_score(socle_a()).model_dump(exclude={"couverture", "provisoire"})
    for categorie in ancien["detail"]:
        del categorie["exclusion"]
    relu = Score.model_validate(ancien)
    assert (relu.couverture, relu.provisoire) == (100.0, False)
