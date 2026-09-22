# Extraction automatique d'informations depuis des documents non structurés

Pipeline qui transforme des factures, CV ou contrats (PDF natif, PDF scanné ou image)
en données structurées exportables (CSV, Excel, SQLite), avec détection automatique
des extractions douteuses.

## Pourquoi ce projet

L'extraction d'informations depuis des documents est l'un des cas d'usage LLM les plus
répandus en entreprise. Ce projet en implémente une version complète, avec deux partis
pris qui le distinguent d'une démo :

1. **Sortie structurée garantie.** Le schéma Pydantic est déclaré comme un *outil* et
   son appel est forcé via `tool_choice`. Le modèle ne peut pas renvoyer autre chose
   qu'un objet conforme — pas de JSON malformé à rattraper au parsing.
2. **Validation métier et score de confiance.** Un LLM se trompe avec le même aplomb
   qu'il a raison. Des règles vérifiables (HT + TVA = TTC, cohérence des dates, formats)
   produisent un score qui route les documents douteux vers une relecture humaine.

C'est un **pipeline**, pas un agent : l'ordre des étapes est fixé par le code, le LLM
n'intervient que sur la structuration. Ce choix est délibéré — pour ce cas d'usage, un
workflow déterministe est plus fiable, moins cher et plus testable qu'un agent autonome.

## Architecture

```
document (PDF / image)
        │
        ▼
┌───────────────────────┐
│ 1. extraction.py      │  PDF natif → pdfplumber
│                       │  PDF scanné → pypdfium2 + Tesseract   (bascule automatique)
│                       │  image → Tesseract
└───────────┬───────────┘
            ▼ texte brut
┌───────────────────────┐
│ 2. structuration.py   │  LLM + schéma Pydantic forcé via tool_choice
└───────────┬───────────┘
            ▼ objet typé
┌───────────────────────┐
│ 3. validation.py      │  règles métier → score de confiance + alertes
└───────────┬───────────┘
            ▼
┌───────────────────────┐
│ 4. export.py          │  CSV / Excel (onglet « à relire ») / SQLite
└───────────────────────┘
```

| Fichier | Rôle |
|---|---|
| `src/schemas.py` | Schémas Pydantic (Facture, CV, Contrat) — définissent les champs extraits |
| `src/extraction.py` | Texte brut depuis PDF ou image, avec détection PDF natif vs scanné |
| `src/structuration.py` | Appel LLM à sortie structurée + conversion du schéma en JSON Schema |
| `src/validation.py` | Règles de cohérence et calcul du score de confiance |
| `src/pipeline.py` | Orchestration des 4 étapes, gestion des erreurs par document |
| `src/export.py` | Export CSV / Excel / SQLite |
| `app.py` | Interface Streamlit |
| `main.py` | Traitement par lot en ligne de commande |

## Installation

```bash
git clone <url-du-repo>
cd extraction-documents

python -m venv .venv
source .venv/bin/activate          # Windows : .venv\Scripts\activate
pip install -r requirements.txt
```

Tesseract doit être installé séparément (c'est un binaire système, pas un paquet Python) :

```bash
# macOS
brew install tesseract tesseract-lang

# Ubuntu / Debian
sudo apt install tesseract-ocr tesseract-ocr-fra
```

Puis la configuration :

```bash
cp .env.example .env
# éditer .env et y mettre la clé ANTHROPIC_API_KEY
```

## Utilisation

**Interface graphique**

```bash
streamlit run app.py
```

Dépose un ou plusieurs documents, choisis le type dans la barre latérale, lance
l'extraction. Les lignes surlignées sont celles à relire.

**Ligne de commande**

```bash
python main.py data/input --type facture --format excel
python main.py data/input --type cv --format csv --sortie resultats.csv
python main.py data/input --type contrat --format sqlite
```

**Tests**

```bash
pytest tests/ -v
```

Les tests couvrent la logique de validation et la génération du schéma. Ils ne
nécessitent ni clé API ni document, donc ils tournent en moins d'une seconde et
peuvent être branchés sur une CI.

## Ajouter un type de document

1. Définir une classe Pydantic dans `src/schemas.py`, avec une `description` soignée
   pour chaque champ (ces descriptions sont envoyées au modèle et pilotent directement
   la qualité de l'extraction).
2. L'enregistrer dans le dictionnaire `SCHEMAS`.
3. Optionnellement, ajouter une fonction `_valider_<type>` dans `src/validation.py`.

Aucune autre modification n'est nécessaire : l'app et le CLI lisent `SCHEMAS`.

## Détails d'implémentation notables

**Bascule PDF natif → OCR.** Un PDF scanné ne contient aucune couche texte. Le module
lit d'abord le texte natif et, en dessous de 100 caractères, bascule sur l'OCR. Sans
ce test, un scan produit une extraction vide sans erreur visible.

**pypdfium2 plutôt que pdf2image.** `pdf2image` dépend du binaire poppler, un point de
friction classique au déploiement. `pypdfium2` embarque son moteur de rendu.

**Aplatissement du JSON Schema.** Pydantic génère `anyOf: [type, null]` pour les champs
`Optional` et des `$ref` pour les objets imbriqués. `_json_schema_compatible` les résout
pour produire un schéma plat, plus lisible pour le modèle.

**Un échec ne fait pas tomber le lot.** Chaque document est traité dans un `try/except` :
un PDF corrompu au milieu de cinquante fichiers ne fait pas perdre les quarante-neuf autres.

## Pistes d'extension

- **Comparatif OCR** : mesurer Tesseract contre une API d'OCR managée (précision, latence,
  coût par page) sur un même jeu de documents, et publier le tableau.
- **Documents longs** : découper les contrats de plus de 20 000 caractères et extraire
  par section plutôt que de tronquer.
- **Évaluation quantifiée** : constituer un jeu de 30 documents annotés à la main et
  mesurer la précision champ par champ. C'est ce qui transforme « ça a l'air de marcher »
  en résultat défendable.
- **Cache** : mémoriser les extractions par hash de fichier pour ne pas repayer un appel
  API sur un document déjà traité.
- **Variante agentique** : exposer les étapes comme des outils et laisser un agent
  décider de l'enchaînement, puis comparer fiabilité, coût et latence avec ce pipeline.

## Données de test

Le dossier `data/input/` est vide et ignoré par git. Pour tester :

- **Factures** : le dataset SROIE (reçus annotés) est disponible publiquement, ou génère
  des factures fictives depuis un template.
- **CV** : utilise ton propre CV et des CV publics de profils fictifs.
- **Contrats** : des modèles de contrats types sont disponibles sur service-public.fr.

N'utilise jamais de documents contenant de vraies données personnelles dans un repo public.
