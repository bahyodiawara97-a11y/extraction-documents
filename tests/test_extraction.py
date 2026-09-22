"""Tests sur la lecture des documents.

Le cas des PDF de type formulaire (AcroForm) est traité à part : les valeurs
saisies n'y sont pas dans le texte de la page mais dans une structure distincte.
Une lecture naïve renvoie le modèle vierge, ce qui est silencieux et trompeur —
d'où ces tests.
"""

import pytest

from src.extraction import _denormaliser_nom_champ, extraire_texte


class TestDenormalisationNomChamp:
    """Les noms de champs PDF encodent les caractères non-ASCII en #XX."""

    def test_accent_decode(self):
        assert _denormaliser_nom_champ("Case #C3#A0 cocher 2_7") == "Case à cocher 2_7"

    def test_nom_simple_inchange(self):
        assert _denormaliser_nom_champ("Zone de texte 1_28") == "Zone de texte 1_28"

    def test_chaine_vide(self):
        assert _denormaliser_nom_champ("") == ""

    def test_diese_isole_conserve(self):
        # Un # qui n'introduit pas deux chiffres hexadécimaux reste tel quel.
        assert _denormaliser_nom_champ("champ#zz") == "champ#zz"

    def test_plusieurs_echappements(self):
        assert _denormaliser_nom_champ("#C3#A9t#C3#A9") == "été"


class TestFormatsNonSupportes:
    def test_extension_inconnue(self, tmp_path):
        fichier = tmp_path / "document.xyz"
        fichier.write_text("contenu")
        with pytest.raises(ValueError, match="Format non supporté"):
            extraire_texte(fichier)

    def test_fichier_absent(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            extraire_texte(tmp_path / "inexistant.pdf")


class TestTexteBrut:
    def test_lecture_txt(self, tmp_path):
        fichier = tmp_path / "note.txt"
        fichier.write_text("Facture n° 42\nMontant : 100 EUR", encoding="utf-8")
        resultat = extraire_texte(fichier)
        assert resultat.methode == "texte_brut"
        assert "Facture n° 42" in resultat.texte
        assert not resultat.est_vide

    def test_fichier_quasi_vide_signale(self, tmp_path):
        fichier = tmp_path / "vide.txt"
        fichier.write_text("x", encoding="utf-8")
        assert extraire_texte(fichier).est_vide
