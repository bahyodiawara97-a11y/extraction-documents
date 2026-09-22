"""Fige les résultats du pipeline sur le jeu d'évaluation, pour le mode démonstration.

À relancer après toute modification du pipeline, pour que la démonstration publique
reste le reflet du code actuel :

    python evaluation/generer_demo.py

Coûte un appel API par document (davantage pour les documents longs, découpés en
blocs). Écrit `evaluation/demo.json`, lu par `src/demo.py`.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import os  # noqa: E402

from dotenv import load_dotenv  # noqa: E402

from src.evaluation import agreger, comparer  # noqa: E402
from src.pipeline import traiter_document  # noqa: E402
from src.schemas import SCHEMAS  # noqa: E402

RACINE = Path(__file__).resolve().parent
ANNOTATIONS = RACINE / "annotations.json"
SORTIE = RACINE / "demo.json"


def main() -> int:
    load_dotenv()

    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY absente : ce script exécute le vrai pipeline.", file=sys.stderr)
        return 1

    annotations = json.loads(ANNOTATIONS.read_text(encoding="utf-8"))["documents"]
    print(f"{len(annotations)} document(s) à traiter.\n")

    documents = []
    comparaisons = []
    champs_vus: list[str] = []

    for i, entree in enumerate(annotations, 1):
        schema = SCHEMAS[entree["type"]]
        for champ in schema.model_fields:
            if champ not in champs_vus:
                champs_vus.append(champ)

        nom = Path(entree["fichier"]).name
        print(f"  [{i}/{len(annotations)}] {nom}…", flush=True)
        doc = traiter_document(RACINE / entree["fichier"], schema)

        enregistrement = {
            "fichier": nom,
            "type": entree["type"],
            "commentaire": entree.get("commentaire", ""),
            "succes": doc.succes,
            "methode_extraction": doc.methode_extraction,
            "nb_pages": doc.nb_pages,
            "duree_s": round(doc.duree_secondes, 2),
        }

        if doc.succes and doc.donnees is not None:
            obtenu = doc.donnees.model_dump()
            enregistrement["donnees"] = obtenu
            enregistrement["rapport"] = {
                "taux_completude": doc.rapport.taux_completude,
                "controles_echoues": doc.rapport.controles_echoues,
                "champs_critiques_manquants": doc.rapport.champs_critiques_manquants,
                "remarques": doc.rapport.remarques,
            }
            comparaisons.append(
                (
                    nom,
                    entree["attendu"],
                    obtenu,
                    comparer(entree["attendu"], obtenu, list(schema.model_fields)),
                )
            )
        else:
            enregistrement["erreur"] = doc.erreur
            print(f"      échec : {doc.erreur}")

        documents.append(enregistrement)

    resultat = agreger(comparaisons, champs_vus)

    contenu = {
        "_lisez_moi": (
            "Résultats figés du pipeline sur le jeu d'évaluation, rejoués par le mode "
            "démonstration de l'application sans aucun appel API. Généré par "
            "evaluation/generer_demo.py — ne pas modifier à la main."
        ),
        "genere_le": date.today().isoformat(),
        "modele": os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5"),
        "scores": {
            "documents": resultat.documents_evalues,
            "precision_globale": resultat.precision_globale,
            "rappel_global": resultat.rappel_global,
            "hallucinations": resultat.hallucinations_totales,
            "par_champ": resultat.lignes_tableau(),
        },
        "documents": documents,
    }

    SORTIE.write_text(json.dumps(contenu, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    p = resultat.precision_globale
    print(f"\nPrécision globale : {'—' if p is None else f'{p:.1%}'}")
    print(f"Hallucinations    : {resultat.hallucinations_totales}")
    print(f"Écrit dans {SORTIE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
