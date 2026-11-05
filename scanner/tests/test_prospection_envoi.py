"""Tests de l'envoi programmé de la prospection badge (sans réseau : faux SMTP et IMAP)."""

from __future__ import annotations

import smtplib
from datetime import UTC, date, datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from typer.testing import CliRunner

from bleublanccloud.cibles.annuaire import URL_EXPORT
from bleublanccloud.cli import app
from bleublanccloud.modeles import EntreeIndex
from bleublanccloud.prospection import LigneProspection, ecrire_classeur, lire_suivi
from bleublanccloud.prospection_envoi import (
    ClasseurInvalide,
    Destinataire,
    MessageRecu,
    Reglages,
    analyser_boite,
    apercus,
    composer,
    copier_dans_envoyes,
    executer,
    lire_boite,
    quota_du_jour,
    type_envoi,
)
from tests import test_statistiques

openpyxl = pytest.importorskip("openpyxl")

# Fixture partagée (base avec trois scans notés, dont Bordeaux en A)
base_statistiques = test_statistiques.base_remplie

JOUR = date(2026, 11, 10)
REGLAGES = Reglages(
    adresse="contact@bbc.example",
    nom="Berachem Markria · Bleu Blanc Cloud",
    url_site="https://bbc.example",
    nombre_a=486,
    nombre_analysees=1162,
    quota_rodage=2,
    quota_croisiere=3,
    seuil_rodage=4,
    pause_min_s=0,
    pause_max_s=0,
)


def entree(slug: str, nom: str, score: int = 100) -> EntreeIndex:
    return EntreeIndex(
        slug=slug,
        nom=nom,
        type="commune",
        departement="44",
        departement_nom="Loire-Atlantique",
        population=10_000,
        domaine=f"{slug}.example",
        score=score,
        note="A",
        date_scan=datetime(2026, 9, 27, tzinfo=UTC),
    )


def classeur(tmp_path: Path, suivis: dict[str, dict[str, Any]]) -> Path:
    """Classeur avec une ligne par entrée de `suivis` (slug → colonnes de suivi)."""
    lignes = [
        LigneProspection(entree=entree(slug, slug.split("-")[0].capitalize()), suivi=suivi)
        for slug, suivi in suivis.items()
    ]
    chemin = tmp_path / "prive" / "prospection.xlsx"
    ecrire_classeur(chemin, lignes, "https://bbc.example")
    return chemin


def a_contacter(courriel: str) -> dict[str, Any]:
    return {"E-mail de contact": courriel, "Statut": "À contacter"}


def destinataire(**champs: Any) -> Destinataire:
    valeurs: dict[str, Any] = {
        "rang": 2,
        "slug": "nantes-44109",
        "commune": "Nantes",
        "score": 100,
        "courriel": "contact@mairie-nantes.example",
        "statut": "À contacter",
        "date_envoi": None,
        "date_relance": None,
    }
    valeurs.update(champs)
    return Destinataire(**valeurs)


class FauxSmtp:
    def __init__(self, refuser: set[str] | None = None, panne_apres: int | None = None) -> None:
        self.envoyes: list[EmailMessage] = []
        self.refuser = refuser or set()
        self.panne_apres = panne_apres

    def __call__(self, message: EmailMessage) -> None:
        if self.panne_apres is not None and len(self.envoyes) >= self.panne_apres:
            raise smtplib.SMTPServerDisconnected("coupure")
        if message["To"] in self.refuser:
            raise smtplib.SMTPRecipientsRefused({message["To"]: (550, b"inconnu")})
        self.envoyes.append(message)


# --------------------------------------------------------------------------- #
# Composition
# --------------------------------------------------------------------------- #


def test_mail_complet_texte_et_html() -> None:
    message = composer(destinataire(commune="Saint-Gély-du-Fesc & Cie"), "premier", REGLAGES)
    assert message["Subject"] == (
        "🏅 Saint-Gély-du-Fesc & Cie obtient la note A en souveraineté numérique"
    )
    assert message["To"] == "contact@mairie-nantes.example"
    assert message["Reply-To"] == "contact@bbc.example"
    assert "Ne%20plus%20recevoir" in message["List-Unsubscribe"]
    texte = message.get_body(preferencelist=("plain",)).get_content()
    page = message.get_body(preferencelist=("html",)).get_content()
    assert "fait partie des collectivités exemplaires" in texte
    assert "486" not in texte and "486" not in page  # aucun chiffre de classement
    assert "https://bbc.example/organisation/nantes-44109/" in texte
    assert "🎉" in texte
    assert "Saint-Gély-du-Fesc &amp; Cie" in page  # échappé dans le HTML
    assert 'src="https://bbc.example/courriel/logo-bleu-blanc-cloud.png"' in page
    assert "$" not in texte and "$" not in page


def test_relance_courte_et_datee() -> None:
    message = composer(destinataire(date_envoi=date(2026, 11, 3)), "relance", REGLAGES)
    assert message["Subject"].startswith("Petit rappel : Nantes obtient la note A")
    texte = message.get_body(preferencelist=("plain",)).get_content()
    assert "mon message du 03/11/2026" in texte
    assert "seul rappel" in texte


# --------------------------------------------------------------------------- #
# Règles
# --------------------------------------------------------------------------- #


def test_quota_rodage_puis_croisiere_moins_les_envois_du_jour() -> None:
    assert quota_du_jour([destinataire()], REGLAGES, JOUR) == 2
    partis = [destinataire(date_envoi=date(2026, 11, 3)) for _ in range(4)]
    assert quota_du_jour(partis, REGLAGES, JOUR) == 3
    aujourd_hui = [*partis, destinataire(date_envoi=JOUR), destinataire(date_relance=JOUR)]
    assert quota_du_jour(aujourd_hui, REGLAGES, JOUR) == 1


@pytest.mark.parametrize(
    ("champs", "attendu"),
    [
        ({}, "premier"),
        ({"courriel": None}, None),
        ({"courriel": "pas-une-adresse"}, None),
        ({"statut": "Pas intéressé"}, None),
        ({"statut": "Adresse introuvable"}, None),
        ({"statut": "Envoyé", "date_envoi": date(2026, 10, 27)}, "relance"),
        ({"statut": "Envoyé", "date_envoi": date(2026, 11, 3)}, None),  # moins de 14 jours
        (
            {
                "statut": "Envoyé",
                "date_envoi": date(2026, 10, 1),
                "date_relance": date(2026, 10, 20),
            },
            None,
        ),
        ({"statut": "Relancé", "date_envoi": date(2026, 10, 1)}, None),
        ({"statut": "Réponse reçue", "date_envoi": date(2026, 10, 1)}, None),
    ],
)
def test_type_envoi(champs: dict[str, Any], attendu: str | None) -> None:
    assert type_envoi(destinataire(**champs), JOUR, REGLAGES, relances=True) == attendu


def test_sans_relances() -> None:
    envoye = destinataire(statut="Envoyé", date_envoi=date(2026, 10, 1))
    assert type_envoi(envoye, JOUR, REGLAGES, relances=False) is None


# --------------------------------------------------------------------------- #
# Réponses et rebonds
# --------------------------------------------------------------------------- #


def test_reponses_et_rebonds() -> None:
    envoye = date(2026, 11, 3)
    destinataires = [
        destinataire(slug="nantes", statut="Envoyé", date_envoi=envoye),
        destinataire(
            slug="albi",
            commune="Albi",
            courriel="secretariat@mairie-albi.example",
            statut="Envoyé",
            date_envoi=envoye,
        ),
        destinataire(
            slug="sete",
            commune="Sète",
            courriel="mairie@ville-sete.example",
            statut="Relancé",
            date_envoi=envoye,
        ),
        destinataire(slug="lyon", commune="Lyon", courriel="x@lyon.example"),  # jamais écrit
    ]
    messages = [
        # Réponse depuis une autre adresse du même domaine
        MessageRecu("Service com <com@mairie-nantes.example>", "Merci !", date(2026, 11, 4)),
        # Réponse depuis un autre domaine, objet repris
        MessageRecu(
            "dsi@agglo.example",
            "Re: 🏅 Sète obtient la note A en souveraineté numérique",
            date(2026, 11, 5),
        ),
        # Rebond qui cite l'adresse d'Albi
        MessageRecu(
            "Mail Delivery System <MAILER-DAEMON@ovh.example>",
            "Undelivered Mail Returned to Sender",
            date(2026, 11, 3),
            corps="Final-Recipient: rfc822; secretariat@mairie-albi.example",
        ),
        # Message antérieur à l'envoi : ignoré
        MessageRecu("x@lyon.example", "Bonjour", date(2026, 10, 1)),
    ]
    ignores = [
        # Accusé de réception automatique : la relance reste possible
        MessageRecu(
            "accueil@mairie-nantes.example",
            "Accusé de réception",
            date(2026, 11, 3),
            automatique=True,
        ),
        # Mail de test envoyé à sa propre boîte
        MessageRecu("contact@bbc.example", "[TEST] 🏅 Albi obtient la note A", date(2026, 11, 4)),
    ]
    assert analyser_boite(ignores, destinataires, ignorer="contact@bbc.example") == {}
    assert analyser_boite(messages, destinataires) == {
        "nantes": "Réponse reçue",
        "sete": "Réponse reçue",
        "albi": "Adresse introuvable",
    }


class FausseBoite:
    def __init__(self, messages: list[bytes]) -> None:
        self.messages = messages
        self.ajouts: list[tuple[str, bytes]] = []

    def select(self, dossier: str, readonly: bool = False) -> tuple[str, list[bytes]]:
        assert readonly
        return "OK", [b"1"]

    def search(self, charset: Any, *criteres: str) -> tuple[str, list[bytes]]:
        assert criteres[0] == "SINCE"
        assert criteres[1] == "01-Nov-2026"  # mois en anglais, quelle que soit la langue
        return "OK", [" ".join(str(i + 1) for i in range(len(self.messages))).encode()]

    def fetch(self, numero: bytes, partie: str) -> tuple[str, list[Any]]:
        assert "PEEK" in partie  # ne marque pas les messages comme lus
        return "OK", [(b"1 (BODY[] {10}", self.messages[int(numero) - 1]), b")"]

    def list(self) -> tuple[str, list[bytes]]:
        return "OK", [b'(\\HasNoChildren) "." INBOX', b'(\\HasNoChildren \\Sent) "." "Sent"']

    def append(
        self, dossier: str, drapeaux: str, date_interne: Any, brut: bytes
    ) -> tuple[str, Any]:
        self.ajouts.append((dossier, brut))
        return "OK", None


def test_lecture_de_la_boite_et_copie_dans_envoyes() -> None:
    reponse = (
        b"From: =?utf-8?q?Mairie_de_S=C3=A8te?= <mairie@ville-sete.example>\r\n"
        b"Subject: Re: =?utf-8?q?S=C3=A8te_obtient_la_note_A?=\r\n"
        b"Date: Wed, 05 Nov 2026 10:00:00 +0100\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\nMerci beaucoup !\r\n"
    )
    boite = FausseBoite([reponse])
    (message,) = lire_boite(boite, date(2026, 11, 1))
    assert message.expediteur == "Mairie de Sète <mairie@ville-sete.example>"
    assert message.sujet == "Re: Sète obtient la note A"
    assert message.date == date(2026, 11, 5)
    assert "Merci beaucoup" in message.corps
    assert not message.automatique

    automatique = (
        b"From: accueil@mairie-albi.example\r\nSubject: RE: Accus\xc3\xa9 de r\xc3\xa9ception\r\n"
        b"Auto-Submitted: auto-replied\r\nDate: Wed, 05 Nov 2026 10:00:00 +0100\r\n\r\nMerci\r\n"
    )
    assert lire_boite(FausseBoite([automatique]), date(2026, 11, 1))[0].automatique

    assert copier_dans_envoyes(boite, composer(destinataire(), "premier", REGLAGES))
    assert boite.ajouts[0][0] == '"Sent"'


# --------------------------------------------------------------------------- #
# Exécution complète
# --------------------------------------------------------------------------- #


def test_execution_quota_dates_statuts_et_pauses(tmp_path: Path) -> None:
    chemin = classeur(
        tmp_path,
        {
            "nantes-44109": a_contacter("contact@mairie-nantes.example"),
            "albi-81004": a_contacter("secretariat@mairie-albi.example"),
            "sete-34301": a_contacter("mairie@ville-sete.example"),
            "lyon-69123": {"Statut": "Adresse introuvable"},
            "dijon-21231": {**a_contacter("contact@dijon.example"), "Statut": "Pas intéressé"},
        },
    )
    smtp = FauxSmtp()
    pauses: list[float] = []
    bilan = executer(chemin, REGLAGES, smtp, jour=JOUR, attendre=pauses.append)
    assert [m["To"] for m in smtp.envoyes] == [
        "contact@mairie-nantes.example",
        "secretariat@mairie-albi.example",
    ]  # quota de rodage : 2
    assert len(pauses) == 1  # une pause entre deux mails, pas après le dernier
    assert bilan.quota == 2
    suivi = lire_suivi(chemin)
    assert suivi["nantes-44109"]["Date mail envoyé"] == datetime(2026, 11, 10)
    assert suivi["nantes-44109"]["Statut"] == "Envoyé"
    assert "Date mail envoyé" not in suivi["sete-34301"]

    # Même jour : quota épuisé, rien ne repart
    assert executer(chemin, REGLAGES, smtp, jour=JOUR, attendre=pauses.append).envoyes == []
    assert len(smtp.envoyes) == 2

    # Le lendemain : Sète ; la réponse de Nantes est prise en compte
    reponse = MessageRecu("com@mairie-nantes.example", "Merci", date(2026, 11, 10))
    bilan = executer(
        chemin,
        REGLAGES,
        smtp,
        jour=date(2026, 11, 11),
        messages_recus=[reponse],
        attendre=pauses.append,
    )
    assert bilan.reponses == ["nantes-44109"]
    assert [slug for slug, _ in bilan.envoyes] == ["sete-34301"]

    # 14 jours plus tard : relance d'Albi seulement (Nantes a répondu, Sète trop récent)
    bilan = executer(chemin, REGLAGES, smtp, jour=date(2026, 11, 24), attendre=pauses.append)
    assert bilan.envoyes == [("albi-81004", "relance")]
    suivi = lire_suivi(chemin)
    assert suivi["albi-81004"]["Statut"] == "Relancé"
    assert suivi["albi-81004"]["Date relance"] == datetime(2026, 11, 24)
    assert suivi["nantes-44109"]["Statut"] == "Réponse reçue"
    assert smtp.envoyes[-1]["Subject"].startswith("Petit rappel : Albi")


def test_adresse_refusee_et_panne_du_serveur(tmp_path: Path) -> None:
    chemin = classeur(
        tmp_path,
        {
            "nantes-44109": a_contacter("refuse@nantes.example"),
            "albi-81004": a_contacter("ok@albi.example"),
            "sete-34301": a_contacter("ok@sete.example"),
        },
    )
    reglages = Reglages(**{**REGLAGES.__dict__, "quota_rodage": 3})
    bilan = executer(
        chemin,
        reglages,
        FauxSmtp(refuser={"refuse@nantes.example"}, panne_apres=1),
        jour=JOUR,
        attendre=lambda _: None,
    )
    assert bilan.envoyes == [("albi-81004", "premier")]
    assert [nature for _, nature in bilan.erreurs] == [
        "SMTPRecipientsRefused",
        "SMTPServerDisconnected",
    ]
    suivi = lire_suivi(chemin)
    assert suivi["nantes-44109"]["Statut"] == "Adresse introuvable"
    # Coupure : Sète reste à contacter, sans date (il partira au prochain passage)
    assert suivi["sete-34301"]["Statut"] == "À contacter"
    assert "Date mail envoyé" not in suivi["sete-34301"]


def test_simulation_ne_modifie_rien(tmp_path: Path) -> None:
    chemin = classeur(tmp_path, {"nantes-44109": a_contacter("contact@nantes.example")})
    avant = chemin.read_bytes()
    fichiers = apercus(chemin, REGLAGES, tmp_path / "apercus", jour=JOUR)
    assert [f.name for f in fichiers] == ["nantes-44109-premier.eml"]
    assert (tmp_path / "apercus" / "nantes-44109-premier.html").exists()
    assert chemin.read_bytes() == avant


def test_classeur_trop_ancien(tmp_path: Path) -> None:
    chemin = tmp_path / "ancien.xlsx"
    ancien = openpyxl.Workbook()
    ancien.active.title = "Communes A"
    ancien.active.append(["Commune", "Statut", "Slug"])
    ancien.save(chemin)
    with pytest.raises(ClasseurInvalide, match="prospection badge"):
        executer(chemin, REGLAGES, FauxSmtp(), jour=JOUR)


# --------------------------------------------------------------------------- #
# Commande
# --------------------------------------------------------------------------- #


@respx.mock
def test_commande_simulation_puis_sans_mot_de_passe(
    base_statistiques: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    respx.get(URL_EXPORT).mock(return_value=httpx.Response(200, json=[]))
    chemin = base_statistiques / "prospection.xlsx"
    lanceur = CliRunner()
    assert lanceur.invoke(app, ["prospection", "badge", "--vers", str(chemin)]).exit_code == 0
    classeur_xlsx = openpyxl.load_workbook(chemin)
    feuille = classeur_xlsx["Communes A"]
    feuille["L2"] = "contact@bordeaux.example"
    feuille["N2"] = "À contacter"
    classeur_xlsx.save(chemin)

    sans_adresse = lanceur.invoke(app, ["prospection", "envoyer", "--vers", str(chemin)])
    assert sans_adresse.exit_code == 1
    assert "COURRIEL_ADRESSE" in sans_adresse.output

    monkeypatch.setenv("COURRIEL_ADRESSE", "contact@bbc.example")
    from bleublanccloud.configuration import obtenir_parametres

    obtenir_parametres.cache_clear()
    resultat = lanceur.invoke(
        app, ["prospection", "envoyer", "--vers", str(chemin), "--simulation"]
    )
    assert resultat.exit_code == 0, resultat.output
    assert "2 notées A sur 3 analysées" in resultat.output
    assert (base_statistiques / "apercus" / "bordeaux-premier.eml").exists()

    sans_mot_de_passe = lanceur.invoke(app, ["prospection", "envoyer", "--vers", str(chemin)])
    assert sans_mot_de_passe.exit_code == 1
    assert "COURRIEL_MOT_DE_PASSE" in sans_mot_de_passe.output
