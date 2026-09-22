"""Interface Streamlit : dépôt de documents, extraction, contrôle, export.

Lancer avec :  streamlit run app.py

Deux modes. Le mode démonstration rejoue des résultats figés, sans appel API ni clé :
c'est ce que voit un visiteur de passage. Le mode traitement exécute le vrai pipeline
sur les documents déposés, et demande une clé.

L'affichage des résultats est commun aux deux modes, par construction : la
démonstration reconstruit les mêmes objets que le pipeline, si bien qu'elle ne peut
pas montrer autre chose que ce que le traitement produirait.
"""

from __future__ import annotations

import io
import os
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from src import demo
from src.export import vers_dataframe
from src.pipeline import ResultatLot, traiter_octets
from src.schemas import SCHEMAS

load_dotenv()

st.set_page_config(page_title="Extraction de documents", page_icon="📄", layout="wide")

DEMO_DISPONIBLE = Path(demo.CHEMIN_DEFAUT).exists()


# ---------------------------------------------------------------- affichage --
def afficher_resultats(lot: ResultatLot, prefixe_fichier: str, commentaires: dict | None = None):
    """Affiche un lot traité. Commun au mode démonstration et au mode traitement."""
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Documents", len(lot.documents))
    c2.metric("Extraits", lot.nb_succes)
    c3.metric("Échecs", lot.nb_echecs)
    c4.metric("À relire", lot.nb_a_reviser)

    df = vers_dataframe(lot)

    st.subheader("Données extraites")
    st.dataframe(
        df.style.apply(
            lambda ligne: [
                "background-color: rgba(255, 193, 7, 0.15)"
                if ligne.get("necessite_revision")
                else ""
                for _ in ligne
            ],
            axis=1,
        ),
        use_container_width=True,
    )

    # Détail par document, en distinguant ce qui est une erreur de ce qui est
    # seulement inhabituel — la confusion entre les deux était le défaut à corriger.
    with st.expander("Détail par document", expanded=bool(commentaires)):
        for doc in lot.documents:
            if commentaires and doc.nom_fichier in commentaires:
                st.markdown(f"**{doc.nom_fichier}** — *{commentaires[doc.nom_fichier]}*")

            if not doc.succes:
                st.error(f"**{doc.nom_fichier}** — {doc.erreur}")
                continue
            if doc.rapport is None:
                continue

            if doc.rapport.controles_echoues:
                st.warning(
                    f"**{doc.nom_fichier}** — contrôles en échec\n\n"
                    + "\n".join(f"- {c}" for c in doc.rapport.controles_echoues)
                )
            if doc.rapport.champs_critiques_manquants:
                st.warning(
                    f"**{doc.nom_fichier}** — champs indispensables absents : "
                    + ", ".join(doc.rapport.champs_critiques_manquants)
                )
            if doc.rapport.remarques:
                st.info(
                    f"**{doc.nom_fichier}** — remarques (pas des erreurs)\n\n"
                    + "\n".join(f"- {r}" for r in doc.rapport.remarques)
                )

    st.subheader("Export")
    col_csv, col_xlsx = st.columns(2)

    col_csv.download_button(
        "Télécharger en CSV",
        data=df.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"{prefixe_fichier}.csv",
        mime="text/csv",
    )

    tampon = io.BytesIO()
    with pd.ExcelWriter(tampon, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Donnees", index=False)
    col_xlsx.download_button(
        "Télécharger en Excel",
        data=tampon.getvalue(),
        file_name=f"{prefixe_fichier}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def afficher_scores(scores: dict):
    """Tableau de précision, rappel et hallucinations par champ."""
    st.subheader("Justesse mesurée")
    st.caption(
        "Comparaison à des valeurs annotées à la main. Quatre issues sont distinguées "
        "par champ : correct, incorrect, omission et **hallucination** — un champ rempli "
        "alors qu'aucune valeur n'existait dans le document. Cette dernière est la plus "
        "grave : une omission se voit, une valeur inventée passe inaperçue."
    )

    c1, c2, c3 = st.columns(3)
    precision = scores.get("precision_globale")
    rappel = scores.get("rappel_global")
    c1.metric("Précision globale", "—" if precision is None else f"{precision:.1%}")
    c2.metric("Rappel global", "—" if rappel is None else f"{rappel:.1%}")
    c3.metric("Hallucinations", scores.get("hallucinations", "—"))

    lignes = scores.get("par_champ", [])
    if lignes:
        table = pd.DataFrame(lignes)
        for colonne in ("precision", "rappel", "f1"):
            if colonne in table:
                table[colonne] = table[colonne].map(
                    lambda v: "—" if pd.isna(v) else f"{v:.1%}"
                )
        st.dataframe(table, use_container_width=True, hide_index=True)


# ------------------------------------------------------------ barre latérale --
with st.sidebar:
    st.header("Configuration")

    modes = []
    if DEMO_DISPONIBLE:
        modes.append("Démonstration (sans clé API)")
    modes.append("Traiter mes documents")
    mode = st.radio("Mode", modes, label_visibility="collapsed")
    demonstration = mode.startswith("Démonstration")

    st.divider()

    if demonstration:
        st.caption(
            "Résultats figés d'une exécution réelle du pipeline sur un jeu de documents "
            "fictifs. Aucun appel API n'est effectué."
        )
    else:
        type_document = st.selectbox(
            "Type de document",
            options=list(SCHEMAS.keys()),
            format_func=str.capitalize,
            help="Détermine les champs qui seront extraits.",
        )

        cle_presente = bool(os.getenv("ANTHROPIC_API_KEY"))
        if cle_presente:
            st.success("Clé API détectée")
        else:
            st.info(
                "Cette application appelle l'API Anthropic. Renseigne ta propre clé "
                "pour traiter tes documents — elle n'est ni stockée ni transmise "
                "ailleurs qu'à l'API."
            )
            cle_saisie = st.text_input("Clé API Anthropic", type="password")
            if cle_saisie:
                os.environ["ANTHROPIC_API_KEY"] = cle_saisie
                cle_presente = True

        with st.expander("Champs extraits pour ce type"):
            for nom, champ in SCHEMAS[type_document].model_fields.items():
                st.markdown(f"**{nom}** — {champ.description or '—'}")

    st.divider()
    st.caption(
        "Un document est signalé à relire quand un contrôle métier échoue ou qu'un "
        "champ indispensable manque — jamais sur un simple seuil de complétude, "
        "qu'un document peut faire baisser sans la moindre erreur d'extraction."
    )
    st.markdown(
        "[Code source](https://github.com/bahyodiawara97-a11y/extraction-documents)"
    )


# ------------------------------------------------------------------- en-tête --
st.title("📄 Extraction automatique d'informations")
st.caption(
    "Factures, reçus, CV et contrats — PDF natifs, formulaires ou scans — convertis "
    "en données structurées, avec contrôles de cohérence et mesure de justesse."
)


# --------------------------------------------------------------------- modes --
if demonstration:
    lot, meta = demo.charger(SCHEMAS)
    scores = meta.get("scores", {})

    st.success(
        f"**Mode démonstration** — {len(lot.documents)} documents fictifs traités par le "
        f"pipeline le {meta.get('genere_le', '?')} avec `{meta.get('modele', '?')}`. "
        "Aucun appel API n'est effectué ici : les résultats affichés sont ceux de cette "
        "exécution. Pour traiter tes propres documents, bascule de mode dans la barre "
        "latérale et renseigne une clé API."
    )

    with st.expander("Ce que ce jeu cherche à éprouver"):
        st.markdown(
            "Les documents ne sont pas de simples factures bien formées. Chacun porte "
            "une difficulté précise : une prestation **exonérée de TVA** sans montant HT, "
            "un **paiement comptant** sans date d'échéance, un **reçu** sans numéro ni "
            "client, une **remise commerciale** avec deux sous-totaux, une facture **en "
            "anglais et en dollars** aux dates américaines, et un **scan dégradé** "
            "(rotation, bruit, voile gris).\n\n"
            "Neuf champs y sont légitimement vides. Ils servent de pièges : un pipeline "
            "qui déduit un HT en divisant le total par 1,2, ou qui ajoute trente jours à "
            "une date d'émission pour fabriquer une échéance, se fait prendre ici."
        )

    if scores:
        afficher_scores(scores)
        st.divider()

    afficher_resultats(lot, "demonstration_extraction", demo.commentaires())

else:
    fichiers = st.file_uploader(
        "Documents à traiter",
        type=["pdf", "png", "jpg", "jpeg", "tiff", "txt"],
        accept_multiple_files=True,
    )

    if fichiers and st.button("Lancer l'extraction", type="primary", disabled=not cle_presente):
        schema = SCHEMAS[type_document]
        lot = ResultatLot()
        barre = st.progress(0.0, text="Traitement en cours…")

        for i, fichier in enumerate(fichiers):
            barre.progress((i + 1) / len(fichiers), text=f"Traitement de {fichier.name}…")
            lot.documents.append(traiter_octets(fichier.getvalue(), fichier.name, schema))

        barre.empty()
        st.session_state["lot"] = lot

    lot = st.session_state.get("lot")
    if lot and lot.documents:
        afficher_resultats(lot, f"{type_document}s_extraits")
    elif not fichiers:
        st.info(
            "Dépose un ou plusieurs documents pour commencer"
            + (", ou passe en mode démonstration dans la barre latérale." if DEMO_DISPONIBLE else ".")
        )
