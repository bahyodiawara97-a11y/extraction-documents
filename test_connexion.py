"""Vérifie que la clé API fonctionne et liste les modèles disponibles.

Usage :  python test_connexion.py
"""

import os
import sys

from dotenv import load_dotenv

load_dotenv()

cle = os.getenv("ANTHROPIC_API_KEY")

print("=" * 55)
if not cle:
    print("ÉCHEC : aucune clé trouvée dans le fichier .env")
    sys.exit(1)

print(f"Clé détectée : {cle[:14]}...{cle[-4:]}  ({len(cle)} caractères)")

try:
    from anthropic import Anthropic

    client = Anthropic(api_key=cle)
    modeles = client.models.list(limit=20).data
except Exception as exc:
    print(f"ÉCHEC de connexion : {type(exc).__name__}")
    print(f"  {exc}")
    print("\nSi le message parle d'authentication_error, la clé est incorrecte.")
    print("Relance la commande de saisie de la clé et recolle-la.")
    sys.exit(1)

print(f"\nConnexion réussie. {len(modeles)} modèle(s) disponible(s) :\n")
for m in modeles:
    print(f"  {m.id:<40} {m.display_name}")

print("=" * 55)
print("\nCopie cette liste et colle-la dans la conversation.")
