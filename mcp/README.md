# Serveur MCP Bleu Blanc Cloud

Serveur [MCP](https://modelcontextprotocol.io) **en lecture seule** : il permet à un assistant
IA (Claude, Le Chat, Cursor…) d'interroger l'observatoire
[Bleu Blanc Cloud](https://bleublanccloud.fr) — souveraineté numérique des collectivités
françaises — à partir des données publiées sur le site.

- Aucune analyse n'est lancée : seuls les fichiers publics du site sont lus (cache d'une heure).
- Aucun serveur à héberger : le programme tourne sur votre ordinateur (transport stdio).
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

## Développement

```bash
uv sync
uv run pytest            # tests sans réseau
uv run ruff check . && uv run mypy
BLEUBLANCCLOUD_URL=http://localhost:4321 uv run bleublanccloud-mcp   # site local
```
