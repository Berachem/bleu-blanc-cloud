"""Tests des adresses fonctionnelles de prospection (pages simulées avec respx, sans réseau)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import httpx
import pytest
import respx

from bleublanccloud.configuration import Parametres
from bleublanccloud.prospection_adresses import (
    adresses_de_la_page,
    chercher_adresse,
    choisir,
    completer_classeur,
    est_fonctionnelle,
)
from bleublanccloud.prospection_envoi import composer, type_envoi
from bleublanccloud.referentiels import Referentiels
from tests.test_http import TYPE_HTML, HorlogeFactice, fabriquer_client
from tests.test_prospection_envoi import JOUR, REGLAGES, a_contacter, classeur, destinataire


@pytest.mark.parametrize(
    ("adresse", "attendu"),
    [
        ("communication@ville.example", True),
        ("service.communication@ville.example", True),
        ("dsi-ville@ville.example", True),
        ("numerique@ville.example", True),
        ("webmaster@ville.example", True),
        ("presse@ville.example", True),
        ("com2@ville.example", True),
        ("direction.systemes.information@ville.example", False),  # aucun mot de service
        ("jean.dupont@ville.example", False),  # adresse de personne
        ("j.dupont-com@ville.example", False),  # nom de personne avant « com »
        ("mdupont@ville.example", False),
        ("contact@ville.example", False),  # générique : déjà dans l'annuaire
        ("mairie@ville.example", False),
        ("accueil@ville.example", False),
    ],
)
def test_est_fonctionnelle(adresse: str, attendu: bool) -> None:
    assert est_fonctionnelle(adresse) is attendu


def test_adresses_de_la_page() -> None:
    html = """<html><body>
      <a href="mailto:Communication@Ville.example?subject=Bonjour">Écrire</a>
      <p>Service numérique : numerique [at] ville.example</p>
      <p>Presse : presse (arobase) ville (point) example</p>
    </body></html>"""
    assert adresses_de_la_page(html) == {
        "communication@ville.example",
        "numerique@ville.example",
        "presse@ville.example",
    }


def test_choisir_le_meilleur_service_du_domaine_officiel() -> None:
    adresses = {
        "presse@ville.example",
        "dsi@ville.example",
        "communication@mairie.ville.example",  # sous-domaine du domaine officiel : accepté
        "communication@prestataire.example",  # autre domaine : écarté
        "jean.dupont@ville.example",  # personne : écartée
    }
    assert choisir(adresses, "ville.example") == "communication@mairie.ville.example"
    assert choisir({"dsi@ville.example", "presse@ville.example"}, "ville.example") == (
        "dsi@ville.example"
    )
    assert choisir({"jean.dupont@ville.example", "contact@ville.example"}, "ville.example") is None


@respx.mock
async def test_recherche_polie_sur_le_site_officiel(
    parametres: Parametres, referentiels: Referentiels
) -> None:
    respx.get("https://exempleville.fr/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nDisallow: /annuaire\n")
    )
    respx.get("https://exempleville.fr/").mock(
        return_value=httpx.Response(
            200,
            headers=TYPE_HTML,
            text="""<html><body>
              <a href="/nous-contacter">Contact</a>
              <a href="/annuaire">Annuaire des services</a>
              <a href="/mentions-legales">Mentions légales</a>
              <a href="mailto:jean.dupont@exempleville.fr">Le maire</a>
            </body></html>""",
        )
    )
    contact = respx.get("https://exempleville.fr/nous-contacter").mock(
        return_value=httpx.Response(
            200, headers=TYPE_HTML, text="<p>communication [at] exempleville.fr</p>"
        )
    )
    annuaire = respx.get("https://exempleville.fr/annuaire").mock(
        return_value=httpx.Response(200, headers=TYPE_HTML, text="<p>dsi@exempleville.fr</p>")
    )
    respx.get("https://exempleville.fr/mentions-legales").mock(
        return_value=httpx.Response(200, headers=TYPE_HTML, text="<p>presse@exempleville.fr</p>")
    )
    horloge = HorlogeFactice()
    client = fabriquer_client(parametres, referentiels, horloge)
    try:
        assert await chercher_adresse("exempleville.fr", client) == (
            "communication@exempleville.fr"
        )
    finally:
        await client.fermer()
    assert contact.called
    assert not annuaire.called  # interdit par robots.txt : jamais demandé
    # Une requête par seconde au plus sur le domaine
    assert all(attente <= parametres.intervalle_par_domaine_s for attente in horloge.attentes)
    assert horloge.attentes


@respx.mock
async def test_site_injoignable(parametres: Parametres, referentiels: Referentiels) -> None:
    respx.get(url__regex=r"https://(www\.)?injoignable\.example/.*").mock(
        side_effect=httpx.ConnectError("refusé")
    )
    client = fabriquer_client(parametres, referentiels, HorlogeFactice())
    try:
        assert await chercher_adresse("injoignable.example", client) is None
    finally:
        await client.fermer()


async def test_completer_le_classeur(tmp_path: Path) -> None:
    pytest.importorskip("openpyxl")
    chemin = classeur(
        tmp_path,
        {
            "nantes-44109": a_contacter("contact@nantes.example"),
            "albi-81004": a_contacter("mairie@albi.example"),
            "sete-34301": {
                **a_contacter("mairie@sete.example"),
                "Contact nominatif": "x@sete.example",
            },
            "lyon-69123": {**a_contacter("contact@lyon.example"), "Statut": "Envoyé"},
            "dijon-21231": {
                **a_contacter("contact@dijon.example"),
                "Adresse fonctionnelle": "aucune (01/11/2026)",
            },
        },
    )
    visites: list[str] = []

    async def chercher(domaine: str) -> str | None:
        visites.append(domaine)
        return "communication@nantes-44109.example" if domaine.startswith("nantes") else None

    cherchees, trouvees = await completer_classeur(chemin, chercher, jour=date(2026, 11, 24))
    # Lyon, contactée via l'accueil et pas encore relancée, est cherchée (relance redirigée) ;
    # Sète (contact nominatif) et Dijon (déjà cherchée) sont ignorées
    assert visites == ["nantes-44109.example", "albi-81004.example", "lyon-69123.example"]
    assert (cherchees, trouvees) == (3, 1)
    from bleublanccloud.prospection import lire_suivi

    suivi = lire_suivi(chemin)
    assert suivi["nantes-44109"]["Adresse fonctionnelle"] == "communication@nantes-44109.example"
    assert suivi["albi-81004"]["Adresse fonctionnelle"] == "aucune (24/11/2026)"
    # Nouvelle exécution : rien n'est revisité
    visites.clear()
    assert await completer_classeur(chemin, chercher) == (0, 0)
    assert visites == []


def test_envoi_vers_l_adresse_fonctionnelle() -> None:
    service = destinataire(adresse_fonctionnelle="communication@mairie-nantes.example")
    message = composer(service, "premier", REGLAGES)
    assert message["To"] == "communication@mairie-nantes.example"
    assert "un « oui » en réponse suffit" in message.get_content()
    # Le contact nominatif reste prioritaire ; « aucune (…) » n'est pas une adresse
    assert (
        destinataire(
            contact_nominatif="dsi@mairie-nantes.example",
            adresse_fonctionnelle="communication@mairie-nantes.example",
        ).adresse_envoi
        == "dsi@mairie-nantes.example"
    )
    assert destinataire(adresse_fonctionnelle="aucune (24/11/2026)").adresse_envoi == (
        "contact@mairie-nantes.example"
    )
    # Relance autorisée vers un service, comme vers une personne
    envoye = destinataire(
        statut="Envoyé",
        date_envoi=date(2026, 10, 27),
        adresse_fonctionnelle="communication@mairie-nantes.example",
        adresse_utilisee="communication@mairie-nantes.example",
    )
    assert type_envoi(envoye, JOUR, REGLAGES, relances=True) == "relance"
