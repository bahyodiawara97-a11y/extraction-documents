"""Mesure chaque étape de la connexion à l'API pour localiser la lenteur.

Usage :  python diagnostic_reseau.py

Chaque étape est chronométrée séparément : résolution DNS, connexion TCP en IPv6,
connexion TCP en IPv4, requête HTTPS via httpx, puis appel réel à l'API.
L'étape qui prend anormalement longtemps est la coupable.
"""

import os
import socket
import time

from dotenv import load_dotenv

load_dotenv()

HOTE = "api.anthropic.com"
PORT = 443


def chrono(libelle, fonction):
    """Exécute une fonction en la chronométrant et affiche le résultat."""
    debut = time.time()
    try:
        resultat = fonction()
        duree = time.time() - debut
        marque = "LENT  <<<" if duree > 5 else "ok"
        print(f"  {libelle:<38} {duree:7.2f}s  {marque}")
        return resultat
    except Exception as exc:
        duree = time.time() - debut
        print(f"  {libelle:<38} {duree:7.2f}s  ECHEC : {type(exc).__name__}: {exc}")
        return None


print("=" * 62)
print("1. RESOLUTION DNS")
print("=" * 62)

adresses = chrono("getaddrinfo (toutes familles)", lambda: socket.getaddrinfo(HOTE, PORT))

ipv4, ipv6 = [], []
if adresses:
    for famille, _, _, _, sockaddr in adresses:
        if famille == socket.AF_INET and sockaddr[0] not in ipv4:
            ipv4.append(sockaddr[0])
        elif famille == socket.AF_INET6 and sockaddr[0] not in ipv6:
            ipv6.append(sockaddr[0])
    print(f"\n  Adresses IPv4 : {ipv4 or 'aucune'}")
    print(f"  Adresses IPv6 : {ipv6 or 'aucune'}")
    if ipv6:
        print("  -> Le systeme dispose d'adresses IPv6 : candidat probable si la suite est lente.")

print()
print("=" * 62)
print("2. CONNEXION TCP BRUTE (sans TLS)")
print("=" * 62)


def connecter(adresse, famille):
    s = socket.socket(famille, socket.SOCK_STREAM)
    s.settimeout(30)
    try:
        s.connect((adresse, PORT))
    finally:
        s.close()
    return True


if ipv6:
    chrono(f"TCP vers IPv6 {ipv6[0][:24]}", lambda: connecter(ipv6[0], socket.AF_INET6))
else:
    print("  (pas d'IPv6 a tester)")

if ipv4:
    chrono(f"TCP vers IPv4 {ipv4[0]}", lambda: connecter(ipv4[0], socket.AF_INET))

print()
print("=" * 62)
print("3. REQUETE HTTPS VIA HTTPX")
print("=" * 62)

import httpx

chrono("GET https (nouvelle connexion)", lambda: httpx.get(f"https://{HOTE}/v1/models", timeout=60))
chrono("GET https (deuxieme appel)", lambda: httpx.get(f"https://{HOTE}/v1/models", timeout=60))

print()
print("=" * 62)
print("4. APPEL REEL A L'API (SDK anthropic)")
print("=" * 62)

cle = os.getenv("ANTHROPIC_API_KEY")
if not cle:
    print("  Pas de cle dans .env, etape ignoree.")
else:
    from anthropic import Anthropic

    client = Anthropic(api_key=cle)

    def petit_appel():
        return client.messages.create(
            model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5"),
            max_tokens=10,
            messages=[{"role": "user", "content": "Reponds juste: ok"}],
        )

    chrono("premier appel", petit_appel)
    chrono("deuxieme appel", petit_appel)

print()
print("=" * 62)
print("Colle ce resultat complet dans la conversation.")
