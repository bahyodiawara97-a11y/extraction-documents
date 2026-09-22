"""Étape 1 du pipeline : obtenir du texte brut à partir d'un document.

Deux chemins possibles, et c'est tout l'intérêt de ce module :
  - PDF natif  : le texte est déjà dans le fichier, on le lit directement (rapide, fiable) ;
  - PDF scanné : le fichier ne contient que des images, il faut passer par l'OCR.

Beaucoup de projets de démo supposent que tous les PDF sont natifs et échouent
silencieusement sur un scan. Ici on détecte le cas et on bascule automatiquement.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Écart vertical maximal (en points) pour rattacher une valeur de formulaire à une
# ligne de texte. Au-delà, la valeur est listée à part plutôt que mal placée.
TOLERANCE_LIGNE = 12

# En dessous de ce nombre de caractères, on considère que le PDF n'a pas de couche texte
# exploitable (page blanche ou scan) et on bascule sur l'OCR.
SEUIL_TEXTE_NATIF = 100

EXTENSIONS_IMAGE = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp"}


@dataclass
class ResultatExtraction:
    """Texte brut d'un document + métadonnées sur la façon dont il a été obtenu."""

    texte: str
    methode: str  # "pdf_natif" | "ocr" | "image_ocr"
    nb_pages: int
    nb_caracteres: int

    @property
    def est_vide(self) -> bool:
        return self.nb_caracteres < 20


def extraire_texte(chemin: str | Path, lang: str | None = None) -> ResultatExtraction:
    """Extrait le texte d'un PDF ou d'une image, en choisissant la méthode adaptée."""
    chemin = Path(chemin)
    if not chemin.exists():
        raise FileNotFoundError(f"Fichier introuvable : {chemin}")

    lang = lang or os.getenv("OCR_LANG", "fra")
    suffixe = chemin.suffix.lower()

    if suffixe == ".pdf":
        resultat = _lire_pdf_natif(chemin)
        if resultat.nb_caracteres < SEUIL_TEXTE_NATIF:
            logger.info("Peu de texte natif dans %s, bascule sur OCR", chemin.name)
            return _ocr_pdf(chemin, lang)
        return resultat

    if suffixe in EXTENSIONS_IMAGE:
        return _ocr_image(chemin, lang)

    if suffixe in {".txt", ".md"}:
        texte = chemin.read_text(encoding="utf-8", errors="replace")
        return ResultatExtraction(texte, "texte_brut", 1, len(texte))

    raise ValueError(f"Format non supporté : {suffixe}")


def _denormaliser_nom_champ(nom: str) -> str:
    """Décode les échappements #XX des noms de champs PDF.

    pdfplumber et pypdf ne les décodent pas de la même façon : 'Case #C3#A0 cocher'
    doit devenir 'Case à cocher' des deux côtés pour que la jointure fonctionne.
    """
    octets = bytearray()
    i = 0
    while i < len(nom):
        if nom[i] == "#" and i + 2 < len(nom) and re.fullmatch(r"[0-9A-Fa-f]{2}", nom[i + 1 : i + 3]):
            octets.append(int(nom[i + 1 : i + 3], 16))
            i += 3
        else:
            octets.extend(nom[i].encode("utf-8"))
            i += 1
    return octets.decode("utf-8", "replace")


def _valeurs_formulaire(chemin: Path) -> dict[str, str]:
    """Valeurs des champs d'un formulaire PDF (AcroForm), indexées par nom normalisé.

    On passe par pypdf et non par pdfplumber : ce dernier tronque les valeurs
    encodées en UTF-16 (il ne renvoie que le marqueur d'ordre des octets).
    """
    try:
        from pypdf import PdfReader

        champs = PdfReader(str(chemin)).get_fields() or {}
    except Exception as exc:  # noqa: BLE001 - un PDF sans formulaire ne doit pas faire échouer la lecture
        logger.debug("Pas de formulaire exploitable dans %s : %s", chemin.name, exc)
        return {}

    valeurs: dict[str, str] = {}
    for nom, champ in champs.items():
        brut = champ.get("/V")
        if brut is None:
            continue
        texte = str(brut).strip()
        if texte in ("", "/Off", "Off"):
            continue
        if texte in ("/Yes", "/On", "/1", "Yes", "On"):
            texte = "[X]"
        valeurs[_denormaliser_nom_champ(nom)] = texte
    return valeurs


def _lire_pdf_natif(chemin: Path) -> ResultatExtraction:
    """Lit la couche texte d'un PDF, en y réinsérant les valeurs de formulaire.

    Un PDF de type formulaire (contrat, déclaration, dossier administratif) stocke
    les valeurs saisies dans une structure distincte du texte de la page. Une lecture
    naïve renvoie donc le modèle vierge : tous les intitulés, aucune valeur. On lit
    ces valeurs séparément et on les replace sur la ligne de texte la plus proche,
    pour que le document reconstitué se lise comme à l'écran.
    """
    import pdfplumber

    valeurs = _valeurs_formulaire(chemin)
    restantes = dict(valeurs)
    pages: list[str] = []

    with pdfplumber.open(str(chemin)) as pdf:
        for page in pdf.pages:
            lignes: list[dict] = []

            for mot in sorted(page.extract_words(), key=lambda m: (m["top"], m["x0"])):
                centre = (mot["top"] + mot["bottom"]) / 2
                ligne = next((l for l in lignes if l["haut"] - 2 <= centre <= l["bas"] + 2), None)
                if ligne is None:
                    lignes.append(
                        {
                            "haut": mot["top"],
                            "bas": mot["bottom"],
                            "elements": [(mot["x0"], mot["text"])],
                        }
                    )
                else:
                    ligne["elements"].append((mot["x0"], mot["text"]))
                    ligne["haut"] = min(ligne["haut"], mot["top"])
                    ligne["bas"] = max(ligne["bas"], mot["bottom"])

            for annot in page.annots or []:
                nom = _denormaliser_nom_champ(annot.get("title") or "")
                valeur = valeurs.get(nom)
                if not valeur:
                    continue
                restantes.pop(nom, None)
                centre = (annot["top"] + annot["bottom"]) / 2
                ligne = min(
                    lignes, key=lambda l: abs((l["haut"] + l["bas"]) / 2 - centre), default=None
                )
                if ligne is not None and abs((ligne["haut"] + ligne["bas"]) / 2 - centre) < TOLERANCE_LIGNE:
                    ligne["elements"].append((annot["x0"], valeur))
                else:
                    lignes.append(
                        {
                            "haut": annot["top"],
                            "bas": annot["bottom"],
                            "elements": [(annot["x0"], valeur)],
                        }
                    )

            lignes.sort(key=lambda l: l["haut"])
            pages.append(
                "\n".join(
                    " ".join(t for _, t in sorted(l["elements"], key=lambda e: e[0]))
                    for l in lignes
                )
            )

    texte = "\n\n".join(pages).strip()

    # Filet de sécurité : aucune valeur saisie ne doit être perdue, même si on n'a
    # pas su la replacer dans la page.
    if restantes:
        logger.info("%d valeur(s) de formulaire non localisée(s) dans %s", len(restantes), chemin.name)
        lignes_restantes = "\n".join(f"{nom} : {valeur}" for nom, valeur in restantes.items())
        texte += "\n\n--- Champs de formulaire non localisés dans la page ---\n" + lignes_restantes

    if valeurs:
        logger.info("%d valeur(s) de formulaire lues dans %s", len(valeurs), chemin.name)

    return ResultatExtraction(texte, "pdf_formulaire" if valeurs else "pdf_natif", len(pages), len(texte))


def _ocr_pdf(chemin: Path, lang: str) -> ResultatExtraction:
    """Rend chaque page du PDF en image puis applique l'OCR.

    On utilise pypdfium2 plutôt que pdf2image : pas besoin d'installer poppler
    sur la machine, ce qui évite un point de friction au déploiement.
    """
    import pypdfium2 as pdfium
    import pytesseract

    pdf = pdfium.PdfDocument(str(chemin))
    pages: list[str] = []
    for i in range(len(pdf)):
        # scale=3 ≈ 216 dpi : bon compromis précision OCR / temps de traitement.
        image = pdf[i].render(scale=3).to_pil()
        pages.append(pytesseract.image_to_string(image, lang=lang))

    texte = "\n\n".join(pages).strip()
    return ResultatExtraction(texte, "ocr", len(pdf), len(texte))


def _ocr_image(chemin: Path, lang: str) -> ResultatExtraction:
    """Applique l'OCR à une image seule."""
    import pytesseract
    from PIL import Image

    texte = pytesseract.image_to_string(Image.open(chemin), lang=lang).strip()
    return ResultatExtraction(texte, "image_ocr", 1, len(texte))


def extraire_texte_depuis_octets(
    contenu: bytes, nom_fichier: str, lang: str | None = None
) -> ResultatExtraction:
    """Variante pour les fichiers uploadés dans Streamlit (jamais écrits sur disque durablement)."""
    import tempfile

    suffixe = Path(nom_fichier).suffix.lower()
    with tempfile.NamedTemporaryFile(suffix=suffixe, delete=False) as tmp:
        tmp.write(contenu)
        chemin_tmp = Path(tmp.name)
    try:
        return extraire_texte(chemin_tmp, lang=lang)
    finally:
        chemin_tmp.unlink(missing_ok=True)
