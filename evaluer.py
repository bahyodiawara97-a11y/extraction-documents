"""Mesure la justesse du pipeline contre un jeu de documents annotés à la main.

Usage :
    python evaluer.py evaluation/annotations.json
    python evaluer.py mes_annotations.json --sortie evaluation/resultats.csv
    python evaluer.py evaluation/annotations.json --simuler   # sans appel API

Format du fichier d'annotations : voir evaluation/annotations.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.evaluation import agreger, comparer
from src.pipeline import traiter_document
from src.schemas import SCHEMAS


def charger_annotations(chemin: Path) -> list[dict]:
    """Lit le fichier d'annotations et vérifie sa structure avant tout appel API."""
    donnees = json.loads(chemin.read_text(encoding="utf-8"))
    entrees = donnees.get("documents", donnees if isinstance(donnees, list) else [])

    if not entrees:
        raise ValueError(f"Aucun document dans {chemin}")

    for i, entree in enumerate(entrees, 1):
        for cle in ("fichier", "type", "attendu"):
            if cle not in entree:
                raise ValueError(f"Entrée {i} : clé '{cle}' manquante")
        if entree["type"] not in SCHEMAS:
            raise ValueError(
                f"Entrée {i} : type '{entree['type']}' inconnu "
                f"(valeurs possibles : {', '.join(SCHEMAS)})"
            )
        inconnus = set(entree["attendu"]) - set(SCHEMAS[entree["type"]].model_fields)
        if inconnus:
            raise ValueError(
                f"Entrée {i} ({entree['fichier']}) : champs annotés inconnus du schéma "
                f"{entree['type']} : {', '.join(sorted(inconnus))}"
            )
    return entrees


def afficher(resultat, seuil_alerte: float = 0.9) -> None:
    """Affiche le tableau des scores, champ par champ."""
    lignes = resultat.lignes_tableau()
    if not lignes:
        print("Aucun champ évalué.")
        return

    largeur = max(len(l["champ"]) for l in lignes) + 2
    entete = (
        f"{'champ':<{largeur}}{'attendus':>9}{'justes':>8}{'faux':>6}"
        f"{'omis':>6}{'inventes':>10}{'precision':>11}{'rappel':>9}"
    )
    print("\n" + entete)
    print("-" * len(entete))

    for l in lignes:
        precision = "—" if l["precision"] is None else f"{l['precision']:.1%}"
        rappel = "—" if l["rappel"] is None else f"{l['rappel']:.1%}"
        marque = ""
        if l["precision"] is not None and l["precision"] < seuil_alerte:
            marque = "  <-- a ameliorer"
        if l["hallucinations"]:
            marque = "  <-- INVENTE"
        print(
            f"{l['champ']:<{largeur}}{l['attendus']:>9}{l['corrects']:>8}{l['incorrects']:>6}"
            f"{l['omissions']:>6}{l['hallucinations']:>10}{precision:>11}{rappel:>9}{marque}"
        )

    print("-" * len(entete))
    p, r = resultat.precision_globale, resultat.rappel_global
    print(f"Documents évalués  : {resultat.documents_evalues}")
    print(f"Précision globale  : {'—' if p is None else f'{p:.1%}'}")
    print(f"Rappel global      : {'—' if r is None else f'{r:.1%}'}")
    print(f"Hallucinations     : {resultat.hallucinations_totales}")

    if resultat.documents_en_echec:
        print(f"\nDocuments en échec : {', '.join(resultat.documents_en_echec)}")

    erreurs = [
        (s.champ, s.exemples_erreurs)
        for s in resultat.par_champ.values()
        if s.exemples_erreurs
    ]
    if erreurs:
        print("\nExemples d'erreurs :")
        for champ, exemples in erreurs:
            for exemple in exemples:
                print(f"  [{champ}] {exemple}")


def main() -> int:
    load_dotenv()

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("annotations", help="Fichier JSON des documents annotés")
    parser.add_argument("--sortie", help="Chemin d'un CSV où écrire les scores par champ")
    parser.add_argument(
        "--simuler",
        action="store_true",
        help="Vérifie le fichier d'annotations et la présence des documents, sans appeler l'API",
    )
    parser.add_argument("--modele", help="Identifiant du modèle à évaluer")
    args = parser.parse_args()

    chemin = Path(args.annotations)
    if not chemin.exists():
        print(f"Fichier introuvable : {chemin}", file=sys.stderr)
        return 1

    try:
        entrees = charger_annotations(chemin)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"Fichier d'annotations invalide : {exc}", file=sys.stderr)
        return 1

    racine = chemin.parent
    manquants = [e["fichier"] for e in entrees if not (racine / e["fichier"]).exists()]
    if manquants:
        print("Documents introuvables :", file=sys.stderr)
        for m in manquants:
            print(f"  {racine / m}", file=sys.stderr)
        return 1

    print(f"{len(entrees)} document(s) annoté(s) dans {chemin}")

    if args.simuler:
        print("Mode simulation : annotations valides, documents présents, aucun appel API.")
        for e in entrees:
            renseignes = sum(1 for v in e["attendu"].values() if v not in (None, "", []))
            print(f"  {e['fichier']:<45} type={e['type']:<9} {renseignes} champ(s) annoté(s)")
        return 0

    comparaisons = []
    champs_vus: list[str] = []
    en_echec: list[str] = []

    for i, entree in enumerate(entrees, 1):
        schema = SCHEMAS[entree["type"]]
        champs = list(schema.model_fields)
        for c in champs:
            if c not in champs_vus:
                champs_vus.append(c)

        print(f"  [{i}/{len(entrees)}] {entree['fichier']}…", flush=True)
        doc = traiter_document(racine / entree["fichier"], schema, modele=args.modele)

        if not doc.succes or doc.donnees is None:
            en_echec.append(entree["fichier"])
            print(f"      échec : {doc.erreur}")
            continue

        obtenu = doc.donnees.model_dump()
        attendu = entree["attendu"]
        comparaisons.append(
            (entree["fichier"], attendu, obtenu, comparer(attendu, obtenu, champs))
        )

    resultat = agreger(comparaisons, champs_vus)
    resultat.documents_en_echec = en_echec
    afficher(resultat)

    if args.sortie:
        import pandas as pd

        sortie = Path(args.sortie)
        sortie.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(resultat.lignes_tableau()).to_csv(sortie, index=False, encoding="utf-8-sig")
        print(f"\nScores écrits dans {sortie}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
