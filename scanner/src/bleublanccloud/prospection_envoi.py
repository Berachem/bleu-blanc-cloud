"""Envoi programmé des mails de la prospection badge « Note A » (classeur privé).

Lancé par `bbcloud prospection envoyer` (timer systemd du mardi au jeudi, 9 h 05) :

1. relit la boîte de réception (IMAP) : une réponse d'une mairie passe sa ligne en
   « Réponse reçue », un message de non-distribution en « Adresse introuvable » ;
2. envoie au plus le quota du jour (rodage puis croisière), avec une pause aléatoire de
   quelques minutes entre deux mails : premiers envois, puis une relance unique après le délai ;
3. note la date d'envoi (ou de relance) et le statut dans le classeur après CHAQUE mail.

Seules les lignes « À contacter » (premier mail) et « Envoyé » (relance) sont concernées :
« Pas intéressé », « Réponse reçue », « Badge intégré »… ne reçoivent plus rien.
Les adresses ne quittent jamais le serveur : ni journal détaillé, ni publication.
"""

from __future__ import annotations

import contextlib
import email.utils
import html
import imaplib
import random
import re
import smtplib
import ssl
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.parser import BytesParser
from email.policy import default as politique_defaut
from pathlib import Path
from string import Template
from typing import Any, Literal

from bleublanccloud.prospection import DATE_ENVOI, DATE_RELANCE, _openpyxl

DOSSIER_MODELES = Path(__file__).resolve().parent / "courriels"
COLONNES_REQUISES = (
    DATE_ENVOI,
    "Commune",
    "Score",
    "E-mail de contact",
    "Statut",
    DATE_RELANCE,
    "Slug",
)
MOTIF_ADRESSE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,63}$", re.IGNORECASE)
MOTIF_REBOND = re.compile(r"mailer-daemon|postmaster|mail delivery", re.IGNORECASE)
# Réponses automatiques (accusé de réception, absence) : ce ne sont pas de vraies réponses
MOTIF_AUTOMATIQUE = re.compile(
    r"^(r[ée]ponse automatique|accus[ée] de r[ée]ception|absence"
    r"|automatic reply|auto(matic)?[- ]?reply|out of office)",
    re.IGNORECASE,
)
MOIS_IMAP = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
TypeEnvoi = Literal["premier", "relance"]


class ClasseurInvalide(RuntimeError):
    """Le classeur ne contient pas les colonnes attendues."""


@dataclass(frozen=True)
class Reglages:
    """Paramètres d'expédition (le mot de passe n'est jamais stocké ici)."""

    adresse: str
    nom: str
    url_site: str
    nombre_a: int
    nombre_analysees: int
    quota_rodage: int = 10
    quota_croisiere: int = 25
    seuil_rodage: int = 50
    delai_relance_jours: int = 14
    pause_min_s: float = 180
    pause_max_s: float = 360

    @property
    def domaine_site(self) -> str:
        return self.url_site.removeprefix("https://").removeprefix("http://").rstrip("/")


@dataclass
class Destinataire:
    rang: int
    slug: str
    commune: str
    score: int
    courriel: str | None
    statut: str
    date_envoi: date | None
    date_relance: date | None


@dataclass(frozen=True)
class MessageRecu:
    """Résumé d'un message de la boîte de réception (pour repérer réponses et rebonds)."""

    expediteur: str
    sujet: str
    date: date | None
    corps: str = ""
    automatique: bool = False


@dataclass
class Bilan:
    reponses: list[str] = field(default_factory=list)
    rebonds: list[str] = field(default_factory=list)
    envoyes: list[tuple[str, TypeEnvoi]] = field(default_factory=list)
    erreurs: list[tuple[str, str]] = field(default_factory=list)
    quota: int = 0
    copies_ratees: int = 0


# --------------------------------------------------------------------------- #
# Lecture du classeur
# --------------------------------------------------------------------------- #


def _en_date(valeur: Any) -> date | None:
    if isinstance(valeur, datetime):
        return valeur.date()
    if isinstance(valeur, date):
        return valeur
    if isinstance(valeur, str) and valeur.strip():
        for format_date in ("%d/%m/%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(valeur.strip(), format_date).date()
            except ValueError:
                continue
    return None


def colonnes(feuille: Any) -> dict[str, int]:
    """Numéro de colonne de chaque intitulé ; erreur claire si le classeur est trop ancien."""
    numeros = {str(c.value): c.column for c in feuille[1] if c.value}
    manquantes = [c for c in COLONNES_REQUISES if c not in numeros]
    if manquantes:
        raise ClasseurInvalide(
            f"colonnes absentes du classeur : {', '.join(manquantes)}. Relancez d'abord "
            "« uv run --with openpyxl bbcloud prospection badge » (le suivi est conservé)."
        )
    return numeros


def lire_destinataires(feuille: Any) -> list[Destinataire]:
    numero = colonnes(feuille)
    destinataires: list[Destinataire] = []
    for rang in range(2, feuille.max_row + 1):

        def valeur(intitule: str, rang: int = rang) -> Any:
            return feuille.cell(rang, numero[intitule]).value

        slug = valeur("Slug")
        if not slug:
            continue
        courriel = str(valeur("E-mail de contact") or "").strip() or None
        destinataires.append(
            Destinataire(
                rang=rang,
                slug=str(slug),
                commune=str(valeur("Commune") or ""),
                score=int(valeur("Score") or 0),
                courriel=courriel,
                statut=str(valeur("Statut") or ""),
                date_envoi=_en_date(valeur(DATE_ENVOI)),
                date_relance=_en_date(valeur(DATE_RELANCE)),
            )
        )
    return destinataires


# --------------------------------------------------------------------------- #
# Règles d'envoi
# --------------------------------------------------------------------------- #


def quota_du_jour(destinataires: Iterable[Destinataire], reglages: Reglages, jour: date) -> int:
    """Rodage (10 par jour) tant que moins de 50 premiers mails sont partis, puis croisière.
    Les envois déjà faits aujourd'hui (relance comprise) sont déduits."""
    liste = list(destinataires)
    deja = sum(1 for d in liste if d.date_envoi)
    plafond = reglages.quota_rodage if deja < reglages.seuil_rodage else reglages.quota_croisiere
    aujourd_hui = sum(1 for d in liste if d.date_envoi == jour) + sum(
        1 for d in liste if d.date_relance == jour
    )
    return max(0, plafond - aujourd_hui)


def type_envoi(
    destinataire: Destinataire, jour: date, reglages: Reglages, relances: bool
) -> TypeEnvoi | None:
    """Premier mail, relance unique, ou rien."""
    if not destinataire.courriel or not MOTIF_ADRESSE.match(destinataire.courriel):
        return None
    if destinataire.statut == "À contacter" and destinataire.date_envoi is None:
        return "premier"
    if (
        relances
        and destinataire.statut == "Envoyé"
        and destinataire.date_envoi is not None
        and destinataire.date_relance is None
        and jour - destinataire.date_envoi >= timedelta(days=reglages.delai_relance_jours)
    ):
        return "relance"
    return None


def planifier(
    destinataires: list[Destinataire], jour: date, reglages: Reglages, relances: bool, maximum: int
) -> list[tuple[Destinataire, TypeEnvoi]]:
    """Relances d'abord (elles sont dues), puis premiers mails dans l'ordre du classeur."""
    candidats = [(d, t) for d in destinataires if (t := type_envoi(d, jour, reglages, relances))]
    candidats.sort(key=lambda c: (c[1] != "relance", c[0].rang))
    return candidats[:maximum]


# --------------------------------------------------------------------------- #
# Réponses et rebonds
# --------------------------------------------------------------------------- #


def _domaine(adresse: str) -> str:
    return adresse.rsplit("@", 1)[-1].lower().strip(">").strip()


def analyser_boite(
    messages: Iterable[MessageRecu],
    destinataires: Iterable[Destinataire],
    ignorer: str | None = None,
) -> dict[str, str]:
    """Nouveau statut par slug : « Réponse reçue » ou « Adresse introuvable ».

    Réponse : message reçu après l'envoi, venant du domaine de l'adresse contactée, ou dont
    l'objet reprend « <Commune> obtient la note A » (réponse depuis une autre adresse).
    Rebond : message de non-distribution qui cite l'adresse contactée.
    Ignorés : réponses automatiques (accusé de réception, absence) et messages de l'adresse
    d'envoi elle-même (mails de test).
    """
    suivis = [
        d
        for d in destinataires
        if d.courriel and d.date_envoi and d.statut in ("Envoyé", "Relancé")
    ]
    statuts: dict[str, str] = {}
    for message in messages:
        expediteur = email.utils.parseaddr(message.expediteur)[1].lower()
        rebond = bool(MOTIF_REBOND.search(message.expediteur))
        if (ignorer and expediteur == ignorer.lower()) or (message.automatique and not rebond):
            continue
        for d in suivis:
            assert d.courriel and d.date_envoi
            if message.date and message.date < d.date_envoi:
                continue
            if rebond:
                if d.courriel.lower() in message.corps.lower():
                    statuts[d.slug] = "Adresse introuvable"
                continue
            meme_domaine = expediteur and _domaine(expediteur) == _domaine(d.courriel)
            objet = f"{d.commune} obtient la note A".lower() in message.sujet.lower()
            if (meme_domaine or objet) and statuts.get(d.slug) != "Adresse introuvable":
                statuts[d.slug] = "Réponse reçue"
    return statuts


def _decoder(valeur: str | None) -> str:
    return str(make_header(decode_header(valeur or "")))


def lire_boite(imap: Any, depuis: date) -> list[MessageRecu]:
    """Messages de la boîte de réception depuis une date (lecture seule, sans les marquer lus)."""
    imap.select("INBOX", readonly=True)
    # Format IMAP en anglais, quelle que soit la langue du serveur (« 05-Nov-2026 »)
    critere = f"{depuis.day:02d}-{MOIS_IMAP[depuis.month - 1]}-{depuis.year}"
    statut, donnees = imap.search(None, "SINCE", critere)
    if statut != "OK" or not donnees or not donnees[0]:
        return []
    messages: list[MessageRecu] = []
    for numero in donnees[0].split():
        statut, parties = imap.fetch(numero, "(BODY.PEEK[])")
        brut = next((p[1] for p in parties or [] if isinstance(p, tuple)), None)
        if statut != "OK" or not brut:
            continue
        lu = BytesParser(policy=politique_defaut).parsebytes(brut)
        horodatage = lu.get("Date")
        try:
            jour = email.utils.parsedate_to_datetime(horodatage).date() if horodatage else None
        except (TypeError, ValueError):
            jour = None
        corps = lu.get_body(preferencelist=("plain", "html"))
        texte = corps.get_content() if corps is not None else ""
        # Les rapports de non-distribution joignent souvent le message d'origine
        if MOTIF_REBOND.search(str(lu.get("From", ""))):
            texte += " ".join(
                str(p.get_payload(decode=False)) for p in lu.walk() if not p.is_multipart()
            )
        sujet = _decoder(lu.get("Subject"))
        automatique = (
            str(lu.get("Auto-Submitted", "no")).lower() != "no"
            or bool(lu.get("X-Autoreply") or lu.get("X-Autorespond"))
            or str(lu.get("Precedence", "")).lower() in ("auto_reply", "bulk", "junk")
            or bool(
                MOTIF_AUTOMATIQUE.search(
                    re.sub(r"^\s*(re|tr|fwd?)\s*:\s*", "", sujet, flags=re.IGNORECASE)
                )
            )
        )
        messages.append(
            MessageRecu(
                expediteur=_decoder(lu.get("From")),
                sujet=sujet,
                date=jour,
                corps=texte,
                automatique=automatique,
            )
        )
    return messages


# Noms usuels du dossier des messages envoyés (Apple Mail crée « Sent Messages », Roundcube
# « Sent », Outlook « Sent Items »…), comparés au dernier niveau du chemin (« INBOX.Sent »)
NOMS_ENVOYES = ("sent", "sent messages", "sent items", "envoyés", "éléments envoyés")


def dossier_envoyes(lignes: Iterable[Any]) -> str | None:
    """Dossier « Envoyés » d'après la réponse IMAP LIST : drapeau \\Sent, sinon nom usuel.

    Le nom est rendu tel que le serveur l'a écrit (avec ses guillemets s'il en a), pour
    l'ajout IMAP.
    """
    candidats: list[tuple[int, str]] = []
    for ligne in lignes:
        texte = ligne.decode(errors="replace") if isinstance(ligne, bytes) else str(ligne)
        trouve = re.search(r'\(([^)]*)\) (?:"([^"]*)"|NIL) (.+)$', texte)
        if not trouve:
            continue
        drapeaux, separateur, dossier = trouve.group(1), trouve.group(2), trouve.group(3).strip()
        if "\\Sent" in drapeaux:
            return dossier
        nom = dossier.strip('"')
        dernier = nom.rsplit(separateur, 1)[-1] if separateur else nom
        if dernier.lower() in NOMS_ENVOYES:
            candidats.append((NOMS_ENVOYES.index(dernier.lower()), dossier))
    return min(candidats)[1] if candidats else None


def copier_dans_envoyes(imap: Any, message: EmailMessage) -> bool:
    """Copie le mail dans le dossier « Envoyés » (pour le voir dans Mail sur le Mac)."""
    statut, lignes = imap.list()
    if statut != "OK":
        return False
    nom = dossier_envoyes(lignes or [])
    if not nom:
        return False
    statut, _ = imap.append(nom, "\\Seen", imaplib.Time2Internaldate(time.time()), bytes(message))
    return bool(statut == "OK")


# --------------------------------------------------------------------------- #
# Composition
# --------------------------------------------------------------------------- #


def _nombre(valeur: int) -> str:
    """1162 → « 1 162 » (espace insécable fine, usage français)."""
    return f"{valeur:,}".replace(",", " ")


def _modele(nom: str) -> Template:
    return Template((DOSSIER_MODELES / nom).read_text(encoding="utf-8"))


def composer(
    destinataire: Destinataire,
    genre: TypeEnvoi,
    reglages: Reglages,
    a: str | None = None,
) -> EmailMessage:
    """Mail en texte et HTML (logo hébergé sur le site, sans paramètre de suivi)."""
    url_fiche = f"{reglages.url_site}/organisation/{destinataire.slug}/"
    valeurs = {
        "commune": destinataire.commune,
        "score": str(destinataire.score),
        "nombre_a": _nombre(reglages.nombre_a),
        "nombre_analysees": _nombre(reglages.nombre_analysees),
        "url_fiche": url_fiche,
        "url_site": reglages.url_site,
        "domaine_site": reglages.domaine_site,
        "date_envoi": f"{destinataire.date_envoi:%d/%m/%Y}" if destinataire.date_envoi else "",
    }
    if genre == "premier":
        sujet = f"🏅 {destinataire.commune} obtient la note A en souveraineté numérique"
    else:
        sujet = f"Petit rappel : {destinataire.commune} obtient la note A en souveraineté numérique"
    echappees = {cle: html.escape(valeur) for cle, valeur in valeurs.items()}
    contenu = _modele(f"{genre}.html").substitute(echappees)
    page = _modele("base.html").substitute(echappees, titre=html.escape(sujet), contenu=contenu)

    message = EmailMessage()
    message["Subject"] = sujet
    message["From"] = email.utils.formataddr((reglages.nom, reglages.adresse))
    message["To"] = a or destinataire.courriel or ""
    message["Reply-To"] = reglages.adresse
    message["Date"] = email.utils.formatdate(localtime=True)
    message["Message-ID"] = email.utils.make_msgid(domain=_domaine(reglages.adresse))
    message["List-Unsubscribe"] = (
        f"<mailto:{reglages.adresse}?subject=Ne%20plus%20recevoir%20de%20message>"
    )
    message.set_content(_modele(f"{genre}.txt").substitute(valeurs))
    message.add_alternative(page, subtype="html")
    return message


# --------------------------------------------------------------------------- #
# Exécution
# --------------------------------------------------------------------------- #


def executer(
    chemin: Path,
    reglages: Reglages,
    envoyer: Callable[[EmailMessage], None],
    *,
    jour: date | None = None,
    relances: bool = True,
    maximum: int | None = None,
    messages_recus: list[MessageRecu] | None = None,
    apres_envoi: Callable[[EmailMessage], bool] | None = None,
    attendre: Callable[[float], None] = time.sleep,
) -> Bilan:
    """Met à jour les statuts (réponses, rebonds), puis envoie le quota du jour.

    Le classeur est enregistré après chaque mail : une coupure ne fait jamais renvoyer un
    mail déjà parti.
    """
    jour = jour or date.today()
    classeur = _openpyxl().load_workbook(chemin)
    feuille = classeur["Communes A"]
    numero = colonnes(feuille)
    destinataires = lire_destinataires(feuille)
    bilan = Bilan()

    if messages_recus:
        for slug, statut in analyser_boite(
            messages_recus, destinataires, ignorer=reglages.adresse
        ).items():
            d = next(x for x in destinataires if x.slug == slug)
            feuille.cell(d.rang, numero["Statut"]).value = statut
            d.statut = statut
            (bilan.rebonds if statut == "Adresse introuvable" else bilan.reponses).append(slug)
        classeur.save(chemin)

    bilan.quota = quota_du_jour(destinataires, reglages, jour)
    limite = bilan.quota if maximum is None else min(bilan.quota, maximum)
    plan = planifier(destinataires, jour, reglages, relances, limite)
    for position, (d, genre) in enumerate(plan):
        message = composer(d, genre, reglages)
        try:
            envoyer(message)
        except (smtplib.SMTPException, OSError) as erreur:
            bilan.erreurs.append((d.slug, type(erreur).__name__))
            if isinstance(erreur, smtplib.SMTPRecipientsRefused):
                feuille.cell(d.rang, numero["Statut"]).value = "Adresse introuvable"
                classeur.save(chemin)
                continue
            break  # serveur indisponible ou authentification refusée : on s'arrête là
        if genre == "premier":
            feuille.cell(d.rang, numero[DATE_ENVOI]).value = datetime.combine(
                jour, datetime.min.time()
            )
            feuille.cell(d.rang, numero["Statut"]).value = "Envoyé"
        else:
            feuille.cell(d.rang, numero[DATE_RELANCE]).value = datetime.combine(
                jour, datetime.min.time()
            )
            feuille.cell(d.rang, numero["Statut"]).value = "Relancé"
        classeur.save(chemin)
        bilan.envoyes.append((d.slug, genre))
        if apres_envoi:
            # La copie dans « Envoyés » est un confort : jamais bloquante, mais comptée
            copie = False
            with contextlib.suppress(imaplib.IMAP4.error, OSError):
                copie = apres_envoi(message)
            if not copie:
                bilan.copies_ratees += 1
        if position < len(plan) - 1:
            attendre(random.uniform(reglages.pause_min_s, reglages.pause_max_s))
    return bilan


def apercus(
    chemin: Path, reglages: Reglages, dossier: Path, *, jour: date | None = None, nombre: int = 5
) -> list[Path]:
    """Mode simulation : écrit les prochains mails (.eml et .html) sans rien envoyer ni modifier."""
    jour = jour or date.today()
    feuille = _openpyxl().load_workbook(chemin, read_only=False)["Communes A"]
    destinataires = lire_destinataires(feuille)
    limite = min(nombre, quota_du_jour(destinataires, reglages, jour))
    dossier.mkdir(parents=True, exist_ok=True)
    fichiers: list[Path] = []
    for d, genre in planifier(destinataires, jour, reglages, True, limite):
        message = composer(d, genre, reglages)
        base = dossier / f"{d.slug}-{genre}"
        base.with_suffix(".eml").write_bytes(bytes(message))
        partie_html = message.get_body(preferencelist=("html",))
        if partie_html is not None:
            base.with_suffix(".html").write_text(partie_html.get_content(), encoding="utf-8")
        fichiers.append(base.with_suffix(".eml"))
    return fichiers


@dataclass(frozen=True)
class Connexion:
    """Accès SMTP et IMAP de la boîte d'envoi (OVH MX Plan : ssl0.ovh.net, 465 et 993)."""

    smtp_hote: str
    smtp_port: int
    imap_hote: str
    imap_port: int
    identifiant: str
    mot_de_passe: str

    def smtp(self) -> smtplib.SMTP_SSL:
        serveur = smtplib.SMTP_SSL(
            self.smtp_hote, self.smtp_port, context=ssl.create_default_context(), timeout=60
        )
        serveur.login(self.identifiant, self.mot_de_passe)
        return serveur

    def imap(self) -> imaplib.IMAP4_SSL:
        boite = imaplib.IMAP4_SSL(
            self.imap_hote, self.imap_port, ssl_context=ssl.create_default_context(), timeout=60
        )
        boite.login(self.identifiant, self.mot_de_passe)
        return boite
