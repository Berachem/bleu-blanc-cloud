# Serveur MCP Bleu Blanc Cloud

Serveur [MCP](https://modelcontextprotocol.io) **en lecture seule** : il permet à un assistant
IA (Claude, Le Chat, Cursor…) d'interroger l'observatoire
[Bleu Blanc Cloud](https://bleublanccloud.fr) — souveraineté numérique des collectivités
françaises — à partir des données publiées sur le site.

- Aucune analyse n'est lancée : seuls les fichiers publics du site sont lus (cache d'une heure).
- En local (transport stdio, rien à héberger) ou en ligne (HTTP, hébergé en France chez
  alwaysdata) pour Le Chat et claude.ai.
- Données sous Licence Ouverte 2.0 ; chaque réponse renvoie vers la fiche et ses preuves.

## Installation

Prérequis : [uv](https://docs.astral.sh/uv/). Configuration à ajouter dans votre client MCP :

```json
{
  "mcpServers": {
    "bleu-blanc-cloud": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://codeberg.org/berachem/bleu-blanc-cloud#subdirectory=mcp",
        "bleublanccloud-mcp"
      ]
    }
  }
}
```

- **Claude Desktop** : Réglages → Développeur → Modifier la configuration
  (`claude_desktop_config.json`), puis redémarrer.
- **Claude Code** : `claude mcp add bleu-blanc-cloud -- uvx --from "git+https://codeberg.org/berachem/bleu-blanc-cloud#subdirectory=mcp" bleublanccloud-mcp`
- **Cursor** : `~/.cursor/mcp.json` (même contenu).

### En ligne (Le Chat, claude.ai)

Sans rien installer : ajoutez un **connecteur MCP personnalisé** avec l'adresse
`https://bleublancloud.alwaysdata.net/mcp` (sans authentification).

- **Le Chat (Mistral)** : Connecteurs → Ajouter un connecteur → MCP personnalisé.
- **claude.ai** : Paramètres → Connecteurs → Ajouter un connecteur personnalisé.

## Outils

| Outil | Rôle |
|---|---|
| `rechercher_collectivite` | trouve une collectivité par nom, code INSEE, domaine ou département |
| `fiche_collectivite` | score, note, catégories, fournisseurs et juridictions, constats, évolution, pistes |
| `classement` | classement filtré par département, type et note |
| `comparer` | compare 2 à 6 collectivités |
| `statistiques` | chiffres clés, France entière ou par département |
| `collectivites_par_fournisseur` | collectivités qui utilisent un fournisseur (ex. messagerie Microsoft) |
| `alternatives` | pistes françaises et européennes du référentiel |

Ressource : `bleublanccloud://methodologie` (méthodologie du score). Prompt :
« Analyser ma collectivité ».

Exemples de questions : « Quelle est la note de Lyon et pourquoi ? », « Quelles communes de
Gironde ont leur messagerie chez Microsoft ? », « Compare Nantes, Rennes et Brest ».

## Limites

Le score est **indicatif** : il ne reflète que l'empreinte externe et visible publiquement,
pas les outils internes ni la sécurité. Bleu Blanc Cloud est un projet personnel, open source
et indépendant, sans lien avec l'État. Méthodologie : https://bleublanccloud.fr/methodologie/

## Hébergement du mode en ligne (alwaysdata)

Le mode en ligne (`bleublanccloud-mcp-http`) sert le même serveur en HTTP « streamable »,
sans état, sur le chemin `/mcp`. Protections : noms d'hôte autorisés
(`MCP_HOTES_AUTORISES`), limite de requêtes par IP (`MCP_REQUETES_PAR_MINUTE`, 60 par défaut,
10 fois plus au total), lecture seule des données publiques.

Installation sur un compte alwaysdata (une fois), en SSH :

```bash
git clone https://codeberg.org/berachem/bleu-blanc-cloud.git ~/bleu-blanc-cloud
python3 -m venv ~/mcp-env
~/mcp-env/bin/pip install --upgrade pip
~/mcp-env/bin/pip install ~/bleu-blanc-cloud/mcp
```

Site (Web → Sites) : type **Programme utilisateur**, commande
`/home/<compte>/mcp-env/bin/bleublanccloud-mcp-http`, répertoire de travail `/home/<compte>`,
variable d'environnement `MCP_HOTES_AUTORISES=<adresse du site>`. La plateforme fournit le
port (`PORT`) ; le serveur écoute en IPv6 (`::`).

Mise à jour :

```bash
cd ~/bleu-blanc-cloud && git pull && ~/mcp-env/bin/pip install --upgrade ./mcp
```

puis redémarrer le site depuis l'interface alwaysdata.

## Développement

```bash
uv sync
uv run pytest            # tests sans réseau
uv run ruff check . && uv run mypy
BLEUBLANCCLOUD_URL=http://localhost:4321 uv run bleublanccloud-mcp   # site local
```
