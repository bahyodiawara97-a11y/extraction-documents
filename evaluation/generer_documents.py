"""Génère un jeu d'évaluation de factures FICTIVES, varié et délibérément imparfait.

Principe : une même structure de données sert à la fois à dessiner le document et à
produire son annotation. Les deux ne peuvent donc pas diverger — la vérité terrain
n'est pas recopiée à la main, elle est la source du document.

Chaque document cible une difficulté précise, notée dans son commentaire.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

SORTIE = Path("/home/claude/extraction-documents/evaluation/documents")
SORTIE.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Les documents. Chaque entrée porte à la fois son rendu et sa vérité terrain.
# `attendu` est ce qu'un humain lirait sur le document : None signifie « l'information
# n'y figure pas », jamais « on pourrait la déduire ».
# ---------------------------------------------------------------------------

DOCUMENTS = [
    {
        "fichier": "facture_004_exoneree.pdf",
        "difficulte": "Prestation exonérée de TVA (article 261-4-4 CGI) : ni HT ni TVA affichés, seul un montant total. Piège à hallucination.",
        "titre": "FACTURE",
        "langue": "fr",
        "emetteur": {
            "nom": "CABINET FORMATION MODELE",
            "adresse": ["14 rue de l'Exemple", "31000 Toulouse"],
            "mentions": ["SIRET 000 000 000 00000", "TVA non applicable, art. 261-4-4 du CGI"],
        },
        "destinataire": {"nom": "SOCIETE FICTIVE SARL", "adresse": ["2 rue du Test", "44000 Nantes"]},
        "references": [("Facture n°", "F-2026-0031"), ("Date", "05/04/2026")],
        "lignes": [
            ("Formation « Rédaction professionnelle » - 2 jours", "2", "600,00", "1 200,00"),
            ("Support pédagogique imprimé", "12", "15,00", "180,00"),
        ],
        "totaux": [("Total", "1 380,00 EUR", True)],
        "pied": ["Exonération de TVA - article 261-4-4 du Code général des impôts.",
                 "Réglement à réception."],
        "attendu": {
            "numero_facture": "F-2026-0031",
            "date_emission": "2026-04-05",
            "date_echeance": None,
            "nom_fournisseur": "CABINET FORMATION MODELE",
            "nom_client": "SOCIETE FICTIVE SARL",
            "montant_ht": None,
            "montant_tva": None,
            "montant_ttc": 1380.0,
            "devise": "EUR",
        },
    },
    {
        "fichier": "facture_005_comptant.pdf",
        "difficulte": "Paiement comptant : aucune date d'échéance sur le document. Le modèle pourrait la déduire de la date d'émission.",
        "titre": "FACTURE",
        "langue": "fr",
        "emetteur": {
            "nom": "QUINCAILLERIE DU MODELE",
            "adresse": ["7 place Imaginaire", "59000 Lille"],
            "mentions": ["SIRET 000 000 000 00000", "TVA intracom. FR00000000000"],
        },
        "destinataire": {"nom": "ATELIER DEMO EURL", "adresse": ["18 avenue Fictive", "59100 Roubaix"]},
        "references": [("Facture n°", "QM-88214"), ("Date", "17/01/2026"),
                       ("Règlement", "Comptant - payé en espèces")],
        "lignes": [
            ("Visserie inox M6 (boîte de 200)", "3", "24,90", "74,70"),
            ("Perceuse filaire 750 W", "1", "89,00", "89,00"),
            ("Jeu de forets HSS 19 pièces", "2", "31,50", "63,00"),
        ],
        "totaux": [("Total HT", "226,70 EUR", False), ("TVA 20 %", "45,34 EUR", False),
                   ("Total TTC", "272,04 EUR", True)],
        "pied": ["Facture acquittée. Aucun échelonnement."],
        "attendu": {
            "numero_facture": "QM-88214",
            "date_emission": "2026-01-17",
            "date_echeance": None,
            "nom_fournisseur": "QUINCAILLERIE DU MODELE",
            "nom_client": "ATELIER DEMO EURL",
            "montant_ht": 226.70,
            "montant_tva": 45.34,
            "montant_ttc": 272.04,
            "devise": "EUR",
        },
    },
    {
        "fichier": "facture_006_remise.pdf",
        "difficulte": "Remise commerciale : deux sous-totaux HT (brut puis net). Le bon montant HT est le net, plus bas dans le tableau.",
        "titre": "FACTURE",
        "langue": "fr",
        "emetteur": {
            "nom": "GROSSISTE EXEMPLE SAS",
            "adresse": ["45 boulevard Fictif", "67000 Strasbourg"],
            "mentions": ["SIRET 000 000 000 00000"],
        },
        "destinataire": {"nom": "BOUTIQUE MODELE", "adresse": ["9 rue du Demo", "68100 Mulhouse"]},
        "references": [("Facture n°", "2026/0447"), ("Date", "22/05/2026"),
                       ("Échéance", "21/06/2026")],
        "lignes": [
            ("Cartons d'emballage 40x30x30 (lot de 50)", "20", "42,00", "840,00"),
            ("Ruban adhésif renforcé (lot de 36)", "10", "56,00", "560,00"),
        ],
        "totaux": [
            ("Sous-total HT brut", "1 400,00 EUR", False),
            ("Remise commerciale 15 %", "- 210,00 EUR", False),
            ("Total HT net", "1 190,00 EUR", False),
            ("TVA 20 %", "238,00 EUR", False),
            ("Total TTC", "1 428,00 EUR", True),
        ],
        "pied": ["Remise accordée au titre du volume annuel.", "Paiement à 30 jours."],
        "attendu": {
            "numero_facture": "2026/0447",
            "date_emission": "2026-05-22",
            "date_echeance": "2026-06-21",
            "nom_fournisseur": "GROSSISTE EXEMPLE SAS",
            "nom_client": "BOUTIQUE MODELE",
            "montant_ht": 1190.0,
            "montant_tva": 238.0,
            "montant_ttc": 1428.0,
            "devise": "EUR",
        },
    },
    {
        "fichier": "facture_007_anglais_usd.pdf",
        "difficulte": "Document en anglais, devise USD, dates au format américain (MM/DD/YYYY). Le schéma et le prompt sont en français.",
        "titre": "INVOICE",
        "langue": "en",
        "emetteur": {
            "nom": "SAMPLE SOFTWARE INC.",
            "adresse": ["500 Fictional Avenue", "Austin, TX 78701, USA"],
            "mentions": ["EIN 00-0000000"],
        },
        "destinataire": {"nom": "DEMO STUDIO LLC", "adresse": ["21 Placeholder St", "Denver, CO 80202, USA"]},
        "references": [("Invoice No.", "INV-2026-1188"), ("Issue date", "03/09/2026"),
                       ("Due date", "04/08/2026")],
        "lignes": [
            ("Annual platform licence - Team plan", "1", "2,400.00", "2,400.00"),
            ("Onboarding and training session", "3", "150.00", "450.00"),
        ],
        "totaux": [("Subtotal", "2,850.00 USD", False), ("Sales tax 8.25%", "235.13 USD", False),
                   ("Total due", "3,085.13 USD", True)],
        "pied": ["Payment due within 30 days. Wire transfer only."],
        "attendu": {
            "numero_facture": "INV-2026-1188",
            "date_emission": "2026-03-09",
            "date_echeance": "2026-04-08",
            "nom_fournisseur": "SAMPLE SOFTWARE INC.",
            "nom_client": "DEMO STUDIO LLC",
            "montant_ht": 2850.0,
            "montant_tva": 235.13,
            "montant_ttc": 3085.13,
            "devise": "USD",
        },
    },
    {
        "fichier": "recu_008_sans_numero.pdf",
        "difficulte": "Reçu de caisse : aucun numéro de facture, aucun client nommé, pas de TVA détaillée. Trois champs légitimement absents.",
        "titre": "REÇU",
        "langue": "fr",
        "emetteur": {
            "nom": "LIBRAIRIE DU MODELE",
            "adresse": ["3 rue Fictive", "35000 Rennes"],
            "mentions": ["SIRET 000 000 000 00000"],
        },
        "destinataire": None,
        "references": [("Date", "11/02/2026"), ("Caisse", "02"), ("Ticket", "—")],
        "lignes": [
            ("Ouvrage - Linguistique générale", "1", "28,00", "28,00"),
            ("Ouvrage - Traitement du langage", "1", "45,50", "45,50"),
        ],
        "totaux": [("Total payé", "73,50 EUR", True)],
        "pied": ["Merci de votre visite.", "Article non repris sans ce reçu."],
        "attendu": {
            "numero_facture": None,
            "date_emission": "2026-02-11",
            "date_echeance": None,
            "nom_fournisseur": "LIBRAIRIE DU MODELE",
            "nom_client": None,
            "montant_ht": None,
            "montant_tva": None,
            "montant_ttc": 73.50,
            "devise": "EUR",
        },
    },
    {
        "fichier": "facture_009_source_pour_scan.pdf",
        "difficulte": "Source du scan dégradé (voir facture_009_scan_degrade.png).",
        "titre": "FACTURE",
        "langue": "fr",
        "emetteur": {
            "nom": "TRANSPORTS MODELE SARL",
            "adresse": ["88 route Imaginaire", "13000 Marseille"],
            "mentions": ["SIRET 000 000 000 00000"],
        },
        "destinataire": {"nom": "NEGOCE FICTIF SA", "adresse": ["4 quai du Test", "13500 Martigues"]},
        "references": [("Facture n°", "TM-2026-0503"), ("Date", "08/06/2026"),
                       ("Échéance", "08/07/2026")],
        "lignes": [
            ("Transport routier Marseille - Lyon", "4", "310,00", "1 240,00"),
            ("Frais de manutention", "1", "85,00", "85,00"),
        ],
        "totaux": [("Total HT", "1 325,00 EUR", False), ("TVA 20 %", "265,00 EUR", False),
                   ("Total TTC", "1 590,00 EUR", True)],
        "pied": ["Paiement à 30 jours fin de mois."],
        "attendu": {
            "numero_facture": "TM-2026-0503",
            "date_emission": "2026-06-08",
            "date_echeance": "2026-07-08",
            "nom_fournisseur": "TRANSPORTS MODELE SARL",
            "nom_client": "NEGOCE FICTIF SA",
            "montant_ht": 1325.0,
            "montant_tva": 265.0,
            "montant_ttc": 1590.0,
            "devise": "EUR",
        },
    },
]


def dessiner(spec: dict) -> Path:
    chemin = SORTIE / spec["fichier"]
    c = canvas.Canvas(str(chemin), pagesize=A4)
    largeur, hauteur = A4
    en_anglais = spec["langue"] == "en"

    # Filigrane : ces documents ne doivent jamais passer pour de vraies factures.
    c.saveState()
    c.setFont("Helvetica-Bold", 54)
    c.setFillColor(colors.Color(0.92, 0.92, 0.92))
    c.translate(largeur / 2, hauteur / 2)
    c.rotate(40)
    c.drawCentredString(0, 0, "TEST DOCUMENT" if en_anglais else "DOCUMENT DE TEST")
    c.restoreState()

    y = hauteur - 28 * mm
    c.setFont("Helvetica-Bold", 20)
    c.drawString(20 * mm, y, spec["titre"])
    c.setFont("Helvetica", 8)
    c.setFillColor(colors.grey)
    c.drawString(
        20 * mm,
        y - 5 * mm,
        "Fictitious document generated for pipeline testing"
        if en_anglais
        else "Document fictif généré pour tester un pipeline d'extraction",
    )
    c.setFillColor(colors.black)

    # Émetteur / destinataire
    y -= 18 * mm
    c.setFont("Helvetica-Bold", 9)
    c.drawString(20 * mm, y, "From" if en_anglais else "Émetteur")
    if spec["destinataire"]:
        c.drawString(112 * mm, y, "Bill to" if en_anglais else "Destinataire")

    c.setFont("Helvetica", 9)
    y -= 5 * mm
    c.drawString(20 * mm, y, spec["emetteur"]["nom"])
    for i, ligne in enumerate(spec["emetteur"]["adresse"] + spec["emetteur"]["mentions"]):
        c.drawString(20 * mm, y - (i + 1) * 4.4 * mm, ligne)

    if spec["destinataire"]:
        c.drawString(112 * mm, y, spec["destinataire"]["nom"])
        for i, ligne in enumerate(spec["destinataire"]["adresse"]):
            c.drawString(112 * mm, y - (i + 1) * 4.4 * mm, ligne)

    # Références
    y -= 26 * mm
    c.setFont("Helvetica", 10)
    for i, (libelle, valeur) in enumerate(spec["references"]):
        c.drawString(20 * mm, y - i * 5 * mm, f"{libelle} : {valeur}")
    y -= len(spec["references"]) * 5 * mm + 10 * mm

    # Tableau des lignes
    c.setFillColor(colors.Color(0.93, 0.93, 0.93))
    c.rect(20 * mm, y - 2.5 * mm, 170 * mm, 8 * mm, fill=1, stroke=0)
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 9)
    entetes = (
        ("Description", "Qty", "Unit price", "Amount")
        if en_anglais
        else ("Désignation", "Qté", "P.U.", "Montant")
    )
    c.drawString(22 * mm, y, entetes[0])
    c.drawRightString(120 * mm, y, entetes[1])
    c.drawRightString(152 * mm, y, entetes[2])
    c.drawRightString(188 * mm, y, entetes[3])

    c.setFont("Helvetica", 9)
    for designation, qte, pu, total in spec["lignes"]:
        y -= 7 * mm
        c.drawString(22 * mm, y, designation)
        c.drawRightString(120 * mm, y, qte)
        c.drawRightString(152 * mm, y, pu)
        c.drawRightString(188 * mm, y, total)

    # Totaux
    y -= 11 * mm
    c.line(112 * mm, y + 4.5 * mm, 190 * mm, y + 4.5 * mm)
    for libelle, valeur, gras in spec["totaux"]:
        c.setFont("Helvetica-Bold" if gras else "Helvetica", 11 if gras else 10)
        c.drawRightString(152 * mm, y, libelle)
        c.drawRightString(188 * mm, y, valeur)
        y -= 6.5 * mm

    # Pied de page
    c.setFont("Helvetica", 8)
    c.setFillColor(colors.grey)
    for i, ligne in enumerate(spec["pied"]):
        c.drawString(20 * mm, 24 * mm - i * 4 * mm, ligne)
    c.drawString(
        20 * mm,
        14 * mm,
        "Test document - fictitious company and amounts."
        if en_anglais
        else "Document de test - entreprise et montants fictifs.",
    )

    c.showPage()
    c.save()
    return chemin


def degrader_en_scan(source: Path, destination: Path) -> None:
    """Simule un scan de mauvaise qualité : rotation, bruit, contraste affaibli."""
    import numpy as np
    import pypdfium2 as pdfium
    from PIL import Image, ImageEnhance, ImageFilter

    image = pdfium.PdfDocument(str(source))[0].render(scale=2.0).to_pil().convert("L")

    image = image.rotate(-0.7, resample=Image.BICUBIC, expand=False, fillcolor=245)
    image = ImageEnhance.Contrast(image).enhance(0.75)
    image = image.filter(ImageFilter.GaussianBlur(radius=0.6))

    tableau = np.asarray(image).astype(np.int16)
    rng = np.random.default_rng(20260922)
    tableau += rng.normal(0, 11, tableau.shape).astype(np.int16)
    # Voile grisâtre inégal, comme une vitre de scanner sale.
    hauteur, largeur = tableau.shape
    voile = np.linspace(0, 14, largeur)[None, :] * np.linspace(0.3, 1.0, hauteur)[:, None]
    tableau -= voile.astype(np.int16)

    Image.fromarray(np.clip(tableau, 0, 255).astype(np.uint8)).save(destination, dpi=(150, 150))


if __name__ == "__main__":
    random.seed(20260922)
    for spec in DOCUMENTS:
        chemin = dessiner(spec)
        print(f"écrit : {chemin.name}")

    degrader_en_scan(
        SORTIE / "facture_009_source_pour_scan.pdf", SORTIE / "facture_009_scan_degrade.png"
    )
    print("écrit : facture_009_scan_degrade.png")

    # Les annotations découlent des mêmes données que le rendu.
    print("\nAnnotations dérivées :")
    print(json.dumps({d["fichier"]: d["attendu"] for d in DOCUMENTS}, ensure_ascii=False, indent=2)[:400])
