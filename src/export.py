"""Étape 4 du pipeline : sortir les données vers un format exploitable."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from .pipeline import ResultatLot


def vers_dataframe(lot: ResultatLot) -> pd.DataFrame:
    """Convertit un lot traité en DataFrame, colonnes de contrôle en fin de tableau."""
    df = pd.DataFrame(lot.en_lignes())
    if df.empty:
        return df

    colonnes_controle = [
        "score_confiance",
        "necessite_revision",
        "alertes",
        "champs_manquants",
        "methode_extraction",
        "nb_pages",
        "duree_s",
        "erreur",
    ]
    metier = [c for c in df.columns if c not in colonnes_controle]
    controle = [c for c in colonnes_controle if c in df.columns]
    return df[metier + controle]


def vers_csv(lot: ResultatLot, chemin: str | Path) -> Path:
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig pour qu'Excel affiche correctement les accents.
    vers_dataframe(lot).to_csv(chemin, index=False, encoding="utf-8-sig")
    return chemin


def vers_excel(lot: ResultatLot, chemin: str | Path) -> Path:
    """Écrit deux onglets : les données, et les documents à relire."""
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    df = vers_dataframe(lot)

    with pd.ExcelWriter(chemin, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Donnees", index=False)
        if "necessite_revision" in df.columns:
            a_reviser = df[df["necessite_revision"] == True]  # noqa: E712
            if not a_reviser.empty:
                a_reviser.to_excel(writer, sheet_name="A_reviser", index=False)
    return chemin


def vers_sqlite(lot: ResultatLot, chemin: str | Path, table: str = "documents") -> Path:
    """Ajoute les lignes à une base SQLite (créée si absente)."""
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    df = vers_dataframe(lot)
    with sqlite3.connect(chemin) as conn:
        df.to_sql(table, conn, if_exists="append", index=False)
    return chemin
