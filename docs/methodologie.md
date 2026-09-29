---
titre: Méthodologie
version: "1.0"
date: 2026-09-29
---

# Méthodologie — version 1.0

Bleu Blanc Cloud mesure la **dépendance numérique externe** des organisations publiques françaises vis-à-vis de fournisseurs extra-européens, en particulier ceux soumis au **Cloud Act** américain ou à une loi extraterritoriale équivalente.

Cette page décrit précisément comment chaque score est calculé. Le code est [open source](https://github.com/Berachem/bleu-blanc-cloud) : chacun peut vérifier, reproduire et contester un résultat.

> **Limite essentielle.** Le score ne reflète que l'empreinte **externe et visible publiquement** d'une organisation (son site web, ses enregistrements DNS). Il ne dit rien de ses outils internes, de ses contrats, ni de la localisation effective des données. Il est **indicatif**.

## 1. Ce que nous analysons

L'analyse part du **nom de domaine** du site officiel de l'organisation. Elle est **strictement passive** : nous consultons uniquement ce que n'importe quel visiteur ou n'importe quel serveur de messagerie peut voir.

| Source | Ce qui est collecté |
|---|---|
| DNS | Adresses IP du site, chaîne d'alias (CNAME), serveurs DNS (NS), serveurs de messagerie (MX), enregistrements TXT (dont SPF), politique DMARC |
| Adresses IP | Opérateur du réseau (numéro de système autonome, ASN) et appartenance aux plages publiées par les grands clouds |
| Site web | Page d'accueil et jusqu'à 4 pages internes (mentions légales, contact, données personnelles, accessibilité, plan du site) : en-têtes HTTP, noms des cookies déposés par le serveur, ressources chargées (scripts, polices, vidéos, cartes, images…) |
| Certificat TLS | Autorité de certification (information affichée, non notée) |
| Registre du domaine (RDAP) | Bureau d'enregistrement (information affichée, non notée) |

### Règles de politesse

- Robot identifié : `BleuBlancCloudBot/1.0 (+https://bleublanccloud.berachem.dev/methodologie)`.
- 5 pages au maximum par site, 1 requête par seconde et par domaine, délai d'attente de 10 secondes, 2 nouvelles tentatives au maximum.
- Respect du fichier `robots.txt` (RFC 9309) : une page interdite n'est jamais demandée ; si `robots.txt` est injoignable, aucune page n'est analysée.
- Aucune soumission de formulaire, aucune tentative d'authentification, aucun test de vulnérabilité.
- Seuls les **noms** des cookies sont conservés, jamais leurs valeurs. Aucune donnée personnelle n'est collectée ni publiée.
- Une organisation peut demander son **retrait** : son domaine est alors exclu **avant toute requête** (voir la page « Retrait »).

## 2. Attribution à un fournisseur

Chaque élément observé est rattaché, lorsque c'est possible, à un fournisseur de notre [référentiel public](https://github.com/Berachem/bleu-blanc-cloud/blob/main/scanner/src/bleublanccloud/referentiels/fournisseurs.yaml), dans cet ordre :

1. **nom d'hôte** (alias CNAME, serveur MX ou NS, domaine d'une ressource) comparé aux motifs connus du fournisseur ;
2. **plages IP publiées** par les grands clouds (AWS, Microsoft Azure, Google, Cloudflare, Oracle, Fastly, GitHub) ;
3. **système autonome (ASN)** de l'adresse IP.

Chaque fait du référentiel (pays du siège, maison mère, exposition au Cloud Act, offre SecNumCloud) est accompagné d'au moins une source. Tant qu'un fait n'a pas été relu, il est marqué « à vérifier ».

## 3. Niveaux de juridiction

| Niveau | Définition | Points |
|---|---|---|
| **A** | Fournisseur dont le siège **et** la maison mère sont dans l'Union européenne, non soumis à une loi extraterritoriale | 100 |
| **B** | Fournisseur hors UE mais non soumis au Cloud Act (ex. Suisse, Royaume-Uni) | 70 |
| **C** | CDN extra-européen placé devant une origine inconnue (hébergeur réel masqué) | 40 |
| **D** | Fournisseur soumis au Cloud Act ou à une loi extraterritoriale équivalente | 0 |
| **inconnu** | Fournisseur non identifié | Exclu du calcul, poids redistribué, signalé |

Précisions :

- Un fournisseur dont le siège est dans l'UE mais dont la **maison mère** est américaine est classé **D**.
- **Niveau C** : un réseau de diffusion de contenu (CDN) extra-européen masque l'hébergeur réel. Si des en-têtes HTTP révèlent l'origine, le niveau retenu est le moins bon entre celui de l'origine et C : un CDN extra-européen plafonne toujours l'hébergement à C (par exemple, une origine chez AWS derrière CloudFront reste D ; une origine française derrière Cloudflare est C).
- Un CDN **européen** n'est pas plafonné : son propre niveau s'applique.
- Les pays de l'Espace économique européen hors UE (Norvège, Islande, Liechtenstein) sont traités comme hors UE.

## 4. Catégories et pondération

| Catégorie | Poids | Calcul |
|---|---|---|
| Hébergement du site | 25 | Niveau du fournisseur de l'adresse IP principale du site (après redirections) |
| Messagerie (MX) | 25 | Niveau du fournisseur des serveurs MX (le moins bon si plusieurs) |
| DNS (NS) | 10 | Niveau du fournisseur des serveurs DNS (le moins bon si plusieurs) |
| Suites collaboratives et SaaS | 15 | 100 − 25 par service de niveau D détecté (minimum 0) |
| Services tiers chargés par le site | 15 | 100 − 20 par service de niveau D détecté (minimum 0) |
| Mesure d'audience et cookies | 10 | 100 si aucune solution ou solution de niveau A ; sinon points du moins bon niveau détecté (B : 70, C : 40, D : 0) |

**Score global** : moyenne pondérée des catégories **évaluables**, arrondie à l'entier le plus proche (0,5 arrondi au-dessus).

**Note** : A ≥ 85 · B ≥ 70 · C ≥ 50 · D ≥ 30 · E < 30.

### Catégories non évaluables

Une catégorie est exclue du calcul, et son poids redistribué proportionnellement entre les autres, lorsque :

- tous les fournisseurs concernés sont **inconnus** du référentiel ;
- le domaine ne déclare **aucun serveur de messagerie** (MX absent ou « MX nul », RFC 7505) : la catégorie messagerie est alors sans objet ;
- les données nécessaires sont **indisponibles** (site injoignable ou `robots.txt` interdisant l'analyse : les catégories « services tiers » et « mesure d'audience » ne sont pas évaluées plutôt que de recevoir 100 par défaut).

Lorsque plusieurs serveurs MX ou NS existent, les serveurs non identifiés sont ignorés et le moins bon niveau parmi les serveurs identifiés est retenu.

### Détection des services

Les services tiers, suites SaaS et outils de mesure d'audience sont détectés par un [référentiel de règles](https://github.com/Berachem/bleu-blanc-cloud/blob/main/scanner/src/bleublanccloud/referentiels/regles_detection.yaml) (domaines des scripts et ressources, noms de cookies, enregistrements TXT et SPF, serveurs MX, extraits de code). Chaque service n'est compté qu'une seule fois. Les ressources tierces qui ne correspondent à aucune règle mais proviennent d'un fournisseur connu sont regroupées en un service par fournisseur ; les ressources de la plateforme qui héberge le site lui-même ne sont pas comptées comme des services tiers.

Une vérification de propriété de domaine (par exemple `google-site-verification`) n'est **pas** considérée comme l'usage d'une suite bureautique : elle est affichée à titre informatif.

Les solutions françaises, européennes ou auto-hébergées (Matomo auto-hébergé, tarteaucitron.js, PeerTube…) sont mises en avant comme **signaux positifs**.

## 5. Informations affichées mais non notées (v1)

- **Bureau d'enregistrement** du domaine et **autorité de certification** du site.
- **Offre qualifiée SecNumCloud** : l'usage réel d'une offre qualifiée par l'ANSSI n'est pas détectable de l'extérieur. Nous indiquons seulement que « ce fournisseur propose une offre qualifiée ».
- SPF et DMARC (bonnes pratiques de sécurité de la messagerie).

## 6. Justification des points retirés

Chaque point retiré est rattaché à un **constat** et à sa **preuve** (enregistrement DNS, URL d'une ressource, en-tête HTTP…), affichés sur la page de l'organisation.

## 7. Rapports rédigés par l'IA

Pour chaque organisation, un rapport lisible par un décideur et un plan de migration sont rédigés par une IA (**Mistral**, entreprise française) **à partir des seuls constats techniques publics**.

- L'IA **ne calcule jamais le score**.
- Les alternatives proposées proviennent **exclusivement** de notre [référentiel d'alternatives](https://github.com/Berachem/bleu-blanc-cloud/blob/main/scanner/src/bleublanccloud/referentiels/alternatives.yaml) : tout rapport citant une alternative inconnue est rejeté.
- Aucun nom de personne, adresse e-mail ou numéro de téléphone n'est transmis.
- Chaque texte généré porte la mention : « Rédigé par une IA (Mistral) à partir des constats techniques — peut contenir des erreurs ».

## 8. Indépendance et droit de réponse

Bleu Blanc Cloud est un projet personnel et bénévole, **sans aucun lien avec l'État ni avec l'Union européenne**, et sans rémunération des fournisseurs cités. Toute organisation peut signaler une erreur, exercer un droit de réponse ou demander son retrait (réponse sous 30 jours).

## 9. Historique des versions

| Version | Date | Modifications |
|---|---|---|
| 1.0 | 2026-09-29 | Première version publique. Précisions : catégorie messagerie sans objet en l'absence de MX ; catégories web non évaluables si le site n'a pas pu être analysé ; niveau C plafonnant l'hébergement derrière un CDN extra-européen ; mesure d'audience B = 70, C = 40. |

Toute modification des règles de calcul donne lieu à une nouvelle version, enregistrée avec chaque score.
