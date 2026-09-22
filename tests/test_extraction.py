"""Tests sur la lecture des documents.

Le cas des PDF de type formulaire (AcroForm) est traité à part : les valeurs
saisies n'y sont pas dans le texte de la page mais dans une structure distincte.
Une lecture naïve renvoie le modèle vierge, ce qui est silencieux et trompeur —
d'où ces tests.
"""

import pytest

from src.extraction import _denormaliser_nom_champ, extraire_texte, regrouper_en_lignes


def mot(texte: str, x: float, haut: float, hauteur: float = 9.0) -> dict:
    return {"text": texte, "x0": x, "top": haut, "bottom": haut + hauteur}


def rendre(lignes) -> list[str]:
    ordonnees = sorted(lignes, key=lambda l: l["centre"])
    return [
        " ".join(t for _, t in sorted(l["elements"], key=lambda e: e[0])) for l in ordonnees
    ]


class TestRegroupementEnLignes:
    """Régression : un filigrane avalait la page entière.

    Le regroupement étendait l'étendue verticale d'une ligne à chaque mot ajouté.
    Une lettre de filigrane haute de 54 points élargissait donc la ligne au point
    d'absorber tout le document, qui se retrouvait sur une seule ligne, montants
    mélangés. Aucune erreur levée, aucun texte perdu : seulement un ordre de lecture
    détruit. Détecté par l'évaluation, pas par les tests d'alors.
    """

    def test_lignes_separees(self):
        mots = [
            mot("Total", 100, 500),
            mot("HT", 130, 500),
            mot("1 190,00", 300, 500),
            mot("TVA", 100, 515),
            mot("238,00", 300, 515),
        ]
        assert rendre(regrouper_en_lignes(mots)) == ["Total HT 1 190,00", "TVA 238,00"]

    def test_ordre_horizontal_respecte(self):
        mots = [mot("fin", 300, 100), mot("debut", 50, 100), mot("milieu", 150, 100)]
        assert rendre(regrouper_en_lignes(mots)) == ["debut milieu fin"]

    def test_filigrane_n_avale_pas_la_page(self):
        # Une lettre de filigrane de 54 points, centrée au milieu du document.
        mots = [
            mot("D", 200, 380, hauteur=54),
            mot("Total", 100, 400),
            mot("1 190,00", 300, 400),
            mot("TVA", 100, 420),
            mot("238,00", 300, 420),
            mot("TTC", 100, 440),
            mot("1 428,00", 300, 440),
        ]
        lignes = rendre(regrouper_en_lignes(mots))
        assert len(lignes) >= 3, f"les lignes ont fusionné : {lignes}"
        assert "1 190,00" not in " ".join(l for l in lignes if "1 428,00" in l)

    def test_montants_ne_se_melangent_pas(self):
        mots = [mot("D", 200, 380, hauteur=54)]
        for i, montant in enumerate(["400,00", "210,00", "190,00", "238,00", "428,00"]):
            mots.append(mot(f"Ligne{i}", 100, 400 + i * 15))
            mots.append(mot(montant, 300, 400 + i * 15))
        lignes = rendre(regrouper_en_lignes(mots))
        montants_par_ligne = [sum(1 for m in ["400,00", "210,00", "190,00"] if m in l) for l in lignes]
        assert max(montants_par_ligne) <= 1, f"plusieurs montants sur une ligne : {lignes}"

    def test_titre_plus_grand_reste_seul(self):
        mots = [mot("FACTURE", 50, 100, hauteur=20), mot("Émetteur", 50, 140)]
        assert len(regrouper_en_lignes(mots)) == 2

    def test_liste_vide(self):
        assert regrouper_en_lignes([]) == []


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
