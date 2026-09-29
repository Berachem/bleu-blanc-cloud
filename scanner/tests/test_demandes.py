"""Analyses sur demande : validation, lecture des tickets, API Codeberg simulée, traitement."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from pydantic import SecretStr
from typer.testing import CliRunner

from bleublanccloud.analyse.score import VERSION_METHODO, calculer_score
from bleublanccloud.cli import app
from bleublanccloud.configuration import Parametres
from bleublanccloud.demandes.execution import adresses_du_site
from bleublanccloud.demandes.forge import ClientForge, ErreurForge
from bleublanccloud.demandes.tickets import Ticket, case_cochee, extraire_domaine
from bleublanccloud.demandes.traitement import TraiteurDemandes
from bleublanccloud.demandes.validation import DomaineRefuse, nom_lisible, valider_domaine
from bleublanccloud.modeles import Organisation, RapportIA, ResultatScan, Retrait
from bleublanccloud.referentiels import Referentiels
from bleublanccloud.scan import scanner_domaine
from bleublanccloud.sondes.dns import ErreurDns
from bleublanccloud.sondes.ip import ResolveurAsn
from bleublanccloud.stockage.base import Base
from bleublanccloud.verrou import verrou_exclusif
from tests.conftest import ResolveurFactice, fabriquer_contexte

API = "https://codeberg.test/api/v1"
DEPOT = "berachem/bleublanccloud-pages"
JETON = "jeton-secret-de-test-123"
URL_SITE = "https://bleublanccloud.berachem.dev"
ETIQUETTES = {"analyse": 1, "traitée": 2, "refusée": 3, "erreur": 4}


def corps_formulaire(domaine: str, cochee: bool = True) -> str:
    """Corps produit par le modèle Forgejo (champs rendus en Markdown)."""
    return (
        f"### Domaine à analyser\n\n{domaine}\n\n### Engagement\n\n"
        f"- [{'x' if cochee else ' '}] Je suis responsable de ce site, ou il s'agit du site "
        "d'un organisme public\n"
    )


# --------------------------------------------------------------------------- #
# Validation du domaine
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("saisie", "attendu"),
    [
        ("exemple.fr", "exemple.fr"),
        ("  Exemple.FR  ", "exemple.fr"),
        ("https://www.ville-exemple.fr/", "www.ville-exemple.fr"),
        ("http://ville-exemple.fr", "ville-exemple.fr"),
        ("exemple.fr.", "exemple.fr"),
        ("Mairie-Évry.fr", "xn--mairie-vry-h7a.fr"),
        ("xn--mairie-vry-h7a.fr", "xn--mairie-vry-h7a.fr"),
        ("example.org", "example.org"),
    ],
)
def test_domaine_valide(saisie: str, attendu: str) -> None:
    assert valider_domaine(saisie) == attendu


@pytest.mark.parametrize(
    ("saisie", "code"),
    [
        (None, "domaine_absent"),
        ("   ", "domaine_absent"),
        ("exemple.fr/contact", "domaine_chemin"),
        ("https://exemple.fr/page?x=1", "domaine_chemin"),
        ("exemple.fr#ancre", "domaine_chemin"),
        ("exemple.fr:8080", "domaine_port"),
        ("127.0.0.1", "domaine_ip"),
        ("http://10.0.0.1/", "domaine_ip"),
        ("[::1]", "domaine_ip"),
        ("2001:db8::1", "domaine_ip"),
        ("localhost", "domaine_reserve"),
        ("intranet.local", "domaine_reserve"),
        ("serveur.internal", "domaine_reserve"),
        ("box.home.arpa", "domaine_reserve"),
        ("site.test", "domaine_reserve"),
        ("exemple", "domaine_invalide"),
        ("127.1", "domaine_invalide"),
        ("0x7f000001", "domaine_invalide"),
        ("sous_domaine.exemple.fr", "domaine_invalide"),
        ("-exemple.fr", "domaine_invalide"),
        ("exemple .fr", "domaine_invalide"),
        ("admin@exemple.fr", "domaine_invalide"),
        ("exemple.fr; rm -rf /", "domaine_invalide"),
        ("$(reboot).fr", "domaine_invalide"),
        ("a" * 64 + ".fr", "domaine_invalide"),
        ("x" * 400, "domaine_invalide"),
    ],
)
def test_domaine_refuse(saisie: str | None, code: str) -> None:
    with pytest.raises(DomaineRefuse) as refus:
        valider_domaine(saisie)
    assert refus.value.code == code


def test_nom_lisible() -> None:
    assert nom_lisible("xn--mairie-vry-h7a.fr") == "mairie-évry.fr"


# --------------------------------------------------------------------------- #
# Lecture des tickets
# --------------------------------------------------------------------------- #


def ticket(numero: int = 1, titre: str = "[Analyse] ", corps: str = "", **champs: Any) -> Ticket:
    return Ticket(numero=numero, titre=titre, corps=corps, auteur=champs.get("auteur", "alice"),
                  etiquettes=frozenset(champs.get("etiquettes", {"analyse"})))  # fmt: skip


def test_lecture_formulaire() -> None:
    t = ticket(corps=corps_formulaire("ville-exemple.fr"))
    assert extraire_domaine(t) == "ville-exemple.fr"
    assert case_cochee(t)
    assert not case_cochee(ticket(corps=corps_formulaire("ville-exemple.fr", cochee=False)))


def test_lecture_url_pre_remplie() -> None:
    corps = (
        "Domaine à analyser : `ville-exemple.fr`\n\n"
        "- [x] Je suis responsable de ce site, ou il s'agit du site d'un organisme public\n"
    )
    t = ticket(corps=corps, etiquettes=set())
    assert t.est_demande  # titre « [Analyse] » sans étiquette
    assert (extraire_domaine(t), case_cochee(t)) == ("ville-exemple.fr", True)


def test_lecture_titre_en_dernier_recours() -> None:
    t = ticket(titre="[Analyse] ville-exemple.fr", corps="Domaine à analyser : \n")
    assert extraire_domaine(t) == "ville-exemple.fr"


def test_champ_sans_reponse() -> None:
    corps = "### Domaine à analyser\n\n_No response_\n\n### Engagement\n"
    assert extraire_domaine(ticket(titre="[Analyse]", corps=corps)) is None


def test_ticket_ordinaire_ignore() -> None:
    assert not ticket(titre="Question sur le site", etiquettes=set()).est_demande


def test_corps_borne() -> None:
    corps = "x" * 30_000 + "\nDomaine à analyser : cache.exemple.fr"
    assert extraire_domaine(ticket(titre="[Analyse]", corps=corps)) is None


# --------------------------------------------------------------------------- #
# API Codeberg (Forgejo) simulée
# --------------------------------------------------------------------------- #


class ForgeSimulee:
    """Dépôt Forgejo en mémoire, servi par respx sur les routes de l'API utilisées."""

    def __init__(self, routeur: respx.MockRouter) -> None:
        self.tickets: dict[int, dict[str, Any]] = {}
        self.commentaires: dict[int, list[str]] = {}
        self.panne = False
        self.panne_commentaires = False
        self.entetes_auth: set[str] = set()
        base = re.escape(f"{API}/repos/{DEPOT}")
        routeur.get(url__regex=rf"^{base}/issues(\?.*)?$").mock(side_effect=self._lister)
        routeur.get(url__regex=rf"^{base}/labels(\?.*)?$").mock(side_effect=self._etiquettes)
        routeur.post(url__regex=rf"^{base}/issues/(?P<n>\d+)/comments$").mock(
            side_effect=self._commenter
        )
        routeur.post(url__regex=rf"^{base}/issues/(?P<n>\d+)/labels$").mock(
            side_effect=self._etiqueter
        )
        routeur.delete(url__regex=rf"^{base}/issues/(?P<n>\d+)/labels/(?P<e>\d+)$").mock(
            side_effect=self._desetiqueter
        )
        routeur.patch(url__regex=rf"^{base}/issues/(?P<n>\d+)$").mock(side_effect=self._modifier)

    def ouvrir(self, numero: int, corps: str, auteur: str = "alice", titre: str = "[Analyse] ",
               etiquettes: tuple[str, ...] = ("analyse",)) -> None:  # fmt: skip
        self.tickets[numero] = {
            "number": numero, "title": titre, "body": corps, "state": "open",
            "user": {"login": auteur}, "labels": list(etiquettes), "pull_request": None,
        }  # fmt: skip
        self.commentaires[numero] = []

    def etat(self, numero: int) -> tuple[str, set[str]]:
        return self.tickets[numero]["state"], set(self.tickets[numero]["labels"])

    def _verifier(self, requete: httpx.Request) -> None:
        self.entetes_auth.add(requete.headers.get("Authorization", ""))
        if self.panne:
            raise httpx.ConnectError("Codeberg injoignable", request=requete)

    def _lister(self, requete: httpx.Request) -> httpx.Response:
        self._verifier(requete)
        page = int(requete.url.params.get("page", "1"))
        ouverts = [
            {**t, "labels": [{"id": ETIQUETTES.get(n, 99), "name": n} for n in t["labels"]]}
            for t in self.tickets.values()
            if t["state"] == "open"
        ]
        return httpx.Response(200, json=ouverts if page == 1 else [])

    def _etiquettes(self, requete: httpx.Request) -> httpx.Response:
        self._verifier(requete)
        return httpx.Response(200, json=[{"id": i, "name": n} for n, i in ETIQUETTES.items()])

    def _commenter(self, requete: httpx.Request, n: str) -> httpx.Response:
        self._verifier(requete)
        if self.panne_commentaires:
            return httpx.Response(500)
        self.commentaires[int(n)].append(json.loads(requete.content)["body"])
        return httpx.Response(201, json={"id": 1})

    def _etiqueter(self, requete: httpx.Request, n: str) -> httpx.Response:
        self._verifier(requete)
        noms = {i: nom for nom, i in ETIQUETTES.items()}
        for identifiant in json.loads(requete.content)["labels"]:
            if noms[identifiant] not in self.tickets[int(n)]["labels"]:
                self.tickets[int(n)]["labels"].append(noms[identifiant])
        return httpx.Response(200, json=[])

    def _desetiqueter(self, requete: httpx.Request, n: str, e: str) -> httpx.Response:
        self._verifier(requete)
        noms = {i: nom for nom, i in ETIQUETTES.items()}
        etiquettes = self.tickets[int(n)]["labels"]
        if noms[int(e)] in etiquettes:
            etiquettes.remove(noms[int(e)])
        return httpx.Response(204)

    def _modifier(self, requete: httpx.Request, n: str) -> httpx.Response:
        self._verifier(requete)
        self.tickets[int(n)]["state"] = json.loads(requete.content)["state"]
        return httpx.Response(201, json={})


@pytest.fixture
def forge_simulee() -> Iterator[ForgeSimulee]:
    with respx.mock(assert_all_called=False) as routeur:
        yield ForgeSimulee(routeur)


@pytest.fixture
def base() -> Iterator[Base]:
    with Base(":memory:") as b:
        yield b


class Banc:
    """Traitement réel branché sur la forge simulée, un résolveur DNS factice et des faux
    services (publication, rapport IA) qui comptent leurs appels."""

    def __init__(
        self,
        base: Base,
        referentiels: Referentiels,
        parametres: Parametres,
        resolveur_asn: ResolveurAsn,
        scenario: dict[str, Any] | None = None,
    ) -> None:
        self.base = base
        self.referentiels = referentiels
        self.resolveur = ResolveurFactice(scenario or {}).fusionner(
            ResolveurFactice.depuis_fixture("exempleville.fr")
        )
        self.contexte = fabriquer_contexte(parametres, referentiels, self.resolveur, resolveur_asn)
        self.analyses: list[str] = []
        self.publications = 0
        self.publication_reussie = True
        self.panne_scan: Exception | None = None
        self.rapports: list[int] = []

    async def analyser(self, hote: str) -> ResultatScan:
        self.analyses.append(hote)
        if self.panne_scan is not None:
            raise self.panne_scan
        return await scanner_domaine(hote, self.contexte)

    async def resoudre(self, hote: str) -> list[str]:
        return await adresses_du_site(hote, self.resolveur)

    async def publier(self) -> bool:
        self.publications += 1
        return self.publication_reussie

    async def generer_rapport(self, scan_id: int) -> None:
        self.rapports.append(scan_id)
        rapport = RapportIA(resume_decideur="Résumé.", points_forts=[], risques=[],
                            plan_migration=[])  # fmt: skip
        self.base.enregistrer_rapport(scan_id, "empreinte", "modele-test", "1.0", rapport)

    def traiteur(self, **options: Any) -> TraiteurDemandes:
        forge = ClientForge(DEPOT, SecretStr(JETON), url_api=API)
        return TraiteurDemandes(
            base=self.base,
            referentiels=options.pop("referentiels", self.referentiels),
            forge=forge,
            analyser=self.analyser,
            resoudre=self.resoudre,
            publier=self.publier,
            url_site=URL_SITE,
            generer_rapport=self.generer_rapport,
            **options,
        )


@pytest.fixture
def banc(
    base: Base, referentiels: Referentiels, parametres: Parametres, resolveur_asn: ResolveurAsn
) -> Banc:
    return Banc(base, referentiels, parametres, resolveur_asn)


# --------------------------------------------------------------------------- #
# Scénarios
# --------------------------------------------------------------------------- #


async def test_demande_valide(forge_simulee: ForgeSimulee, banc: Banc) -> None:
    forge_simulee.ouvrir(1, corps_formulaire("exempleville.fr"))
    bilan = await banc.traiteur().traiter()

    assert bilan.traitees == [1] and banc.analyses == ["exempleville.fr"]
    assert banc.publications == 1 and len(banc.rapports) == 1
    assert forge_simulee.etat(1) == ("closed", {"analyse", "traitée"})
    [reponse] = forge_simulee.commentaires[1]
    enregistree = banc.base.organisation_par_slug("sur-demande-exempleville-fr")
    assert enregistree is not None and enregistree.organisation.type == "sur_demande"
    scan = banc.base.dernier_scan(enregistree.id)
    assert scan is not None and scan.score is not None
    assert f"**Note : {scan.score.note}**" in reponse
    assert f"**Score : {scan.score.score_global}/100**" in reponse
    assert f"{URL_SITE}/organisation/sur-demande-exempleville-fr/" in reponse
    assert "externe et visible publiquement" in reponse
    assert "Rapport rédigé par une IA (Mistral)" in reponse
    suivi = banc.base.demande(DEPOT, 1)
    assert suivi is not None and suivi.statut == "traitee" and suivi.cloturee_le is not None
    # Un second passage ne refait rien (ticket fermé)
    bilan = await banc.traiteur().traiter()
    assert bilan.lues == 0 and banc.publications == 1


async def test_jeton_transmis_mais_jamais_journalise(
    forge_simulee: ForgeSimulee, banc: Banc, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    forge_simulee.ouvrir(1, corps_formulaire("exempleville.fr"))
    forge_simulee.panne_commentaires = True
    await banc.traiteur().traiter()
    assert forge_simulee.entetes_auth == {f"token {JETON}"}
    assert JETON not in caplog.text
    assert "HTTP 500" in caplog.text  # l'erreur est bien journalisée, sans le jeton


@pytest.mark.parametrize(
    ("corps", "code"),
    [
        (corps_formulaire("exempleville.fr/contact"), "domaine_chemin"),
        (corps_formulaire("192.168.1.1"), "domaine_ip"),
        (corps_formulaire("nas.local"), "domaine_reserve"),
        (corps_formulaire("exempleville.fr", cochee=False), "case_non_cochee"),
        ("Bonjour, pouvez-vous analyser mon site ?", "case_non_cochee"),
    ],
)
async def test_demande_refusee(
    forge_simulee: ForgeSimulee, banc: Banc, corps: str, code: str
) -> None:
    forge_simulee.ouvrir(1, corps)
    bilan = await banc.traiteur().traiter()
    assert bilan.refusees == [(1, code)]
    assert banc.analyses == [] and banc.publications == 0
    assert forge_simulee.etat(1) == ("closed", {"analyse", "refusée"})
    [reponse] = forge_simulee.commentaires[1]
    assert "ne peut malheureusement pas être traitée" in reponse
    assert "nouvelle demande" in reponse


async def test_contenu_du_ticket_jamais_recopie(forge_simulee: ForgeSimulee, banc: Banc) -> None:
    forge_simulee.ouvrir(1, corps_formulaire("<script>alert(1)</script>.fr"))
    await banc.traiteur().traiter()
    [reponse] = forge_simulee.commentaires[1]
    assert "script" not in reponse


async def test_reseau_prive_refuse(
    forge_simulee: ForgeSimulee,
    base: Base,
    referentiels: Referentiels,
    parametres: Parametres,
    resolveur_asn: ResolveurAsn,
) -> None:
    scenario = {"resolutions": {"piege-exemple.fr": {"ipv4": ["51.91.10.20", "192.168.1.10"]}}}
    banc = Banc(base, referentiels, parametres, resolveur_asn, scenario)
    forge_simulee.ouvrir(1, corps_formulaire("piege-exemple.fr"))
    bilan = await banc.traiteur().traiter()
    assert bilan.refusees == [(1, "reseau_prive")] and banc.analyses == []


async def test_domaine_sans_adresse_refuse(forge_simulee: ForgeSimulee, banc: Banc) -> None:
    forge_simulee.ouvrir(1, corps_formulaire("inexistant-exemple.fr"))
    bilan = await banc.traiteur().traiter()
    assert bilan.refusees == [(1, "sans_adresse")]


async def test_retrait_respecte(
    forge_simulee: ForgeSimulee, banc: Banc, referentiels: Referentiels
) -> None:
    import dataclasses

    avec_retrait = dataclasses.replace(
        referentiels,
        retraits={"exempleville.fr": Retrait(domaine="exempleville.fr", date_demande="2026-01-01")},
    )
    forge_simulee.ouvrir(1, corps_formulaire("www.exempleville.fr"))
    bilan = await banc.traiteur(referentiels=avec_retrait).traiter()
    assert bilan.refusees == [(1, "retrait")]
    assert banc.analyses == [] and banc.resolveur.appels == []  # aucune requête DNS
    assert "droit de retrait" in forge_simulee.commentaires[1][0]


async def test_limite_par_compte(forge_simulee: ForgeSimulee, banc: Banc) -> None:
    forge_simulee.ouvrir(1, corps_formulaire("exempleville.fr"), auteur="alice")
    forge_simulee.ouvrir(2, corps_formulaire("www.exempleville.fr"), auteur="Alice")
    bilan = await banc.traiteur().traiter()
    assert bilan.traitees == [1] and bilan.refusees == [(2, "limite_compte")]
    assert "une seule analyse par jour" in forge_simulee.commentaires[2][0].lower()


async def test_limite_quotidienne(forge_simulee: ForgeSimulee, banc: Banc) -> None:
    for numero, auteur in ((1, "alice"), (2, "bob"), (3, "chloe")):
        forge_simulee.ouvrir(numero, corps_formulaire("exempleville.fr"), auteur=auteur)
    bilan = await banc.traiteur(limite_jour=2).traiter()
    assert bilan.traitees == [1, 2]
    assert bilan.refusees == [(3, "limite_quotidienne")]
    assert "limite de 2 analyses par jour" in forge_simulee.commentaires[3][0]
    assert banc.analyses == ["exempleville.fr"]  # la 2e demande réutilise la 1re analyse


async def test_limite_remise_a_zero_le_lendemain(forge_simulee: ForgeSimulee, banc: Banc) -> None:
    forge_simulee.ouvrir(1, corps_formulaire("exempleville.fr"))
    await banc.traiteur().traiter()
    forge_simulee.ouvrir(2, corps_formulaire("exempleville.fr"))
    demain = datetime.now(UTC) + timedelta(days=1)
    bilan = await banc.traiteur(maintenant=lambda: demain).traiter()
    assert bilan.traitees == [2]


async def test_doublon_recent_reutilise_la_fiche(forge_simulee: ForgeSimulee, banc: Banc) -> None:
    # Fiche de l'observatoire analysée il y a 2 jours pour le même domaine
    commune = Organisation(slug="exempleville-99999", nom="Commune d'Exempleville",
                           type="commune", site_web="https://www.exempleville.fr/",
                           source="test")  # fmt: skip
    org_id = banc.base.enregistrer_organisation(commune)
    resultat = await scanner_domaine("exempleville.fr", banc.contexte)
    resultat = resultat.model_copy(update={"debut": datetime.now(UTC) - timedelta(days=2)})
    banc.base.enregistrer_scan(
        org_id, resultat, calculer_score(resultat.constats, ["dns"]), VERSION_METHODO
    )

    forge_simulee.ouvrir(1, corps_formulaire("exempleville.fr"))
    bilan = await banc.traiteur().traiter()
    assert bilan.traitees == [1] and banc.analyses == [] and banc.rapports == []
    [reponse] = forge_simulee.commentaires[1]
    assert "déjà été analysé il y a moins de 7 jours" in reponse
    assert f"{URL_SITE}/organisation/exempleville-99999/" in reponse
    assert banc.base.organisation_par_slug("sur-demande-exempleville-fr") is None


async def test_analyse_ancienne_relancee_sur_la_fiche_existante(
    forge_simulee: ForgeSimulee, banc: Banc
) -> None:
    commune = Organisation(slug="exempleville-99999", nom="Commune d'Exempleville",
                           type="commune", site_web="https://exempleville.fr/",
                           source="test")  # fmt: skip
    org_id = banc.base.enregistrer_organisation(commune)
    resultat = await scanner_domaine("exempleville.fr", banc.contexte)
    resultat = resultat.model_copy(update={"debut": datetime.now(UTC) - timedelta(days=10)})
    banc.base.enregistrer_scan(org_id, resultat, calculer_score(resultat.constats, ["dns"]), "1.2")

    forge_simulee.ouvrir(1, corps_formulaire("exempleville.fr"))
    await banc.traiteur().traiter()
    assert banc.analyses == ["exempleville.fr"]
    # Nouveau scan rattaché à la fiche de la commune (pas de fiche en double)
    enregistree = banc.base.organisation_par_slug("exempleville-99999")
    assert enregistree is not None and enregistree.organisation.type == "commune"
    assert banc.base.organisation_par_slug("sur-demande-exempleville-fr") is None


async def test_erreur_reseau_codeberg(forge_simulee: ForgeSimulee, banc: Banc) -> None:
    forge_simulee.ouvrir(1, corps_formulaire("exempleville.fr"))
    forge_simulee.panne = True
    with pytest.raises(ErreurForge) as erreur:
        await banc.traiteur().traiter()
    assert JETON not in str(erreur.value)
    assert banc.base.demande(DEPOT, 1) is None and banc.analyses == []


async def test_erreur_technique_retentee_trois_fois(
    forge_simulee: ForgeSimulee, banc: Banc
) -> None:
    forge_simulee.ouvrir(1, corps_formulaire("exempleville.fr"))
    banc.panne_scan = ErreurDns("A exempleville.fr : délai dépassé")

    for tentative in (1, 2):
        bilan = await banc.traiteur().traiter()
        assert [numero for numero, _ in bilan.erreurs] == [1]
        assert forge_simulee.etat(1) == ("open", {"analyse", "erreur"})
        suivi = banc.base.demande(DEPOT, 1)
        assert suivi is not None and (suivi.statut, suivi.tentatives) == ("erreur", tentative)
    assert len(forge_simulee.commentaires[1]) == 1  # un seul message d'attente
    assert "nouvel essai aura lieu automatiquement" in forge_simulee.commentaires[1][0]

    await banc.traiteur().traiter()
    assert forge_simulee.etat(1) == ("closed", {"analyse", "erreur"})
    assert "après 3 tentatives" in forge_simulee.commentaires[1][-1]
    assert banc.analyses == ["exempleville.fr"] * 3 and banc.publications == 0
    # La demande acceptée n'est comptée qu'une fois dans les limites
    assert len(banc.base.demandes_acceptees_depuis(datetime.now(UTC) - timedelta(days=1))) == 1


async def test_erreur_puis_succes(forge_simulee: ForgeSimulee, banc: Banc) -> None:
    forge_simulee.ouvrir(1, corps_formulaire("exempleville.fr"))
    banc.panne_scan = httpx.ConnectError("réseau coupé")
    await banc.traiteur().traiter()
    banc.panne_scan = None
    bilan = await banc.traiteur().traiter()
    assert bilan.traitees == [1]
    assert forge_simulee.etat(1) == ("closed", {"analyse", "traitée"})  # « erreur » retirée


async def test_publication_en_echec(forge_simulee: ForgeSimulee, banc: Banc) -> None:
    forge_simulee.ouvrir(1, corps_formulaire("exempleville.fr"))
    banc.publication_reussie = False
    bilan = await banc.traiteur().traiter()
    assert bilan.publication is False and bilan.erreurs == [(1, "publication du site impossible")]
    banc.publication_reussie = True
    bilan = await banc.traiteur().traiter()
    assert bilan.traitees == [1] and banc.analyses == ["exempleville.fr"]  # pas de 2e scan


async def test_reponse_reportee_sans_nouvelle_analyse(
    forge_simulee: ForgeSimulee, banc: Banc
) -> None:
    forge_simulee.ouvrir(1, corps_formulaire("exempleville.fr"))
    forge_simulee.panne_commentaires = True
    bilan = await banc.traiteur().traiter()
    assert bilan.reponses_en_attente == [1] and forge_simulee.etat(1)[0] == "open"
    forge_simulee.panne_commentaires = False
    await banc.traiteur().traiter()
    assert forge_simulee.etat(1) == ("closed", {"analyse", "traitée"})
    assert len(forge_simulee.commentaires[1]) == 1
    assert banc.analyses == ["exempleville.fr"] and banc.publications == 1


async def test_ticket_rouvert_ignore(forge_simulee: ForgeSimulee, banc: Banc) -> None:
    forge_simulee.ouvrir(1, corps_formulaire("exempleville.fr/x"))
    await banc.traiteur().traiter()
    forge_simulee.tickets[1]["state"] = "open"  # rouvert par une personne
    await banc.traiteur().traiter()
    assert forge_simulee.etat(1)[0] == "open" and len(forge_simulee.commentaires[1]) == 1


async def test_tickets_ordinaires_non_traites(forge_simulee: ForgeSimulee, banc: Banc) -> None:
    forge_simulee.ouvrir(1, "Merci pour ce site !", titre="Bravo", etiquettes=())
    bilan = await banc.traiteur().traiter()
    assert bilan.lues == 0 and forge_simulee.commentaires[1] == []


# --------------------------------------------------------------------------- #
# Client Forgejo, verrou, commande
# --------------------------------------------------------------------------- #


def test_depot_invalide() -> None:
    with pytest.raises(ValueError, match="dépôt invalide"):
        ClientForge("pas un dépôt; rm -rf /", SecretStr(JETON))


async def test_client_ignore_les_demandes_de_fusion(forge_simulee: ForgeSimulee) -> None:
    forge_simulee.ouvrir(1, corps_formulaire("exempleville.fr"))
    forge_simulee.tickets[1]["pull_request"] = {"merged": False}
    async with ClientForge(DEPOT, SecretStr(JETON), url_api=API) as forge:
        assert await forge.tickets_ouverts() == []


def test_verrou_exclusif(tmp_path: Path) -> None:
    chemin = tmp_path / "donnees" / "bbcloud.verrou"
    with verrou_exclusif(chemin) as premier:
        assert premier
        with verrou_exclusif(chemin) as second:
            assert not second
    with verrou_exclusif(chemin) as apres:
        assert apres


def parametres_cli(dossier: Path, jeton: str | None) -> Parametres:
    """Paramètres isolés du fichier .env réel (les tests tournent aussi sur le serveur)."""
    return Parametres(
        _env_file=None,  # type: ignore[call-arg]
        chemin_base_sqlite=dossier / "base.db",
        chemin_verrou=dossier / "bbcloud.verrou",
        codeberg_jeton=SecretStr(jeton) if jeton else None,
    )


def test_cli_sans_jeton(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "bleublanccloud.cli.obtenir_parametres", lambda: parametres_cli(tmp_path, None)
    )
    resultat = CliRunner().invoke(app, ["demandes", "traiter"])
    assert resultat.exit_code == 0
    assert "aucune demande traitée" in resultat.output


def test_cli_verrou_pris(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "bleublanccloud.cli.obtenir_parametres", lambda: parametres_cli(tmp_path, JETON)
    )
    with verrou_exclusif(tmp_path / "bbcloud.verrou"):
        resultat = CliRunner().invoke(app, ["demandes", "traiter"])
    assert resultat.exit_code == 0
    assert "traitement reporté" in resultat.output
    assert JETON not in resultat.output


def test_valeur_vide_du_env_vaut_non_renseignee(tmp_path: Path) -> None:
    fichier = tmp_path / ".env"
    fichier.write_text("CODEBERG_JETON=\nMISTRAL_API_KEY=\n")
    parametres = Parametres(_env_file=fichier)  # type: ignore[call-arg]
    assert parametres.codeberg_jeton is None and parametres.mistral_api_key is None


def test_modele_forgejo_coherent_avec_le_robot() -> None:
    """Le modèle publié et le repli pré-rempli du site produisent ce que le robot sait lire."""
    import yaml

    from bleublanccloud.configuration import RACINE_PROJET
    from bleublanccloud.demandes.tickets import (
        ETIQUETTE_ANALYSE,
        LIBELLE_DOMAINE,
        PREFIXE_TITRE,
        TEXTE_ENGAGEMENT,
    )

    modele = yaml.safe_load(
        (RACINE_PROJET / "deploy/codeberg/.forgejo/issue_template/analyse.yaml").read_text()
    )
    assert modele["labels"] == [ETIQUETTE_ANALYSE]
    assert modele["title"].strip() == PREFIXE_TITRE
    champs = {bloc.get("id"): bloc for bloc in modele["body"]}
    assert champs["domaine"]["attributes"]["label"] == LIBELLE_DOMAINE
    assert champs["domaine"]["validations"]["required"] is True
    [case] = champs["engagement"]["attributes"]["options"]
    assert case["label"] == TEXTE_ENGAGEMENT and case["required"] is True

    repli = (RACINE_PROJET / "site/src/lib/demandes.ts").read_text()
    assert f'"{LIBELLE_DOMAINE} : "' in repli
    assert f'"- [ ] {TEXTE_ENGAGEMENT}"' in repli
    assert f'encodeURIComponent("{PREFIXE_TITRE} ")' in repli


async def test_identifiants_de_fiche_distincts(
    forge_simulee: ForgeSimulee,
    base: Base,
    referentiels: Referentiels,
    parametres: Parametres,
    resolveur_asn: ResolveurAsn,
) -> None:
    # « a-b.fr » et « a.b.fr » donnent le même identifiant : pas d'écrasement de fiche
    scenario = {
        "resolutions": {
            "a-b.fr": {"ipv4": ["51.91.10.20"]},
            "a.b.fr": {"ipv4": ["51.91.10.20"]},
        }
    }
    banc = Banc(base, referentiels, parametres, resolveur_asn, scenario)
    forge_simulee.ouvrir(1, corps_formulaire("a-b.fr"), auteur="alice")
    forge_simulee.ouvrir(2, corps_formulaire("a.b.fr"), auteur="bob")
    bilan = await banc.traiteur().traiter()
    assert bilan.traitees == [1, 2]
    fiches = {
        e.organisation.site_web
        for e in banc.base.organisations()
        if e.organisation.type == "sur_demande"
    }
    assert fiches == {"https://a-b.fr/", "https://a.b.fr/"}


def test_ipv4_essayee_en_premier() -> None:
    from bleublanccloud.sondes.reseau import verifier_adresses

    assert verifier_adresses("x", ["2a0a:4580:103f:c0de::2", "51.91.10.20"]) == [
        "51.91.10.20",
        "2a0a:4580:103f:c0de::2",
    ]
