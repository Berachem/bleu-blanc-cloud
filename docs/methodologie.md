---
titre: Méthodologie
version: "1.2"
date: 2026-09-29
---

# Méthodologie — version 1.2

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

- Robot identifié : `BleuBlancCloudBot/1.0 (+https://bleublanccloud.fr/methodologie)`.
- 5 pages au maximum par site, 1 requête par seconde et par domaine, délai d'attente de 10 secondes, 2 nouvelles tentatives au maximum.
- Respect du fichier `robots.txt` (RFC 9309) : une page interdite n'est jamais demandée ; si `robots.txt` est injoignable, aucune page n'est analysée.
- Aucune soumission de formulaire, aucune tentative d'authentification, aucun test de vulnérabilité.
- Seuls les **noms** des cookies sont conservés, jamais leurs valeurs. Aucune donnée personnelle n'est collectée ni publiée.
- Une organisation peut demander son **retrait** : son domaine est alors exclu **avant toute requête** (voir la page « Retrait »).

## 2. Attribution à un fournisseur

Chaque élément observé est rattaché, lorsque c'est possible, à un fournisseur de notre [référentiel public](https://github.com/Berachem/bleu-blanc-cloud/blob/main/scanner/src/bleublanccloud/referentiels/fournisseurs.yaml), dans cet ordre :

1. **nom d'hôte** (alias CNAME, serveur MX ou NS, domaine d'une ressource) comparé aux motifs connus du fournisseur ;
2. **plages IP publiées** par les grands clouds (AWS, Microsoft Azure, Google, Cloudflare, Oracle, Fastly, GitHub) ;
3. **système autonome (ASN)** de l'adresse IP ;
4. à défaut, **nom du système autonome** : un réseau dont le nom désigne un organisme public français (« Ville de… », « Métropole », « Conseil départemental », « Groupement d'intérêt public »…) est classé **auto-hébergement public**, niveau A. Cette présomption n'est appliquée que si le pays connu de l'adresse IP est la France, jamais pour une société commerciale (SA, SAS, SARL…), et elle est signalée comme telle dans la preuve. Les réseaux publics confirmés (ex. Ville de Paris, Ville et Eurométropole de Strasbourg, GIP Gigalis) sont recensés par leur ASN.

**Réseaux de transit.** Certains systèmes autonomes sont ceux de grands opérateurs de transit (Cogent, Lumen, Arelion…) qui acheminent le trafic d'autres réseaux. Une adresse IP annoncée par l'un d'eux appartient souvent à un client sans ASN propre (hébergeur régional, collectivité…) : l'hébergeur réel n'est pas connu. Ces ASN, recensés dans un [référentiel dédié](https://github.com/Berachem/bleu-blanc-cloud/blob/main/scanner/src/bleublanccloud/referentiels/transitaires.yaml), ne valent **jamais** attribution : le constat indique une **origine indéterminée** (niveau inconnu, exclu du calcul), sauf si le nom d'hôte ou une plage IP publiée désigne un fournisseur connu.

Un serveur de messagerie ou DNS qui n'est pas reconnu par son nom est résolu en adresses IP : toutes ses adresses (IPv4 puis IPv6) sont essayées jusqu'à identifier l'opérateur, et une requête DNS en échec est relancée une fois. Un serveur MX qui ne résout vers **aucune adresse** est signalé (il ne peut pas recevoir de courriel) et reste « inconnu ».

Chaque fait du référentiel (pays du siège, maison mère, exposition au Cloud Act, offre SecNumCloud) est accompagné d'au moins une source. Tant qu'un fait n'a pas été relu, il est marqué « à vérifier ».

**Mise à jour du référentiel.** Les preuves brutes de chaque constat (nom d'hôte, chaîne CNAME, adresse IP, ASN, nom du système autonome) sont conservées. Lorsqu'un fournisseur est ajouté ou corrigé, les constats déjà enregistrés sont réattribués et les scores recalculés **sans nouvelle analyse des sites** ; la page de l'organisation garde la date du scan d'origine. Un rapport IA rédigé à partir des anciens constats est retiré jusqu'à sa nouvelle rédaction. Une nouvelle règle de détection de services tiers, elle, ne s'applique qu'au scan suivant (les pages visitées ne sont pas conservées).

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

### Couverture et note provisoire

La **couverture** est la part du poids applicable qui a réellement pu être évaluée. Le poids applicable est la somme des poids des catégories, sans les catégories **sans objet** (par exemple la messagerie lorsqu'aucun MX n'est déclaré).

> Couverture = poids des catégories évaluées ÷ poids applicable

Si **plus de 30 %** du poids applicable est non évalué (fournisseur inconnu ou données indisponibles), autrement dit si la couverture est inférieure à 70 %, la note est affichée comme **provisoire**. Elle reste calculée de la même façon, mais elle repose sur trop peu d'éléments pour être considérée comme stable et pourra évoluer lorsque les fournisseurs manquants seront identifiés.

Exemples : hébergeur inconnu seul (25 %) → couverture 75 %, note définitive ; hébergeur et DNS inconnus (35 %) → couverture 65 %, note provisoire ; sans MX, hébergeur inconnu (25 sur 75) → couverture 67 %, note provisoire.

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

## 8. Analyses sur demande

Tout visiteur peut demander l'analyse d'un domaine avec le bouton « Analyser mon site », qui propose deux voies :

1. **un ticket sur Codeberg** (recommandé, automatique) : le serveur du projet n'est joignable depuis Internet par aucun port ; il relit les tickets toutes les heures via l'API de Codeberg, puis répond dans le ticket ;
2. **un e-mail**, sans compte : la demande est traitée à la main, avec **les mêmes contrôles** qu'un ticket (validation du domaine, retraits, adresses publiques uniquement) et la même fiche ; l'adresse de l'expéditeur ne sert qu'à lui répondre et n'est jamais publiée.

- **Engagement** : la demande doit concerner votre propre site ou le site d'un organisme public (case obligatoire dans le ticket, à confirmer dans l'e-mail).
- **Validation stricte** : seul un nom de domaine est accepté (ni chemin, ni port, ni adresse IP, ni nom local comme `localhost` ou `.local`) ; un domaine qui pointe vers une adresse locale ou privée est refusé. Le contenu du ticket n'est jamais exécuté : seul le domaine validé est utilisé.
- **Retraits** : un domaine qui a demandé son retrait n'est jamais analysé.
- **Limites** : 10 analyses acceptées par jour au total, une par jour et par compte Codeberg. Si le domaine a été analysé il y a moins de 7 jours, la fiche existante est réutilisée.
- **Même méthode** : analyse passive, score et rapport IA identiques à ceux de l'observatoire.
- **Hors observatoire** : ces fiches sont publiques et accessibles par leur lien et la recherche, mais **exclues de la carte, des classements et des statistiques**. Si le domaine appartient déjà à une organisation de l'observatoire, c'est sa fiche qui est mise à jour.
- **Réponse** : note, score, lien vers la fiche et rappel des limites ; en cas de refus, la raison est expliquée. Une erreur technique est retentée automatiquement (3 tentatives au maximum).

## 9. Indépendance et droit de réponse

Bleu Blanc Cloud est un projet personnel et bénévole, **sans aucun lien avec l'État ni avec l'Union européenne**, et sans rémunération des fournisseurs cités. Toute organisation peut signaler une erreur, exercer un droit de réponse ou demander son retrait (réponse sous 30 jours).

## 10. Historique des versions

| Version | Date | Modifications |
|---|---|---|
| 1.2 | 2026-09-29 | Indicateur de **couverture** : note affichée comme **provisoire** si plus de 30 % du poids applicable n'a pas pu être évalué (fournisseur inconnu ou données indisponibles) ; les catégories sans objet sont exclues de ce calcul. *Précision ultérieure, sans nouvelle version car aucun score ne change* : les adresses annoncées par un **réseau de transit** sont explicitement marquées « origine indéterminée » (elles étaient déjà classées inconnues) ; les scores peuvent être recalculés sans nouvelle analyse après une mise à jour du référentiel. |
| 1.1 | 2026-09-29 | Attribution : réseaux d'organismes publics français classés A « auto-hébergement public » (ASN recensés, ou présomption sur le nom du système autonome) ; résolution des serveurs MX et NS plus robuste (toutes les adresses IPv4 et IPv6, nouvelle tentative en cas d'échec DNS, signalement des MX sans adresse) ; 15 fournisseurs ajoutés au référentiel après la première campagne de test. Les règles de calcul du score sont inchangées. |
| 1.0 | 2026-09-29 | Première version publique. Précisions : catégorie messagerie sans objet en l'absence de MX ; catégories web non évaluables si le site n'a pas pu être analysé ; niveau C plafonnant l'hébergement derrière un CDN extra-européen ; mesure d'audience B = 70, C = 40. |

Toute modification des règles de calcul donne lieu à une nouvelle version, enregistrée avec chaque score.
