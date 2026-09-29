"""Données de démonstration FICTIVES pour développer le site sans lancer de scan réel.

Toutes les organisations, domaines (en .example) et rapports sont inventés. Les scores sont
calculés par le vrai moteur de score à partir de constats synthétiques.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from bleublanccloud.analyse.attribution import niveau_juridiction
from bleublanccloud.analyse.score import calculer_score
from bleublanccloud.modeles import (
    Constat,
    EtapeMigration,
    InformationsComplementaires,
    Organisation,
    OrganisationExport,
    RapportIA,
    ResultatScan,
    RisqueIA,
    TypeOrganisation,
)
from bleublanccloud.referentiels import Referentiels
from bleublanccloud.stockage.base import RapportEnregistre, ScanEnregistre

DATE_DEMO = datetime(2026, 9, 27, 3, 0, tzinfo=UTC)

# Points situés à l'intérieur de chaque département de démonstration (longitude, latitude) :
# ils servent à placer un contour de commune INVENTÉ sur la carte de situation des fiches.
CENTRES_DEMO: dict[str, tuple[float, float]] = {
    "06": (7.116, 43.938), "13": (5.086, 43.543), "21": (4.773, 47.426),
    "2A": (8.987, 41.864), "31": (1.175, 43.359), "33": (-0.583, 44.839),
    "35": (-1.634, 48.151), "44": (-1.679, 47.363), "59": (3.216, 50.449),
    "63": (3.14, 45.726), "67": (7.552, 48.671), "69": (4.641, 45.871),
    "971": (-61.68, 16.159),
}  # fmt: skip


def contour_demo(nom: str, departement: str) -> list[list[list[list[float]]]]:
    """Contour FICTIF d'une commune de démonstration : polygone irrégulier d'environ 8 km de
    large, déterministe (dérivé du nom), centré sur un point du département."""
    lon0, lat0 = CENTRES_DEMO[departement]
    graine = sum(ord(c) for c in nom)
    points: list[list[float]] = []
    for rang in range(18):
        angle = 2 * math.pi * rang / 18
        rayon = 0.04 * (
            1 + 0.25 * math.sin(3 * angle + graine) + 0.12 * math.cos(5 * angle + graine / 7)
        )
        points.append([
            round(lon0 + rayon * math.cos(angle) / math.cos(math.radians(lat0)), 4),
            round(lat0 + rayon * math.sin(angle), 4),
        ])  # fmt: skip
    return [[[*points, points[0]]]]


# Noms officiels des départements utilisés par la démonstration (placement sur la carte).
DEPARTEMENTS_DEMO: dict[str, tuple[str, str]] = {
    "06": ("Alpes-Maritimes", "93"),
    "13": ("Bouches-du-Rhône", "93"),
    "21": ("Côte-d'Or", "27"),
    "2A": ("Corse-du-Sud", "94"),
    "31": ("Haute-Garonne", "76"),
    "33": ("Gironde", "75"),
    "35": ("Ille-et-Vilaine", "53"),
    "44": ("Loire-Atlantique", "52"),
    "59": ("Nord", "32"),
    "63": ("Puy-de-Dôme", "84"),
    "67": ("Bas-Rhin", "44"),
    "69": ("Rhône", "84"),
    "971": ("Guadeloupe", "01"),
}


def _hebergement(fournisseur: str, niveau: str, ip: str, cle: str = "hebergeur") -> Constat:
    return Constat(
        sonde="ip",
        categorie="hebergement",
        cle=cle,
        valeur=ip,
        fournisseur_id=fournisseur or None,
        niveau=niveau,
        preuve={"ip": ip, "attribution": {"methode": "asn"}, "demonstration": True},
    )


def _serveur(categorie: str, cle: str, hote: str, fournisseur: str | None, niveau: str) -> Constat:
    return Constat(
        sonde="dns",
        categorie=categorie,
        cle=cle,
        valeur=hote,
        fournisseur_id=fournisseur,
        niveau=niveau,
        preuve={"hote": hote, "demonstration": True},
    )


def _service(referentiels: Referentiels, regle_id: str, element: str) -> Constat:
    regle = next(r for r in referentiels.regles if r.id == regle_id)
    fournisseur = referentiels.fournisseurs.get(regle.fournisseur_id or "")
    niveau = regle.niveau or (niveau_juridiction(fournisseur) if fournisseur else "inconnu")
    return Constat(
        sonde="dns" if regle.categorie == "suites_saas" else "http",
        categorie=regle.categorie,
        cle="spf" if regle.categorie == "suites_saas" else "script_tiers",
        valeur=regle.nom,
        fournisseur_id=regle.fournisseur_id,
        niveau=niveau,
        preuve={
            "regle": regle.id,
            "type_service": regle.type_service,
            "signal_positif": regle.signal_positif,
            "correspondances": [{"type": "exemple", "motif": "demonstration", "element": element}],
            "nombre_correspondances": 1,
            "demonstration": True,
        },
    )


def _informatifs(spf: str | None, dmarc: str | None) -> list[Constat]:
    return [
        Constat(
            sonde="dns", categorie="informatif", cle="spf", valeur=spf or "Aucun enregistrement SPF"
        ),
        Constat(
            sonde="dns",
            categorie="informatif",
            cle="dmarc",
            valeur=dmarc or "Aucune politique DMARC",
        ),
    ]


@dataclass(frozen=True)
class ProfilDemo:
    nom: str
    type: TypeOrganisation
    departement: str | None
    population: int | None
    domaine: str
    constats: list[Constat]
    informations: InformationsComplementaires
    rapport: RapportIA | None = None


def _rapport_demo(
    forts: list[str], risques: list[RisqueIA], etapes: list[EtapeMigration]
) -> RapportIA:
    return RapportIA(
        resume_decideur=(
            "Ceci est un exemple de rapport fictif, affiché uniquement pour la démonstration du site. "
            "Il illustre la forme que prendra la synthèse destinée aux élus et aux directions."
        ),
        points_forts=forts,
        risques=risques,
        plan_migration=etapes,
    )


def profils(referentiels: Referentiels) -> list[ProfilDemo]:

    def s(regle: str, element: str) -> Constat:
        return _service(referentiels, regle, element)

    info = InformationsComplementaires
    return [
        ProfilDemo(
            "Commune d'Exempleville", "commune", "33", 48_200, "exempleville.example",
            [
                _hebergement("ovhcloud", "A", "198.51.100.10 (AS16276 OVH SAS)"),
                _serveur("messagerie", "mx", "mx1.mail.ovh.net", "ovhcloud", "A"),
                _serveur("messagerie", "mx", "mx2.mail.ovh.net", "ovhcloud", "A"),
                _serveur("dns", "ns", "dns110.ovh.net", "ovhcloud", "A"),
                _serveur("dns", "ns", "ns110.ovh.net", "ovhcloud", "A"),
                s("matomo-auto-heberge", "https://stats.exempleville.example/matomo.js"),
                s("tarteaucitron", "https://www.exempleville.example/js/tarteaucitron.js"),
                s("ovhcloud-messagerie", "v=spf1 include:mx.ovh.com -all"),
                *_informatifs("v=spf1 include:mx.ovh.com -all", "v=DMARC1; p=reject"),
            ],
            info(bureau_enregistrement="OVH", autorite_certification="Let's Encrypt (R11)",
                 fournisseurs_secnumcloud=["OVHcloud"]),
            _rapport_demo(
                ["Hébergement, messagerie et DNS chez un fournisseur français.",
                 "Mesure d'audience auto-hébergée (Matomo)."],
                [RisqueIA(titre="Aucun risque majeur identifié", gravite="faible",
                          explication="L'empreinte externe visible repose sur des fournisseurs européens.")],
                [EtapeMigration(ordre=1, action="Maintenir la veille sur les services ajoutés au site.",
                                alternative_id=None, effort="faible")],
            ),
        ),
        ProfilDemo(
            "Commune de Démoville", "commune", "59", 121_500, "demoville.example",
            [
                _hebergement("cloudflare", "C", "203.0.113.20", "cdn"),
                _serveur("messagerie", "mx", "demoville-example.mail.protection.outlook.com", "microsoft", "D"),
                _serveur("dns", "ns", "anna.ns.cloudflare.com", "cloudflare", "D"),
                _serveur("dns", "ns", "bob.ns.cloudflare.com", "cloudflare", "D"),
                s("microsoft-365", "MS=ms12345678"),
                s("google-analytics", "https://www.googletagmanager.com/gtag/js?id=G-DEMO"),
                s("google-tag-manager", "https://www.googletagmanager.com/gtm.js?id=GTM-DEMO"),
                s("youtube", "https://www.youtube.com/embed/demo"),
                s("google-fonts", "https://fonts.googleapis.com/css2?family=Roboto"),
                s("google-recaptcha", "https://www.google.com/recaptcha/api.js"),
                *_informatifs("v=spf1 include:spf.protection.outlook.com -all", None),
            ],
            info(bureau_enregistrement="Bureau fictif", autorite_certification="Google Trust Services (WE1)",
                 domaines_tiers_inconnus=["cdn.agence-fictive.example"]),
            _rapport_demo(
                ["Politique SPF publiée pour la messagerie."],
                [RisqueIA(titre="Messagerie soumise au Cloud Act", gravite="elevee",
                          explication="Les courriels transitent par un fournisseur américain."),
                 RisqueIA(titre="Mesure d'audience américaine", gravite="moyenne",
                          explication="Les données de navigation des habitants sont transmises à Google.")],
                [EtapeMigration(ordre=1, action="Remplacer Google Analytics par Matomo auto-hébergé.",
                                alternative_id="matomo-auto-heberge", effort="faible"),
                 EtapeMigration(ordre=2, action="Migrer la messagerie vers une offre européenne.",
                                alternative_id="bluemind", effort="eleve")],
            ),
        ),
        ProfilDemo(
            "Commune de Fictif-sur-Mer", "commune", "13", 23_400, "fictif-sur-mer.example",
            [
                _hebergement("wix", "D", "198.51.100.30 (AS58182 Wix.com)"),
                _serveur("messagerie", "mx", "aspmx.l.google.com", "google", "D"),
                _serveur("dns", "ns", "ns0.wixdns.net", "wix", "D"),
                s("google-workspace", "v=spf1 include:_spf.google.com ~all"),
                s("google-analytics", "https://www.googletagmanager.com/gtag/js?id=G-DEMO2"),
                s("meta-pixel", "https://connect.facebook.net/en_US/fbevents.js"),
                *_informatifs("v=spf1 include:_spf.google.com ~all", None),
            ],
            info(bureau_enregistrement="Bureau fictif"),
        ),
        ProfilDemo(
            "Commune de Testbourg", "commune", "67", 14_800, "testbourg.example",
            [
                _hebergement("", "inconnu", "192.0.2.40 (AS64500 PETIT HEBERGEUR)"),
                _serveur("messagerie", "mx", "spool.mail.gandi.net", "gandi", "A"),
                # DNS chez un prestataire non référencé : 35 % du poids inconnu → note provisoire
                _serveur("dns", "ns", "ns1.prestataire-fictif.example", None, "inconnu"),
                s("google-fonts", "https://fonts.googleapis.com/css2?family=Lato"),
                s("openstreetmap", "https://tile.openstreetmap.org/12/2072/1409.png"),
                *_informatifs("v=spf1 include:_mailcust.gandi.net ?all", "v=DMARC1; p=none"),
            ],
            info(bureau_enregistrement="Gandi SAS"),
        ),
        ProfilDemo(
            "Commune de Maquette-les-Bains", "commune", "63", 31_900, "maquette-les-bains.example",
            [
                _hebergement("scaleway", "A", "198.51.100.50 (AS12876 SCALEWAY S.A.S.)"),
                _serveur("messagerie", "mx", "mail.maquette-les-bains.example", "ovhcloud", "A"),
                _serveur("dns", "ns", "ns0.dom.scw.cloud", "scaleway", "A"),
                s("plausible", "https://plausible.io/js/script.js"),
                s("peertube", "https://videos.maquette-les-bains.example/videos/embed/6f1d1e2b-0000"),
                *_informatifs("v=spf1 mx -all", "v=DMARC1; p=quarantine"),
            ],
            info(bureau_enregistrement="Bureau fictif", autorite_certification="Certigna"),
        ),
        ProfilDemo(
            "Commune d'Échantillon-la-Forêt", "commune", "35", 18_700, "echantillon-la-foret.example",
            [
                _hebergement("ionos", "A", "198.51.100.60 (AS8560 IONOS SE)"),
                _serveur("messagerie", "mx", "echantillon.mail.protection.outlook.com", "microsoft", "D"),
                _serveur("dns", "ns", "ns1045.ui-dns.com", "ionos", "A"),
                s("microsoft-365", "MS=ms87654321"),
                s("google-recaptcha", "https://www.google.com/recaptcha/api.js"),
                s("axeptio", "https://static.axept.io/sdk.js"),
                *_informatifs("v=spf1 include:spf.protection.outlook.com -all", None),
            ],
            info(bureau_enregistrement="IONOS SE"),
        ),
        ProfilDemo(
            "Commune de Prototype-en-Vallée", "commune", "69", 11_200, "prototype-en-vallee.example",
            [
                _hebergement("infomaniak", "B", "198.51.100.70 (AS29222 Infomaniak)"),
                _serveur("messagerie", "mx", "mta-gw.infomaniak.ch", "infomaniak", "B"),
                _serveur("dns", "ns", "ns11.infomaniak.ch", "infomaniak", "B"),
                s("infomaniak-ksuite", "v=spf1 include:spf.infomaniak.ch -all"),
                *_informatifs("v=spf1 include:spf.infomaniak.ch -all", "v=DMARC1; p=reject"),
            ],
            info(bureau_enregistrement="Infomaniak"),
        ),
        ProfilDemo(
            "Commune de Brouillon-le-Château", "commune", "06", 67_300, "brouillon-le-chateau.example",
            [
                _hebergement("aws", "D", "198.51.100.80 (CloudFront)", "cdn"),
                _serveur("messagerie", "mx", "aspmx.l.google.com", "google", "D"),
                _serveur("dns", "ns", "ns-12.awsdns-34.org", "aws", "D"),
                s("google-workspace", "v=spf1 include:_spf.google.com ~all"),
                s("mailchimp-envoi", "v=spf1 include:servers.mcsv.net ?all"),
                s("atlassian", "atlassian-domain-verification=demo"),
                s("google-analytics", "https://www.googletagmanager.com/gtag/js?id=G-DEMO3"),
                s("hotjar", "https://static.hotjar.com/c/hotjar-demo.js"),
                s("youtube", "https://www.youtube.com/embed/demo2"),
                s("google-maps", "https://www.google.com/maps/embed?pb=demo"),
                s("onetrust", "https://cdn.cookielaw.org/scripttemplates/otSDKStub.js"),
                *_informatifs("v=spf1 include:_spf.google.com include:servers.mcsv.net ~all", None),
            ],
            info(bureau_enregistrement="Bureau fictif", autorite_certification="Amazon (RSA 2048 M02)"),
        ),
        ProfilDemo(
            "Commune d'Esquisse-sur-Loire", "commune", "44", 26_500, "esquisse-sur-loire.example",
            [
                _hebergement("o2switch", "A", "198.51.100.90 (AS50474 o2switch)"),
                _serveur("messagerie", "mx", "mail.esquisse-sur-loire.example", "o2switch", "A"),
                _serveur("dns", "ns", "lara.ns.cloudflare.com", "cloudflare", "D"),
                s("didomi", "https://sdk.privacy-center.org/demo/loader.js"),
                s("dailymotion", "https://www.dailymotion.com/embed/video/xdemo"),
                *_informatifs("v=spf1 mx -all", "v=DMARC1; p=none"),
            ],
            info(bureau_enregistrement="Bureau fictif"),
        ),
        ProfilDemo(
            "Commune de Simulacre-la-Rivière", "commune", "31", 10_400, "simulacre-la-riviere.example",
            [
                _hebergement("codeberg", "A", "198.51.100.100"),
                _serveur("dns", "ns", "ns-12-a.gandi.net", "gandi", "A"),
                Constat(sonde="dns", categorie="informatif", cle="mx_absent",
                        valeur="Aucun serveur de messagerie (MX) déclaré"),
                *_informatifs(None, None),
            ],
            info(bureau_enregistrement="Gandi SAS"),
        ),
        ProfilDemo(
            "Commune de Canevas-les-Îles", "commune", "971", 15_100, "canevas-les-iles.example",
            [
                _hebergement("orange", "A", "198.51.100.110 (AS3215 Orange)"),
                _serveur("messagerie", "mx", "canevas.mail.protection.outlook.com", "microsoft", "D"),
                _serveur("dns", "ns", "dns1.orange.example", None, "inconnu"),
                s("microsoft-365", "MS=ms11223344"),
                s("facebook-widgets", "https://www.facebook.com/plugins/page.php?href=demo"),
                *_informatifs("v=spf1 include:spf.protection.outlook.com -all", None),
            ],
            info(bureau_enregistrement="Bureau fictif"),
        ),
        ProfilDemo(
            "Commune de Gabarit-sur-Seine", "commune", "2A", 12_900, "gabarit-sur-seine.example",
            [
                _hebergement("hetzner", "A", "198.51.100.120 (AS24940 Hetzner Online)"),
                _serveur("messagerie", "mx", "mx.gabarit-sur-seine.example", "hetzner", "A"),
                _serveur("dns", "ns", "hydrogen.ns.hetzner.com", "hetzner", "A"),
                s("google-fonts", "https://fonts.googleapis.com/css2?family=Inter"),
                s("jsdelivr", "https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.js"),
                s("openstreetmap-france", "https://a.tile.openstreetmap.fr/osmfr/12/1/1.png"),
                *_informatifs("v=spf1 mx -all", "v=DMARC1; p=quarantine"),
            ],
            info(bureau_enregistrement="Bureau fictif"),
        ),
        ProfilDemo(
            "Département fictif de démonstration", "departement", "21", None,
            "departement-demo.example",
            [
                _hebergement("outscale", "A", "198.51.100.130"),
                _serveur("messagerie", "mx", "mx.departement-demo.example", "ovhcloud", "A"),
                _serveur("dns", "ns", "ns1.nameshield.net", "nameshield", "A"),
                s("microsoft-365", "MS=ms99887766"),
                s("piano-analytics", "https://tag.aticdn.net/piano-analytics.js"),
                *_informatifs("v=spf1 include:spf.protection.outlook.com mx -all", "v=DMARC1; p=reject"),
            ],
            info(bureau_enregistrement="Nameshield", fournisseurs_secnumcloud=["3DS Outscale"]),
        ),
        ProfilDemo(
            "Région fictive de démonstration", "region", "33", None, "region-demo.example",
            [
                _hebergement("akamai", "C", "198.51.100.140", "cdn"),
                _serveur("messagerie", "mx", "region-demo.mail.protection.outlook.com", "microsoft", "D"),
                _serveur("dns", "ns", "a1-64.akam.net", "akamai", "D"),
                s("microsoft-365", "MS=ms55667788"),
                s("docusign", "docusign=demo"),
                s("eulerian", "https://region.eulerian.net/ea.js"),
                s("youtube", "https://www.youtube.com/embed/demo3"),
                *_informatifs("v=spf1 include:spf.protection.outlook.com -all", "v=DMARC1; p=none"),
            ],
            info(bureau_enregistrement="Bureau fictif"),
        ),
        # Analyse sur demande (ticket Codeberg) : visible par lien et recherche, hors carte,
        # classements et statistiques de l'observatoire.
        ProfilDemo(
            "association-fictive.example", "sur_demande", None, None,
            "association-fictive.example",
            [
                _hebergement("infomaniak", "B", "198.51.100.150 (AS29222 Infomaniak Network SA)"),
                _serveur("messagerie", "mx", "mta-gw.infomaniak.ch", "infomaniak", "B"),
                _serveur("dns", "ns", "ns11.infomaniak.ch", "infomaniak", "B"),
                s("matomo-auto-heberge", "https://stats.association-fictive.example/matomo.js"),
                *_informatifs("v=spf1 include:spf.infomaniak.ch -all", "v=DMARC1; p=reject"),
            ],
            info(bureau_enregistrement="Bureau fictif"),
        ),
    ]  # fmt: skip


def slug_demo(profil: ProfilDemo) -> str:
    base = profil.domaine.removesuffix(".example")
    return f"{base}-demo"


def generer_demonstration(referentiels: Referentiels) -> list[OrganisationExport]:
    """Construit les organisations fictives (même format que l'export réel)."""
    from bleublanccloud.export.site_statique import construire_organisation

    organisations: list[OrganisationExport] = []
    noms_departements = {code: nom for code, (nom, _) in DEPARTEMENTS_DEMO.items()}
    for rang, profil in enumerate(profils(referentiels)):
        date = DATE_DEMO - timedelta(minutes=7 * rang)
        resultat = ResultatScan(
            domaine=profil.domaine,
            debut=date,
            fin=date + timedelta(seconds=14),
            statut="termine",
            sondes_reussies=["dns", "http"],
            constats=profil.constats,
            informations=profil.informations,
        )
        score = calculer_score(resultat.constats, resultat.sondes_reussies)
        scan = ScanEnregistre(
            id=rang, organisation_id=rang, resultat=resultat, version_methodo=score.version_methodo,
            score=score,
        )  # fmt: skip
        rapport = (
            RapportEnregistre(
                contenu=profil.rapport,
                modele="démonstration (texte fictif)",
                version_invite="1.0",
                cree_le=date,
            )
            if profil.rapport
            else None
        )
        organisation = Organisation(
            slug=slug_demo(profil),
            nom=profil.nom,
            type=profil.type,
            departement=profil.departement,
            region=DEPARTEMENTS_DEMO[profil.departement][1] if profil.departement else None,
            population=profil.population,
            site_web=f"https://www.{profil.domaine}/",
            source="demonstration",
        )
        organisations.append(
            construire_organisation(
                organisation,
                scan,
                referentiels,
                rapport,
                noms_departements,
                {},
                contour=(
                    contour_demo(profil.nom, profil.departement)
                    if profil.type == "commune" and profil.departement
                    else None
                ),
            )
        )
    return organisations


def noms_departements_demo() -> dict[str, tuple[str, str | None]]:
    return {code: (nom, region) for code, (nom, region) in DEPARTEMENTS_DEMO.items()}


def resume(organisations: list[OrganisationExport]) -> dict[str, Any]:
    return {o.slug: (o.score.score_global, o.score.note) for o in organisations}
