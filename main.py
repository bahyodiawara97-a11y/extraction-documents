"""Traitement par lot en ligne de commande.

Exemples :
    python main.py data/input --type facture --sortie data/output/factures.xlsx
    python main.py data/input --type cv --format csv
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.export import vers_csv, vers_excel, vers_sqlite
from src.pipeline import traiter_lot
from src.schemas import SCHEMAS

EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".txt"}


def main() -> int:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(description="Extraction d'informations depuis des documents.")
    parser.add_argument("dossier", help="Dossier contenant les documents à traiter")
    parser.add_argument(
        "--type", choices=list(SCHEMAS), default="facture", help="Type de document (défaut: facture)"
    )
    parser.add_argument(
        "--format", choices=["excel", "csv", "sqlite"], default="excel", help="Format de sortie"
    )
    parser.add_argument("--sortie", help="Chemin du fichier de sortie")
    parser.add_argument("--modele", help="Identifiant du modèle à utiliser")
    args = parser.parse_args()

    dossier = Path(args.dossier)
    if not dossier.is_dir():
        print(f"Dossier introuvable : {dossier}", file=sys.stderr)
        return 1

    fichiers = sorted(p for p in dossier.iterdir() if p.suffix.lower() in EXTENSIONS)
    if not fichiers:
        print(f"Aucun document exploitable dans {dossier}", file=sys.stderr)
        return 1

    print(f"{len(fichiers)} document(s) à traiter, type « {args.type} »\n")
    lot = traiter_lot(list(fichiers), SCHEMAS[args.type], modele=args.modele)

    for doc in lot.documents:
        if not doc.succes:
            statut = f"ÉCHEC  — {doc.erreur}"
        elif doc.rapport and doc.rapport.necessite_revision:
            statut = f"À RELIRE — {doc.rapport.motif_revision}"
        else:
            completude = doc.rapport.taux_completude if doc.rapport else "?"
            remarque = " (voir remarques)" if doc.rapport and doc.rapport.remarques else ""
            statut = f"OK — complétude {completude}{remarque}"
        print(f"  {doc.nom_fichier:<40} {statut}")

    extensions = {"excel": ".xlsx", "csv": ".csv", "sqlite": ".db"}
    sortie = Path(
        args.sortie or f"data/output/{args.type}s_extraits{extensions[args.format]}"
    )
    ecrivains = {"excel": vers_excel, "csv": vers_csv, "sqlite": vers_sqlite}
    ecrivains[args.format](lot, sortie)

    print(
        f"\n{lot.nb_succes} extraction(s) réussie(s), {lot.nb_echecs} échec(s), "
        f"{lot.nb_a_reviser} à relire."
    )
    print(f"Résultats écrits dans {sortie}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
