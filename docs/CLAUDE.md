# CLAUDE.md — Bleu Blanc Cloud 🇫🇷🇪🇺

> Observatoire indépendant et open source de la souveraineté numérique des organisations françaises.
> Auteur : Berachem Markria (berachem.dev) · URL : `bleublanccloud.fr` (ancienne adresse `bleublanccloud.berachem.dev`, redirigée)

---

## 0. Première action à faire

Au démarrage d'une session :
1. Lis ce fichier en entier.
2. Résume en 5 lignes ta compréhension du projet.
3. Indique la phase en cours (section 16) et propose le plan détaillé de cette phase.
4. **Attends mon feu vert** avant d'écrire du code.

---

## 1. Vision du projet

**Bleu Blanc Cloud** mesure la dépendance numérique des organisations françaises (d'abord les collectivités et services publics) vis-à-vis des fournisseurs extra-européens, en particulier ceux soumis au **Cloud Act** américain.

Pour chaque organisation, à partir de son nom de domaine, le projet :
1. Réalise une **analyse passive** de son empreinte numérique externe : hébergement du site, messagerie, DNS, suites collaboratives et SaaS, services tiers chargés par le site, mesure d'audience.
2. Calcule un **score de 0 à 100** et une **note de A à E**, avec une méthodologie publique et versionnée.
3. Génère avec **Mistral** un rapport lisible par un décideur et un **plan de migration** vers des alternatives françaises ou européennes.
4. Publie le tout sur un **site statique** avec une **carte de France**, des classements et une page par organisation.

### Différenciation par rapport à l'existant

Des outils existent déjà (cloud-souverain.org, Numericatous, NextHop, questionnaire SEAL de SUSE, Wanderer aux Pays-Bas). Bleu Blanc Cloud se distingue par :
- **Un référentiel France** : qualification SecNumCloud de l'ANSSI, fournisseurs français, contexte de la doctrine « cloud au centre ».
- **Un observatoire national en masse** : scan automatique de toutes les communes de plus de 10 000 habitants, départements, régions, puis d'autres catégories.
- **L'IA qui passe à l'action** : plan de migration concret, pas seulement un score.
- **Transparence totale** : code open source (licence EUPL-1.2), méthodologie versionnée, chaque point retiré est justifié par une preuve.

---

## 2. Règles de travail pour Claude (IMPORTANT)

### Langue et nommage
- **Tout en français** : interface, documentation, commentaires, docstrings, messages de commit, messages d'erreur.
- **Noms de variables, fonctions, classes, modules et fichiers en français**, sans accents dans le code.
  - ✅ `nom_domaine`, `calculer_score()`, `class FournisseurCloud`, `sondes/messagerie.py`
  - ❌ `domain_name`, `compute_score()`, `class CloudProvider`
  - Exceptions tolérées : mots-clés du langage, API de bibliothèques tierces, sigles techniques consacrés (`dns`, `ip`, `url`, `http`, `mx`, `asn`, `tls`, `json`).
- Commits au format Conventional Commits en français : `feat(sondes): ajout de la sonde MX`.

### Méthode
- Travailler **phase par phase** (section 16). Ne pas passer à la phase suivante tant que les critères d'acceptation ne sont pas remplis.
- À la fin de chaque phase : résumé de ce qui a été fait, commandes pour tester, commit.
- **Demander avant** : ajout d'une dépendance lourde, choix d'architecture non prévu ici, toute action irréversible (suppression, push forcé, publication).
- Préférer du code simple, typé, testé, à de l'abstraction prématurée.

### Sécurité et éthique
- **Ne jamais lancer de scan en masse sur de vrais domaines pendant le développement.** Domaines de test autorisés : `berachem.dev`, `example.org`, `example.com`. Les campagnes réelles ne se lancent que sur demande explicite.
- **Tests sans réseau** : réponses enregistrées, fixtures, mocks (`respx`).
- **Ne jamais committer de secrets** : `.env`, clé Mistral, clé de base ASN. Fournir un `.env.example`.
- Aucun test de vulnérabilité, aucune soumission de formulaire, aucune tentative d'authentification sur les sites scannés.

### Fiabilité des référentiels
- Chaque fait d'un référentiel YAML (pays du siège, maison mère, exposition au Cloud Act, offre SecNumCloud) doit avoir **au moins une URL source**.
- Tant qu'un fait n'est pas vérifié, marquer `a_verifier: true` et me le signaler. Ne jamais inventer un fait.

### Cohérence avec le sujet
- **Zéro dépendance américaine dans le produit publié** : pas de Google Fonts, pas de CDN américain, pas de Google Analytics, pas de reCAPTCHA, pas d'embed YouTube.
- Le site doit obtenir la **note A sur son propre scan** (dogfooding, vérifié en phase 7).
- **Ne pas utiliser le DSFR** (Système de design de l'État), ni la police Marianne, ni le logo Marianne, ni « gouv » dans les noms : le site ne doit **jamais** ressembler à un site officiel de l'État ou de l'Union européenne.

---

## 3. Architecture générale

```
Serveur Proxmox (domicile) — conteneur LXC Debian 12
│
├── scanner/  (Python, CLI « bbcloud »)
│   ├── 1. Import des cibles        → API Annuaire de l'administration + geo.api.gouv.fr
│   ├── 2. Sondes passives          → DNS, HTTP, TLS, RDAP, IP/ASN
│   ├── 3. Attribution              → IP / MX / NS → fournisseur → juridiction
│   ├── 4. Détection services tiers → scripts, cookies, en-têtes, TXT, SPF
│   ├── 5. Score + note             → méthodologie versionnée
│   ├── 6. Rapports IA              → API Mistral (avec cache)
│   ├── 7. Stockage                 → SQLite
│   └── 8. Export                   → fichiers JSON statiques
│
├── site/  (Astro, 100 % statique)
│   └── build → dist/
│
└── deploy/
    ├── timer systemd hebdomadaire → campagne → export → build → publication
    └── publication : git push vers le dépôt Pages (Codeberg Pages)
                      → bleublanccloud.fr
```

**Principe clé (v1)** : le site est 100 % statique. Aucun serveur exposé depuis le domicile. Les traitements tournent sur le Proxmox, seuls les fichiers générés sont publiés. Le scan à la demande est une phase optionnelle (phase 8).

---

## 4. Stack technique

### Scanner (Python)
| Besoin | Choix |
|---|---|
| Version | Python 3.12 |
| Gestion projet | `uv` + `pyproject.toml` |
| CLI | `typer` + `rich` |
| HTTP asynchrone | `httpx` (HTTP/2) |
| DNS | `dnspython` (résolveur asynchrone) |
| Parsing HTML | `selectolax` |
| IP → ASN | `maxminddb` (base locale IPinfo Lite ou GeoLite2 ASN), repli API RIPEstat |
| Modèles de données | `pydantic` v2 + `pydantic-settings` |
| Référentiels | `PyYAML` |
| Stockage | SQLite (`sqlite3` standard) + migrations SQL simples versionnées |
| Relances | `tenacity` |
| IA | SDK officiel `mistralai` |
| Qualité | `pytest`, `respx`, `ruff`, `mypy` (strict sur `analyse/` et `score`) |
| Optionnel (phase 8) | `playwright` pour les sites rendus en JavaScript |

### Site
| Besoin | Choix |
|---|---|
| Framework | Astro (sortie statique), TypeScript |
| Style | CSS maison avec variables (pas de framework CSS externe) |
| Carte | SVG des départements généré **au build** avec `d3-geo` (aucune lib cartographique côté client ; carte de situation zoomable, fond de plan IGN uniquement à la demande du visiteur, ADR-0005) |
| Interactions | JavaScript vanilla minimal (infobulles, recherche, filtres) |
| Types | Types TypeScript générés depuis les schémas JSON exportés par pydantic (`json-schema-to-typescript`) |

---

## 5. Structure du dépôt

```
bleu-blanc-cloud/
├── README.md
├── CONTRIBUTING.md
├── SECURITY.md
├── LICENSE                      # EUPL-1.2
├── .env.example
├── .claude/CLAUDE.md            # importe docs/CLAUDE.md (instructions pour Claude Code)
├── .github/
│   ├── workflows/qualite.yml    # lint + tests (scanner et site)
│   └── ISSUE_TEMPLATE/          # modèle de ticket
│
├── scanner/
│   ├── pyproject.toml
│   ├── src/bleublanccloud/
│   │   ├── __init__.py
│   │   ├── cli.py
│   │   ├── configuration.py
│   │   ├── modeles.py               # Constat, ResultatScan, Score, RapportIA…
│   │   ├── cibles/
│   │   │   ├── annuaire.py          # import API Annuaire de l'administration
│   │   │   └── communes.py          # geo.api.gouv.fr (population, département)
│   │   ├── sondes/
│   │   │   ├── dns.py               # A, AAAA, CNAME, NS, MX, TXT, CAA, DMARC
│   │   │   ├── http.py              # pages, en-têtes, cookies, ressources tierces
│   │   │   ├── tls.py               # autorité de certification
│   │   │   ├── rdap.py              # bureau d'enregistrement
│   │   │   └── ip.py                # IP → ASN → opérateur
│   │   ├── analyse/
│   │   │   ├── attribution.py       # rattache une preuve à un fournisseur
│   │   │   ├── detection.py         # applique regles_detection.yaml
│   │   │   └── score.py             # méthodologie section 9
│   │   ├── ia/
│   │   │   ├── client_mistral.py
│   │   │   └── invites.py           # prompts versionnés
│   │   ├── stockage/
│   │   │   ├── base.py
│   │   │   └── migrations/*.sql
│   │   ├── export/
│   │   │   └── site_statique.py
│   │   └── referentiels/
│   │       ├── fournisseurs.yaml
│   │       ├── regles_detection.yaml
│   │       ├── alternatives.yaml
│   │       ├── retraits.yaml        # domaines exclus sur demande
│   │       └── telechargements/     # plages IP, base ASN (non versionnés)
│   └── tests/
│       ├── fixtures/
│       └── test_*.py
│
├── site/
│   ├── package.json
│   ├── astro.config.mjs
│   ├── public/
│   │   ├── polices/                 # polices auto-hébergées
│   │   └── donnees/                 # JSON générés par l'export (non versionnés)
│   └── src/
│       ├── pages/
│       ├── composants/
│       ├── mises-en-page/
│       ├── styles/theme.css
│       ├── types/                   # types générés
│       └── donnees-demo/            # organisations fictives pour le dev
│
├── docs/
│   ├── CLAUDE.md                    # ce fichier
│   ├── methodologie.md              # publiée sur le site
│   ├── images/                      # captures du README
│   └── adr/                         # décisions d'architecture (ADR)
│
└── deploy/
    ├── bbcloud-campagne.service
    ├── bbcloud-campagne.timer
    └── publier.sh
```

---

## 6. Sources de données

| Donnée | Source | Remarque |
|---|---|---|
| Organisations publiques et leur site web | API « Annuaire de l'administration » (Service-Public / data.gouv.fr) | Vérifier l'URL exacte de l'API dans la documentation. Ne **jamais** publier les e-mails ou téléphones issus de l'annuaire. |
| Communes, population, départements, régions | `geo.api.gouv.fr` | Sert au filtrage (≥ 10 000 hab.) et à la carte. |
| Contours des départements | IGN Admin Express COG (licence Etalab 2.0) ou `france-geojson` simplifié | Vérifier la licence avant usage, simplifier la géométrie au build. |
| Plages IP des grands clouds | AWS `ip-ranges.json`, Azure Service Tags, Google `cloud.json` + `goog.json`, Cloudflare `ips-v4` / `ips-v6`, Oracle `public_ip_ranges.json` | Téléchargées par `bbcloud referentiels maj`. |
| IP → ASN → opérateur | Base locale `.mmdb` (IPinfo Lite ou GeoLite2 ASN, comptes gratuits) | Repli : API RIPEstat. |
| Bureau d'enregistrement | RDAP (bootstrap IANA `data.iana.org/rdap/dns.json`, AFNIC pour `.fr`) | Informatif en v1. |
| Offres qualifiées SecNumCloud | Liste publiée par l'ANSSI (cyber.gouv.fr) | Information affichée, voir section 9. |
| Sous-domaines | Certificate Transparency via `crt.sh` | Phase 8 uniquement (service fragile, limiter les appels). |
| Signatures des services tiers | Référentiel maison `regles_detection.yaml` | Plus fiable et maîtrisable qu'une base externe. |

---

## 7. Sondes (analyse strictement passive)

| Sonde | Ce qu'elle collecte | Constats produits |
|---|---|---|
| `dns` | A, AAAA, CNAME (chaîne complète), NS, MX, TXT, CAA, DMARC | Hébergeur DNS, messagerie, SPF (`include:` révélant les services d'envoi), jetons de vérification (`MS=`, `google-site-verification`, `atlassian-domain-verification`, etc. révélant les suites SaaS) |
| `ip` | ASN et opérateur pour chaque IP | Hébergeur réel, présence d'un CDN |
| `http` | Page d'accueil + jusqu'à 4 pages (mentions légales, contact, trouvées via liens internes) | En-têtes (`server`, `via`, `cf-ray`, `x-amz-cf-id`, `x-azure-ref`…), cookies, domaines des scripts, polices, iframes, images tierces |
| `tls` | Émetteur du certificat | Informatif |
| `rdap` | Bureau d'enregistrement | Informatif |

### Règles de politesse (obligatoires)
- User-Agent explicite : `BleuBlancCloudBot/1.0 (+https://bleublanccloud.fr/methodologie)` (construit à partir de `DOMAINE_SITE`).
- 5 pages maximum par site, 1 requête par seconde par domaine, concurrence globale plafonnée (20 par défaut, configurable).
- Délais d'expiration : 10 s. Relances limitées (2 maximum).
- Respect de `robots.txt` pour les pages HTML.
- Liste d'exclusion `retraits.yaml` respectée **avant** toute requête.

### Modèle de constat
```python
class Constat(BaseModel):
    sonde: str                  # "dns", "http"…
    categorie: str              # voir section 9
    cle: str                    # ex. "mx", "script_tiers"
    valeur: str                 # ex. "domaine-fr.mail.protection.outlook.com"
    fournisseur_id: str | None  # id dans fournisseurs.yaml, None si inconnu
    niveau: str                 # "A", "B", "C", "D" ou "inconnu" (section 9)
    preuve: dict                # élément brut qui justifie le constat
```

---

## 8. Référentiels YAML

### `fournisseurs.yaml`
```yaml
- id: ovhcloud
  nom: OVHcloud
  pays_siege: FR
  maison_mere: OVH Groupe
  pays_maison_mere: FR
  soumis_cloud_act: false
  propose_offre_secnumcloud: true
  asn: [16276]
  motifs_domaines: ["ovh.net", "ovh.com"]
  categories: [hebergement, messagerie, dns]
  sources:
    - "https://…"
  a_verifier: true
```

Liste initiale à constituer **avec sources** (toutes les entrées démarrent en `a_verifier: true`) :
- **France / UE** : OVHcloud, Scaleway, Outscale, Clever Cloud, alwaysdata, o2switch, Gandi, Ionos, Hetzner, Infomaniak (Suisse), Brevo, prestataires de messagerie français.
- **Hors UE / exposés** : AWS, Microsoft Azure et Microsoft 365, Google Cloud et Google Workspace, Cloudflare, Akamai, Fastly, Vercel, Netlify, GitHub Pages, Wix, Squarespace, WordPress.com, Shopify, Mailchimp.

### `regles_detection.yaml`
```yaml
- id: google-analytics
  nom: Google Analytics
  categorie: mesure_audience
  fournisseur_id: google
  motifs:
    domaines_scripts: ["google-analytics.com", "googletagmanager.com"]
    cookies: ["_ga", "_gid"]
- id: microsoft-365
  nom: Microsoft 365
  categorie: suites_saas
  fournisseur_id: microsoft
  motifs:
    txt: ["^MS=ms"]
    mx: ["mail.protection.outlook.com$"]
    spf: ["spf.protection.outlook.com"]
```
Viser ~80 règles couvrant : mesure d'audience, polices, vidéos, cartes, captcha, chat, bandeaux cookies, suites bureautiques, messagerie, envoi d'e-mails, CRM, formulaires. Inclure aussi les **signaux positifs** (Matomo auto-hébergé, tarteaucitron, solutions françaises).

### `alternatives.yaml`
Par catégorie, alternatives françaises ou européennes avec `id`, `nom`, `pays`, `url`, `description_courte`, `sources`. C'est la **seule** source d'alternatives autorisée pour l'IA.

---

## 9. Méthodologie de score (version 1.0)

### Niveaux de juridiction
| Niveau | Définition | Points |
|---|---|---|
| **A** | Fournisseur dont le siège **et** la maison mère sont dans l'UE, non soumis à une loi extraterritoriale | 100 |
| **B** | Fournisseur hors UE mais non soumis au Cloud Act (ex. Suisse, Royaume-Uni) | 70 |
| **C** | CDN extra-européen placé devant une origine inconnue (hébergeur réel masqué) | 40 |
| **D** | Fournisseur soumis au Cloud Act ou à une loi extraterritoriale équivalente | 0 |
| **inconnu** | Fournisseur non identifié | Exclu du calcul, poids redistribué, signalé dans le rapport |

### Catégories et pondération
| Catégorie | Poids | Calcul |
|---|---|---|
| Hébergement du site | 25 | Niveau du fournisseur de l'IP principale |
| Messagerie (MX) | 25 | Niveau du fournisseur des MX (le moins bon si plusieurs) |
| DNS (NS) | 10 | Niveau du fournisseur DNS |
| Suites collaboratives et SaaS (TXT, SPF) | 15 | 100 − 25 par service de niveau D détecté (minimum 0) |
| Services tiers chargés par le site | 15 | 100 − 20 par service de niveau D (minimum 0) |
| Mesure d'audience et cookies | 10 | 100 si aucune ou solution de niveau A, 0 si solution de niveau D |

- Bureau d'enregistrement, autorité de certification et offre SecNumCloud : **informatifs** en v1 (affichés, non notés). L'usage réel d'une offre SecNumCloud n'est pas détectable de l'extérieur : on affiche seulement « ce fournisseur propose une offre qualifiée ».
- **Note** : A ≥ 85 · B ≥ 70 · C ≥ 50 · D ≥ 30 · E < 30.
- Chaque point retiré est **justifié par un constat et sa preuve** dans le rapport.
- `version_methodo` est enregistrée avec chaque score. Toute modification des règles = nouvelle version + entrée dans `docs/methodologie.md`.
- **Limite affichée partout** : le score ne reflète que l'empreinte **externe et visible publiquement**, pas les outils internes.

---

## 10. Intelligence artificielle (Mistral)

- SDK officiel `mistralai`. Modèle configurable dans `.env` (défaut : `mistral-small-latest`, vérifier les identifiants dans la documentation Mistral). Température 0,2.
- **L'IA ne calcule jamais le score.** Elle reformule les constats et propose un plan d'action.
- Sortie **JSON validée par pydantic** :
```python
class RisqueIA(BaseModel):
    titre: str
    explication: str
    gravite: Literal["faible", "moyenne", "elevee"]

class EtapeMigration(BaseModel):
    ordre: int
    action: str
    alternative_id: str | None   # doit exister dans alternatives.yaml
    effort: Literal["faible", "moyen", "eleve"]

class RapportIA(BaseModel):
    resume_decideur: str          # 5 phrases max, sans jargon
    points_forts: list[str]
    risques: list[RisqueIA]
    plan_migration: list[EtapeMigration]
```
- Les alternatives disponibles sont fournies dans le prompt. Tout `alternative_id` inconnu → rapport rejeté et regénéré une fois, puis marqué en erreur.
- **Cache** : clé = SHA-256 des constats + version du prompt + modèle. Pas de nouvel appel si rien n'a changé.
- **Budget** : options `--max` et `--dry-run` avec estimation du nombre d'appels et du coût avant exécution.
- **Données envoyées** : uniquement les constats techniques publics. Jamais d'e-mail, de nom de personne ou de téléphone.
- **Transparence (AI Act)** : chaque texte généré est affiché avec la mention « Rédigé par une IA (Mistral) à partir des constats techniques — peut contenir des erreurs ».
- Prompts versionnés dans `ia/invites.py` (`VERSION_INVITE = "1.0"`).

---

## 11. Site web

### Pages
| Route | Contenu |
|---|---|
| `/` | Accueil : accroche, recherche, chiffres clés, carte, derniers scans |
| `/carte` | Carte des départements (score moyen) + tableau équivalent accessible |
| `/organisation/[slug]` | Page détaillée (générée au build) |
| `/classements` | Par département, par type d'organisation, filtres |
| `/methodologie` | Contenu de `docs/methodologie.md` + version |
| `/alternatives` | Alternatives françaises et européennes par catégorie |
| `/a-propos` | Qui, pourquoi, open source, limites, indépendance vis-à-vis de l'État |
| `/retrait` | Demande d'exclusion ou droit de réponse (adresse de contact) |
| `/mentions-legales` | Éditeur et hébergeur (me demander les informations à afficher) |
| `404` | Page d'erreur dans le thème |

### Page organisation
- Grand badge de note (A à E) + score sur 100 + date du scan + version de la méthodologie.
- Détail par catégorie (barres de progression).
- Liste des constats avec preuve dépliable.
- Rapport IA (avec mention de transparence).
- Alternatives proposées.
- Bouton « Signaler une erreur / demander une correction ».

### Thème visuel : aux couleurs de la France et de l'Union européenne
```css
:root {
  /* France */
  --bleu-france: #002395;
  --blanc: #FFFFFF;
  --rouge-france: #ED2939;
  /* Union européenne */
  --bleu-europe: #003399;
  --jaune-europe: #FFCC00;
  /* Neutres */
  --fond: #F5F7FB;
  --texte: #1B1F3B;
  --texte-secondaire: #4A5070;
  /* Notes */
  --note-a: #003399;  /* texte blanc */
  --note-b: #3A6BD6;  /* texte blanc */
  --note-c: #FFCC00;  /* texte foncé */
  --note-d: #F08A24;  /* texte foncé */
  --note-e: #ED2939;  /* texte blanc */
}
```
- **Bandeau tricolore** fin (bleu | blanc | rouge) en haut de chaque page.
- **Motif discret de 12 étoiles jaunes en cercle** (SVG maison) dans la zone d'accueil, en clin d'œil à l'Europe. Ne pas utiliser le drapeau européen comme logo et ne rien laisser penser d'une approbation officielle.
- **Logo** : nuage stylisé tricolore + texte « Bleu Blanc Cloud » (SVG maison, déclinaison claire et sombre).
- **Typographie** : police française **Luciole** auto-hébergée (vérifier sa licence), repli sur la pile système. Aucune police chargée depuis un service externe.
- **Mode sombre** automatique (`prefers-color-scheme`) avec les couleurs ajustées.
- **Mobile d'abord**, responsive.
- **Accessibilité** WCAG 2.1 AA / RGAA : contrastes vérifiés (le jaune n'est jamais utilisé pour du texte sur fond blanc), focus visible, textes alternatifs, carte doublée d'un tableau.
- **Ton** factuel et pédagogique, jamais accusateur : parler de « dépendance » et de « pistes », pas de « mauvais élèves ».
- **Aucune ressource externe, aucun cookie, aucun traceur.** Mesure d'audience : aucune en v1 (Matomo auto-hébergé éventuellement plus tard). Seule exception, à l'initiative du visiteur : le fond de plan IGN (Géoplateforme, établissement public français) des cartes de situation, jamais chargé par défaut et mentionné dans les mentions légales (ADR-0005).
- Performance : Lighthouse ≥ 95 sur toutes les catégories, page d'accueil < 200 Ko.

### Contrat de données entre scanner et site
Généré par `bbcloud exporter` dans `site/public/donnees/` :
- `meta.json` : date de campagne, version méthodologie, nombre d'organisations.
- `index.json` : liste légère (slug, nom, type, département, score, note, date).
- `organisations/{slug}.json` : détail complet (constats, scores par catégorie, rapport IA, alternatives).
- `departements.json` : agrégats par département.
- Schémas JSON exportés depuis pydantic → types TypeScript générés dans `site/src/types/`.

---

## 12. Stockage SQLite

```sql
organisations(id, slug, nom, type, code_commune, departement, region,
              population, site_web, source, cree_le)
scans(id, organisation_id, domaine, debut, fin, statut, version_methodo, erreurs_json)
constats(id, scan_id, sonde, categorie, cle, valeur, fournisseur_id, niveau, preuve_json)
scores(scan_id, score_global, note, detail_json)
rapports_ia(id, scan_id, empreinte_constats, modele, version_invite, contenu_json, cree_le)
retraits(domaine, date_demande, motif)
```
- Migrations SQL numérotées dans `stockage/migrations/`.
- L'historique des scans est conservé (évolution dans le temps en phase 8).

---

## 13. Interface en ligne de commande

```bash
bbcloud referentiels maj                          # plages IP, base ASN, liste SecNumCloud
bbcloud cibles importer --population-min 10000    # communes, départements, régions
bbcloud scanner berachem.dev                      # scan unitaire, affichage rich
bbcloud scanner berachem.dev --json               # sortie JSON
bbcloud campagne lancer [--limite N] [--dry-run]
bbcloud rapports generer [--max N] [--dry-run]
bbcloud exporter --vers ../site/public/donnees
bbcloud publier                                   # export + build + push Pages
```

---

## 14. Configuration (`.env.example`)

```env
MISTRAL_API_KEY=
MISTRAL_MODELE=mistral-small-latest
CHEMIN_BASE_ASN=scanner/src/bleublanccloud/referentiels/telechargements/asn.mmdb
CHEMIN_BASE_SQLITE=donnees/bleublanccloud.db
CONCURRENCE_MAX=20
DELAI_EXPIRATION_S=10
DOMAINE_SITE=bleublanccloud.fr   # URL du site, User-Agent (+https://<DOMAINE_SITE>/methodologie)
DEPOT_PAGES=
```

---

## 15. Déploiement

- **Serveur** : conteneur LXC Debian 12 sur Proxmox (2 vCPU, 2 Go RAM suffisent), avec `uv` et Node.js LTS.
- **Planification** : `bbcloud-campagne.timer` (systemd), chaque dimanche à 3 h : mise à jour des référentiels → campagne → rapports IA → export → build → publication.
- **Publication** : `deploy/publier.sh` copie `site/dist/` dans le dépôt Pages, commit, push.
- **Hébergement du site** : Codeberg Pages (git-pages, Allemagne) avec le domaine `bleublanccloud.fr` (zone DNS chez OVHcloud, DNSSEC) : apex en A/AAAA, `www` et l'ancienne adresse `bleublanccloud.berachem.dev` redirigés en 301 par un dépôt dédié (ADR-0004, `deploy/README.md` section 5). Alternative : alwaysdata (France).
- **Code source** : GitHub (visibilité) avec miroir sur Codeberg.
- **Journaux** : journald. **Sauvegarde** : `sqlite3 .backup` quotidien vers le stockage Proxmox.

---

## 16. Phases de réalisation

### Phase 0 — Socle
- Arborescence, `uv`, `ruff`, `mypy`, `pytest`, pre-commit, Astro initialisé, `LICENSE` EUPL-1.2, `.env.example`, README squelette, workflow qualité.
- ✅ `uv run pytest` et `npm run build` passent. ADR-0001 : choix d'architecture.

### Phase 1 — DNS, IP et attribution
- Sondes `dns` et `ip`, `attribution.py`, référentiel `fournisseurs.yaml` initial, commande `referentiels maj`.
- ✅ `bbcloud scanner berachem.dev` affiche hébergeur, DNS et messagerie avec leur niveau. Tests avec fixtures.

### Phase 2 — HTTP, services tiers, TLS, RDAP
- Sonde `http` avec règles de politesse, `detection.py`, `regles_detection.yaml` (~80 règles), sondes `tls` et `rdap`.
- ✅ Chaque règle a au moins un test. `robots.txt` et `retraits.yaml` respectés (testés).

### Phase 3 — Score, stockage, export
- `score.py` conforme à la section 9, `docs/methodologie.md`, SQLite + migrations, `exporter`, schémas JSON.
- ✅ Couverture ≥ 80 % sur `analyse/`. Tests de cas limites (fournisseur inconnu, CDN, plusieurs MX).

### Phase 4 — Site v1
- Thème complet (section 11), toutes les pages, page organisation, méthodologie, alternatives, avec **données de démonstration fictives** (ex. « Commune d'Exempleville »).
- ✅ Lighthouse ≥ 95, zéro requête externe (vérifié dans l'onglet réseau), mode sombre, validation accessibilité.

### Phase 5 — Cibles, campagnes, carte
- Import depuis l'API Annuaire et `geo.api.gouv.fr`, commande `campagne`, carte SVG des départements, classements.
- ✅ Campagne de test limitée à 10 organisations **après mon accord**, résultats visibles sur le site local.

### Phase 6 — Rapports IA
- Client Mistral, prompts versionnés, validation, cache, budget, affichage sur le site avec mention de transparence.
- ✅ `--dry-run` estime le coût. Aucun `alternative_id` inventé ne passe la validation (testé).

### Phase 7 — Déploiement et dogfooding
- Fichiers systemd, `publier.sh`, documentation d'installation sur Proxmox, publication sur `bleublanccloud.fr`.
- ✅ Le site obtient **A** sur son propre scan. Première campagne complète publiée après mon accord.

### Phase 8 — Évolutions optionnelles
- Scan à la demande (formulaire → file traitée par le serveur, limitation de débit).
- Sous-domaines via `crt.sh`, rendu JavaScript via Playwright.
- Badge SVG intégrable, historique et évolution des scores, API publique en lecture, nouvelles catégories (hôpitaux, universités).

---

## 17. Cadre éthique et légal

- Analyse **uniquement passive**, sur des données publiquement accessibles.
- **Droit de réponse** et **droit de retrait** via `/retrait`, traités sous 30 jours.
- Aucune donnée personnelle collectée ni publiée.
- Indépendance affichée : projet personnel, **aucun lien avec l'État ni avec l'Union européenne**.
- Score présenté comme **indicatif**, avec ses limites clairement expliquées.
- Mentions légales conformes à la loi (LCEN) : me demander les informations à afficher.

---

## 18. Définition de « terminé » pour chaque tâche

- Code typé, lisible, noms en français.
- Tests écrits et verts, lint et typage OK.
- Documentation mise à jour (README, méthodologie ou ADR si besoin).
- Commit en français au format Conventional Commits.
- Résumé de ce qui a été fait + commandes pour tester.
