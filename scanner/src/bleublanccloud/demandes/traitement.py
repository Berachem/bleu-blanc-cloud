"""Traitement des tickets « Analyser mon site » : validation, limites, analyse, réponse.

Déroulé d'un passage (commande `bbcloud demandes traiter`, toutes les heures) :

1. lecture des tickets ouverts (étiquette « analyse » ou titre « [Analyse] … ») ;
2. pour chaque nouvelle demande : case d'engagement, domaine (validation stricte), liste de
   retraits, adresses publiques uniquement, limites quotidiennes ;
3. réutilisation d'une analyse de moins de 7 jours, sinon scan passif + score + rapport IA ;
4. une seule publication du site pour toutes les demandes acceptées ;
5. réponse dans chaque ticket, étiquette « traitée » / « refusée » / « erreur », fermeture.

Une erreur technique laisse le ticket ouvert (étiquette « erreur ») : il est retenté au
passage suivant, puis fermé après le nombre maximal de tentatives.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from typing import Final
from zoneinfo import ZoneInfo

from bleublanccloud.analyse.score import VERSION_METHODO, ScoreImpossible, calculer_score
from bleublanccloud.cibles.importation import slugifier
from bleublanccloud.demandes.forge import ErreurForge, Forge
from bleublanccloud.demandes.reponses import reponse_erreur, reponse_refusee, reponse_traitee
from bleublanccloud.demandes.tickets import (
    ETIQUETTE_ERREUR,
    ETIQUETTE_REFUSEE,
    ETIQUETTE_TRAITEE,
    Ticket,
    case_cochee,
    extraire_domaine,
)
from bleublanccloud.demandes.validation import DomaineRefuse, nom_lisible, valider_domaine
from bleublanccloud.export.site_statique import domaine_organisation, score_a_jour
from bleublanccloud.modeles import Organisation, ResultatScan
from bleublanccloud.referentiels import Referentiels
from bleublanccloud.scan import normaliser_cible
from bleublanccloud.sondes.reseau import est_adresse_publique
from bleublanccloud.stockage.base import Base, DemandeEnregistree

journal = logging.getLogger(__name__)

FUSEAU: Final = ZoneInfo("Europe/Paris")
LIMITE_JOUR: Final = 10
LIMITE_COMPTE: Final = 1
DELAI_REUTILISATION: Final = timedelta(days=7)
TENTATIVES_MAX: Final = 3
SOURCE: Final = "demande-codeberg"
SOURCE_EMAIL: Final = "demande-email"

Analyser = Callable[[str], Awaitable[ResultatScan]]
Resoudre = Callable[[str], Awaitable[list[str]]]
Publier = Callable[[], Awaitable[bool]]
GenererRapport = Callable[[int], Awaitable[None]]


class Refus(Exception):
    """Demande refusée ; le code sélectionne la réponse polie (voir reponses.py)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ErreurTechnique(Exception):
    """Échec indépendant de la demande (réseau, site injoignable…) : sera retenté."""


@dataclass
class BilanDemandes:
    lues: int = 0
    traitees: list[int] = field(default_factory=list)
    refusees: list[tuple[int, str]] = field(default_factory=list)
    erreurs: list[tuple[int, str]] = field(default_factory=list)
    publication: bool | None = None
    reponses_en_attente: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class AnalyseDirecte:
    """Résultat d'une demande reçue hors ticket (e-mail), à communiquer au demandeur."""

    hote: str
    slug: str
    url_fiche: str
    note: str
    score: int
    provisoire: bool
    reutilisee: bool


@dataclass
class TraiteurDemandes:
    """Orchestration d'un passage ; toutes les dépendances externes sont injectées."""

    base: Base
    referentiels: Referentiels
    forge: Forge
    analyser: Analyser
    resoudre: Resoudre
    publier: Publier
    url_site: str
    generer_rapport: GenererRapport | None = None
    limite_jour: int = LIMITE_JOUR
    limite_compte: int = LIMITE_COMPTE
    delai_reutilisation: timedelta = DELAI_REUTILISATION
    tentatives_max: int = TENTATIVES_MAX
    source: str = SOURCE
    """Origine enregistrée sur les fiches créées (ticket Codeberg ou e-mail)."""
    maintenant: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))

    @property
    def url_methodologie(self) -> str:
        return f"{self.url_site.rstrip('/')}/methodologie/"

    # ------------------------------------------------------------------ #
    # Passage complet
    # ------------------------------------------------------------------ #

    async def traiter(self) -> BilanDemandes:
        """Traite les demandes ouvertes. Lève ErreurForge si la forge est injoignable."""
        bilan = BilanDemandes()
        tickets = sorted(
            (t for t in await self.forge.tickets_ouverts() if t.est_demande),
            key=lambda t: t.numero,
        )
        bilan.lues = len(tickets)
        a_publier: list[tuple[Ticket, DemandeEnregistree]] = []
        for ticket in tickets:
            suivi = self.base.demande(self.forge.depot, ticket.numero) or DemandeEnregistree(
                depot=self.forge.depot,
                numero=ticket.numero,
                auteur=ticket.auteur,
                statut="nouvelle",
                recue_le=self.maintenant(),
            )
            if suivi.cloturee_le is not None:
                continue  # ticket rouvert par une personne : le robot n'y touche plus
            if suivi.statut in ("traitee", "refusee", "echec"):
                await self._repondre(ticket, suivi, bilan)  # réponse restée en attente
                continue
            try:
                await self._examiner(ticket, suivi)
            except Refus as refus:
                suivi.statut, suivi.motif = "refusee", refus.code
                self.base.enregistrer_demande(suivi)
                bilan.refusees.append((ticket.numero, refus.code))
                await self._repondre(ticket, suivi, bilan)
            except Exception as erreur:
                await self._echec_technique(ticket, suivi, erreur, bilan)
            else:
                a_publier.append((ticket, suivi))

        if a_publier:
            bilan.publication = await self._publier()
            for ticket, suivi in a_publier:
                if bilan.publication:
                    suivi.statut, suivi.motif = "traitee", None
                    self.base.enregistrer_demande(suivi)
                    bilan.traitees.append(ticket.numero)
                    await self._repondre(ticket, suivi, bilan)
                else:
                    echec = ErreurTechnique("publication du site impossible")
                    await self._echec_technique(ticket, suivi, echec, bilan)
        return bilan

    async def _publier(self) -> bool:
        try:
            return await self.publier()
        except Exception:
            journal.exception("Publication du site impossible.")
            return False

    # ------------------------------------------------------------------ #
    # Examen d'une demande
    # ------------------------------------------------------------------ #

    async def _examiner(self, ticket: Ticket, suivi: DemandeEnregistree) -> None:
        """Valide puis analyse (ou réutilise) ; suivi passe à « a_publier ». Lève Refus."""
        if suivi.acceptee_le is None:
            hote = await self._accepter(ticket, suivi)
        else:
            assert suivi.domaine is not None  # demande déjà acceptée : domaine validé
            hote = suivi.domaine
        domaine = normaliser_cible(hote).domaine

        recent = self.base.dernier_scan_note_du_domaine(
            domaine, self.maintenant() - self.delai_reutilisation
        )
        if recent is not None and recent.organisation_id is not None:
            suivi.organisation_id = recent.organisation_id
        else:
            suivi.organisation_id = await self._analyser(hote, domaine)
        suivi.statut, suivi.motif = "a_publier", None
        self.base.enregistrer_demande(suivi)

    async def _accepter(self, ticket: Ticket, suivi: DemandeEnregistree) -> str:
        """Contrôles d'une nouvelle demande, dans l'ordre ; retourne le nom d'hôte validé."""
        if not case_cochee(ticket):
            raise Refus("case_non_cochee")
        hote = self._valider(extraire_domaine(ticket))
        suivi.domaine = hote
        await self._verifier_hote(hote)
        self._verifier_limites(ticket.auteur)
        suivi.acceptee_le = self.maintenant()
        self.base.enregistrer_demande(suivi)
        return hote

    @staticmethod
    def _valider(saisie: str | None) -> str:
        try:
            return valider_domaine(saisie)
        except DomaineRefuse as refus:
            raise Refus(refus.code) from None

    async def _verifier_hote(self, hote: str) -> None:
        """Retrait demandé, nom sans adresse ou adresse non publique : refus."""
        if self.referentiels.est_retire(hote) or self.referentiels.est_retire(
            normaliser_cible(hote).domaine
        ):
            raise Refus("retrait")
        adresses = await self.resoudre(hote)
        if not adresses:
            raise Refus("sans_adresse")
        if not all(est_adresse_publique(adresse) for adresse in adresses):
            raise Refus("reseau_prive")

    async def analyser_directement(self, saisie: str) -> AnalyseDirecte:
        """Demande reçue hors ticket (par e-mail) : mêmes contrôles de sécurité qu'un ticket,
        même réutilisation d'une analyse récente et même fiche « sur demande ». La case
        d'engagement et les limites quotidiennes relèvent de la personne qui lance la
        commande. Lève Refus ; ne publie pas le site."""
        hote = self._valider(saisie)
        await self._verifier_hote(hote)
        domaine = normaliser_cible(hote).domaine
        recent = self.base.dernier_scan_note_du_domaine(
            domaine, self.maintenant() - self.delai_reutilisation
        )
        if recent is not None and recent.organisation_id is not None:
            organisation_id, reutilisee = recent.organisation_id, True
        else:
            organisation_id, reutilisee = await self._analyser(hote, domaine), False
        enregistree = self.base.organisation_par_id(organisation_id)
        scan = self.base.dernier_scan(organisation_id)
        if enregistree is None or scan is None or scan.score is None:
            raise ErreurTechnique("fiche introuvable après l'analyse")
        score = score_a_jour(scan)
        slug = enregistree.organisation.slug
        return AnalyseDirecte(
            hote=hote,
            slug=slug,
            url_fiche=f"{self.url_site.rstrip('/')}/organisation/{slug}/",
            note=score.note,
            score=score.score_global,
            provisoire=score.provisoire,
            reutilisee=reutilisee,
        )

    def _verifier_limites(self, auteur: str) -> None:
        """1 demande acceptée par jour et par compte, 10 au total (jour calendaire, Paris)."""
        aujourd_hui = self.maintenant().astimezone(FUSEAU).date()
        debut_jour = datetime.combine(aujourd_hui, time.min, tzinfo=FUSEAU)
        acceptees = self.base.demandes_acceptees_depuis(debut_jour)
        du_compte = [d for d in acceptees if d.auteur.casefold() == auteur.casefold()]
        if len(du_compte) >= self.limite_compte:
            raise Refus("limite_compte")
        if len(acceptees) >= self.limite_jour:
            raise Refus("limite_quotidienne")

    async def _analyser(self, hote: str, domaine: str) -> int:
        """Scan passif + score (+ rapport IA) ; retourne l'identifiant de l'organisation."""
        resultat = await self.analyser(hote)
        if resultat.statut == "exclu":
            raise Refus("retrait")
        if resultat.statut == "erreur":
            raise ErreurTechnique("aucune donnée DNS n'a pu être collectée")
        try:
            score = calculer_score(resultat.constats, resultat.sondes_reussies)
        except ScoreImpossible as erreur:
            raise ErreurTechnique("aucune catégorie évaluable") from erreur
        organisation_id = self._organisation_pour(hote, domaine)
        scan_id = self.base.enregistrer_scan(organisation_id, resultat, score, VERSION_METHODO)
        if self.generer_rapport is not None:
            try:
                await self.generer_rapport(scan_id)
            except Exception:
                journal.exception("Rapport IA impossible pour le scan %s.", scan_id)
        return organisation_id

    def _organisation_pour(self, hote: str, domaine: str) -> int:
        """Organisation existante de même domaine (fiche unique), sinon fiche « sur demande »."""
        for enregistree in self.base.organisations(avec_site=True):
            if domaine_organisation(enregistree.organisation) == domaine:
                return enregistree.id
        slug = f"sur-demande-{slugifier(domaine)}"
        if self.base.organisation_par_slug(slug) is not None:
            # « a-b.fr » et « a.b.fr » donnent le même identifiant : suffixe stable et distinct
            slug = f"{slug}-{hashlib.sha256(domaine.encode()).hexdigest()[:6]}"
        return self.base.enregistrer_organisation(
            Organisation(
                slug=slug,
                nom=nom_lisible(domaine),
                type="sur_demande",
                site_web=f"https://{hote}/",
                source=self.source,
            )
        )

    # ------------------------------------------------------------------ #
    # Réponses dans les tickets
    # ------------------------------------------------------------------ #

    def _message(self, suivi: DemandeEnregistree) -> str:
        if suivi.statut == "refusee":
            return reponse_refusee(suivi.motif or "", self.url_methodologie, self.limite_jour)
        if suivi.statut == "echec":
            return reponse_erreur(suivi.tentatives, self.tentatives_max)
        assert suivi.statut == "traitee" and suivi.organisation_id is not None
        enregistree = self.base.organisation_par_id(suivi.organisation_id)
        scan = self.base.dernier_scan(suivi.organisation_id)
        if enregistree is None or scan is None or scan.score is None:
            raise ErreurTechnique("fiche introuvable après publication")
        score = score_a_jour(scan)
        return reponse_traitee(
            domaine=scan.resultat.domaine,
            note=score.note,
            score=score.score_global,
            provisoire=score.provisoire,
            url_fiche=f"{self.url_site.rstrip('/')}/organisation/{enregistree.organisation.slug}/",
            url_methodologie=self.url_methodologie,
            date_scan=scan.resultat.debut,
            reutilisee=suivi.acceptee_le is not None and scan.resultat.debut < suivi.acceptee_le,
            avec_rapport_ia=self.base.rapport_du_scan(scan.id) is not None,
        )

    async def _repondre(
        self, ticket: Ticket, suivi: DemandeEnregistree, bilan: BilanDemandes
    ) -> None:
        """Commentaire final (une seule fois), étiquette, fermeture. Retenté si la forge échoue."""
        etiquette = {
            "traitee": ETIQUETTE_TRAITEE,
            "refusee": ETIQUETTE_REFUSEE,
            "echec": ETIQUETTE_ERREUR,
        }[suivi.statut]
        try:
            if suivi.commentee_le is None:
                await self.forge.commenter(ticket.numero, self._message(suivi))
                suivi.commentee_le = self.maintenant()
                self.base.enregistrer_demande(suivi)
            await self.forge.ajouter_etiquette(ticket.numero, etiquette)
            if suivi.statut == "traitee" and suivi.tentatives:
                await self.forge.retirer_etiquette(ticket.numero, ETIQUETTE_ERREUR)
            await self.forge.fermer(ticket.numero)
        except (ErreurForge, ErreurTechnique) as erreur:
            journal.warning("Ticket #%s : réponse reportée (%s).", ticket.numero, erreur)
            bilan.reponses_en_attente.append(ticket.numero)
            return
        suivi.cloturee_le = self.maintenant()
        self.base.enregistrer_demande(suivi)

    async def _echec_technique(
        self,
        ticket: Ticket,
        suivi: DemandeEnregistree,
        erreur: BaseException,
        bilan: BilanDemandes,
    ) -> None:
        """Erreur retentée au passage suivant ; échec définitif après `tentatives_max`."""
        raison = str(erreur) or type(erreur).__name__
        journal.warning("Ticket #%s : erreur technique (%s).", ticket.numero, raison)
        suivi.tentatives += 1
        suivi.motif = "erreur_technique"
        bilan.erreurs.append((ticket.numero, raison))
        if suivi.tentatives >= self.tentatives_max:
            suivi.statut = "echec"
            self.base.enregistrer_demande(suivi)
            await self._repondre(ticket, suivi, bilan)
            return
        suivi.statut = "erreur"
        self.base.enregistrer_demande(suivi)
        try:
            if suivi.tentatives == 1:  # un seul message d'attente, pas un par tentative
                await self.forge.commenter(
                    ticket.numero, reponse_erreur(suivi.tentatives, self.tentatives_max)
                )
            await self.forge.ajouter_etiquette(ticket.numero, ETIQUETTE_ERREUR)
        except ErreurForge as erreur_forge:
            journal.warning(
                "Ticket #%s : message d'erreur non publié (%s).", ticket.numero, erreur_forge
            )
