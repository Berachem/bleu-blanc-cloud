"""Interface en ligne de commande « bbcloud »."""

from __future__ import annotations

import typer
from rich.console import Console

from bleublanccloud import __version__

app = typer.Typer(
    help="Bleu Blanc Cloud — observatoire de la souveraineté numérique.",
    no_args_is_help=True,
)
console = Console()


@app.callback()
def principal() -> None:
    """Bleu Blanc Cloud — observatoire de la souveraineté numérique."""


@app.command()
def version() -> None:
    """Affiche la version du scanner."""
    console.print(f"bbcloud {__version__}")


if __name__ == "__main__":
    app()
