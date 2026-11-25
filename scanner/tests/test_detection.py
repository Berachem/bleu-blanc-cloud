"""Tests de la détection des services tiers.

Chaque règle de regles_detection.yaml est testée à partir de ses propres exemples.
"""

from __future__ import annotations

import pytest

from bleublanccloud.analyse.attribution import Attributeur
from bleublanccloud.analyse.detection import (
    Detecteur,
    ElementsObserves,
    correspondances_regle,
)
from bleublanccloud.modeles import ExempleRegle, RegleDetection
from bleublanccloud.referentiels import Referentiels, referentiels_par_defaut
from bleublanccloud.sondes.dns import ChaineResolution, DonneesDns, EnregistrementMx
from bleublanccloud.sondes.http import DonneesHttp, Ressource, extraire_ressources
from tests.conftest import DOSSIER_FIXTURES

REGLES = referentiels_par_defaut().regles
CAS_EXEMPLES = [
    pytest.param(regle, exemple, id=f"{regle.id}-{indice}")
    for regle in REGLES
    for indice, exemple in enumerate(regle.exemples)
]


@pytest.fixture
def detecteur(referentiels: Referentiels) -> Detecteur:
    return Detecteur(referentiels.regles, Attributeur(referentiels.fournisseurs))


def test_nombre_de_regles() -> None:
    assert len(REGLES) >= 80


@pytest.mark.parametrize(("regle", "exemple"), CAS_EXEMPLES)
def test_chaque_regle_detecte_ses_exemples(regle: RegleDetection, exemple: ExempleRegle) -> None:
    elements = ElementsObserves.depuis_exemple(exemple)
    assert correspondances_regle(regle, elements), f"{regle.id} ne détecte pas {exemple.valeur}"


@pytest.mark.parametrize("regle", REGLES, ids=[r.id for r in REGLES])
def test_aucune_regle_sur_un_site_sobre(regle: RegleDetection) -> None:
    elements = ElementsObserves(
        txt=["v=spf1 -all"],
        spf="v=spf1 -all",
        mx=["mx1.exempleville.fr"],
        ressources=[
            Ressource(
                type="script",
                url="https://www.exempleville.fr/js/site.js",
                domaine="www.exempleville.fr",
                tierce=False,
            )
        ],
        cookies=["session"],
        en_tetes={"server": "nginx"},
        html=["<html><body><p>Bienvenue à Exempleville</p></body></html>"],
    )
    assert correspondances_regle(regle, elements) == []


def test_elements_depuis_exemple_en_tete() -> None:
    elements = ElementsObserves.depuis_exemple(
        ExempleRegle(type="en_tete", nom="X-Test", valeur="1")
    )
    assert elements.en_tetes == {"x-test": "1"}


def test_elements_depuis_exemple_cname() -> None:
    elements = ElementsObserves.depuis_exemple(ExempleRegle(type="cname", valeur="a.sendgrid.net"))
    assert elements.cnames == ["a.sendgrid.net"]


def test_detection_sur_la_page_d_accueil_fictive(detecteur: Detecteur) -> None:
    html = (DOSSIER_FIXTURES / "http" / "exempleville_accueil.html").read_text()
    ressources, _ = extraire_ressources(html, "https://www.exempleville.fr/", "exempleville.fr")
    http = DonneesHttp(
        url_depart="https://www.exempleville.fr/",
        ressources=ressources,
        cookies=["PHPSESSID", "_ga"],
        html_pages=[html],
    )
    elements = ElementsObserves.depuis_sondes(None, http)
    resultat = detecteur.detecter(elements)
    regles = {c.preuve["regle"] for c in resultat.constats}
    assert {
        "google-fonts",
        "adobe-fonts",
        "tarteaucitron",
        "google-tag-manager",
        "google-analytics",
        "youtube",
        "openstreetmap",
        "matomo-auto-heberge",
    } <= regles
    assert "tarteaucitron-io" not in regles
    par_regle = {c.preuve["regle"]: c for c in resultat.constats}
    assert par_regle["matomo-auto-heberge"].niveau == "A"
    assert par_regle["matomo-auto-heberge"].preuve["signal_positif"] is True
    assert par_regle["openstreetmap"].niveau == "B"
    assert par_regle["youtube"].niveau == "D"
    assert par_regle["google-analytics"].cle == "cookie"

    generiques, inconnus = detecteur.ressources_non_couvertes(elements, resultat.elements_expliques)
    assert {c.fournisseur_id for c in generiques} == {"google", "aws"}
    google = next(c for c in generiques if c.fournisseur_id == "google")
    assert google.preuve["domaines"] == ["lh3.googleusercontent.com"]
    assert inconnus == ["cdn.exemple-agence.fr"]


def test_une_seule_detection_par_regle(detecteur: Detecteur) -> None:
    elements = ElementsObserves(
        ressources=[
            Ressource(
                type="iframe",
                url=f"https://www.youtube.com/embed/{i}",
                domaine="www.youtube.com",
                tierce=True,
            )
            for i in range(10)
        ]
    )
    constats = detecteur.detecter(elements).constats
    assert len(constats) == 1
    assert constats[0].preuve["nombre_correspondances"] == 10
    assert len(constats[0].preuve["correspondances"]) == 5


def test_matomo_cloud_annule_matomo_auto_heberge(detecteur: Detecteur) -> None:
    elements = ElementsObserves(
        ressources=[
            Ressource(
                type="script",
                url="https://cdn.matomo.cloud/exempleville.matomo.cloud/matomo.js",
                domaine="cdn.matomo.cloud",
                tierce=True,
            )
        ],
        html=["_paq.push(['trackPageView']);"],
    )
    regles = {c.preuve["regle"] for c in detecteur.detecter(elements).constats}
    assert regles == {"matomo-cloud"}


def test_detection_dns_microsoft_365(detecteur: Detecteur) -> None:
    dns = DonneesDns(
        domaine="exempleville.fr",
        txt=["MS=ms123", "v=spf1 include:spf.protection.outlook.com -all"],
        mx=[EnregistrementMx(priorite=0, hote="exempleville-fr.mail.protection.outlook.com")],
        resolutions={
            "exempleville.fr": ChaineResolution(nom="exempleville.fr", cnames=["x.sendgrid.net"])
        },
    )
    constats = detecteur.detecter(ElementsObserves.depuis_sondes(dns, None)).constats
    par_regle = {c.preuve["regle"]: c for c in constats}
    assert par_regle["microsoft-365"].sonde == "dns"
    assert par_regle["microsoft-365"].categorie == "suites_saas"
    assert par_regle["microsoft-365"].preuve["nombre_correspondances"] == 3
    assert par_regle["sendgrid"].cle == "cname_service"


def test_ressources_de_l_hebergeur_ignorees(detecteur: Detecteur) -> None:
    elements = ElementsObserves(
        ressources=[
            Ressource(
                type="image",
                url="https://static.wixstatic.com/media/logo.png",
                domaine="static.wixstatic.com",
                tierce=True,
            )
        ]
    )
    generiques, inconnus = detecteur.ressources_non_couvertes(elements, frozenset(), {"wix"})
    assert generiques == [] and inconnus == []
    generiques, _ = detecteur.ressources_non_couvertes(elements, frozenset())
    assert [c.fournisseur_id for c in generiques] == ["wix"]


# --------------------------------------------------------------------------- #
# Assistants IA : informatifs, sans effet sur le score
# --------------------------------------------------------------------------- #


def _script_tiers(url: str) -> Ressource:
    from urllib.parse import urlsplit

    return Ressource(type="script", url=url, domaine=urlsplit(url).hostname or "", tierce=True)


SITE_AVEC_ASSISTANTS = ElementsObserves(
    ressources=[
        _script_tiers(
            "https://www.gstatic.com/dialogflow-console/fast/df-messenger/prod/v1/df-messenger.js"
        ),
        _script_tiers("https://cdn.botframework.com/botframework-webchat/latest/webchat.js"),
        _script_tiers("https://www.chatbase.co/embed.min.js"),
        _script_tiers("https://cdn.botpress.cloud/webchat/v3.3/inject.js"),
        _script_tiers("https://cdn.voiceflow.com/widget/bundle.mjs"),
        _script_tiers("https://www.googletagmanager.com/gtag/js?id=G-TEST"),
    ],
    html=['<df-messenger agent-id="test"></df-messenger>'],
)


def test_regles_sans_effet_sur_le_score_toujours_informatives() -> None:
    for regle in REGLES:
        if not regle.explique_ressources:
            assert regle.categorie == "informatif", regle.id
        if regle.type_service == "assistant_ia":
            assert not regle.explique_ressources, regle.id


def test_assistants_ia_ne_changent_ni_les_constats_notes_ni_le_score(
    referentiels: Referentiels,
) -> None:
    from bleublanccloud.analyse.score import calculer_score

    attributeur = Attributeur(referentiels.fournisseurs)
    resultats = []
    for regles in (
        referentiels.regles,
        [r for r in referentiels.regles if r.type_service != "assistant_ia"],
    ):
        detecteur = Detecteur(regles, attributeur)
        detection = detecteur.detecter(SITE_AVEC_ASSISTANTS)
        generiques, inconnus = detecteur.ressources_non_couvertes(
            SITE_AVEC_ASSISTANTS, detection.elements_expliques
        )
        resultats.append(([*detection.constats, *generiques], inconnus))
    (avec, inconnus_avec), (sans, inconnus_sans) = resultats

    def notes(constats: list) -> list:  # type: ignore[type-arg]
        return sorted(
            (c.categorie, c.cle, c.valeur, c.niveau, c.fournisseur_id)
            for c in constats
            if c.categorie != "informatif"
        )

    assert notes(avec) == notes(sans)
    assert inconnus_avec == inconnus_sans

    # Même score, même note, mêmes catégories et mêmes justifications. Seule la position
    # du constat justificatif dans la liste change (les constats informatifs s'y ajoutent).
    def sans_position(constats: list) -> dict:  # type: ignore[type-arg]
        score = calculer_score(constats).model_dump()
        for categorie in score["detail"]:
            for justification in categorie["justifications"]:
                justification["constat"] = constats[justification.pop("constat_index")].valeur
        return score

    assert sans_position(avec) == sans_position(sans)
    assistants = [c for c in avec if c.preuve.get("type_service") == "assistant_ia"]
    assert {c.preuve["regle"] for c in assistants} == {
        "ia-dialogflow-messenger",
        "ia-bot-framework-webchat",
        "ia-chatbase",
        "ia-botpress",
        "ia-voiceflow",
    }
    assert all(c.categorie == "informatif" for c in assistants)
