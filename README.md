# Extraction d'informations depuis des documents non structurés

Pipeline qui transforme des factures, reçus, CV et contrats-PDF natifs, PDF
formulaires ou scans - en données structurées exportables, avec une mesure de
justesse champ par champ et des contrôles de cohérence métier.

Écrit en Python, testé par 133 tests, évalué sur un jeu de documents annotés.

**[Démonstration en ligne](https://extraction-documents-bahyo.streamlit.app)** - sans clé API : l'application rejoue les résultats d'une exécution réelle du pipeline
sur le jeu d'évaluation. Une démonstration publique déployée avec une clé laisserait
n'importe quel visiteur dépenser le crédit de son auteur ; déployée sans, elle
accueillerait le visiteur par une demande de clé qu'il n'a pas. Les résultats sont
donc figés par `evaluation/generer_demo.py`, qui exécute le vrai pipeline — rien
n'est écrit à la main. Qui veut traiter ses propres documents apporte sa clé.

## Résultats mesurés

Sur un jeu de 10 documents annotés à la main (90 comparaisons champ par champ) :

| Champ | Attendus | Précision | Rappel | Hallucinations |
|---|---|---|---|---|
| numero_facture | 9 | 100 % | 100 % | 0 |
| date_emission | 10 | 100 % | 100 % | 0 |
| date_echeance | 7 | 100 % | 100 % | 0 |
| nom_fournisseur | 10 | 100 % | 100 % | 0 |
| nom_client | 9 | 100 % | 100 % | 0 |
| montant_ht | 8 | 100 % | 100 % | 0 |
| montant_tva | 8 | 100 % | 100 % | 0 |
| montant_ttc | 10 | 100 % | 100 % | 0 |
| devise | 10 | 100 % | 100 % | 0 |

Le chiffre qui compte n'est pas le 100 %, c'est la dernière colonne. **Neuf champs
du jeu devaient légitimement rester vides** - une facture exonérée de TVA sans
montant HT, un paiement comptant sans échéance, un reçu sans numéro ni client - et
les neuf sont restés vides. Le pipeline n'a pas divisé le total par 1,2 pour
fabriquer un HT, ni ajouté trente jours à la date d'émission pour inventer une
échéance.

**Ce que ces chiffres ne disent pas.** Dix documents, c'est peu. Ils sont tous
synthétiques, générés par un script versionné dans `evaluation/`, donc porteurs des
angles morts de leur auteur. Aucun document d'entreprise réel n'a encore été
évalué. Un taux de 100 % sur un tel jeu signifie « ne s'effondre pas sur les cas
prévus », pas « fiable en production ». L'extension à des documents réels est la
prochaine étape, et le harnais est prêt à les accueillir.

Reproduire la mesure :

```bash
python evaluer.py evaluation/annotations.json --sortie evaluation/resultats.csv
python evaluer.py evaluation/annotations.json --simuler   # sans appel API
```

## Pourquoi quatre issues et non un taux de réussite

Pour chaque champ, la comparaison distingue quatre cas : **correct** (valeur
attendue, extraite à l'identique), **incorrect** (une autre valeur est sortie),
**omission** (le champ est resté vide alors qu'une valeur existait) et
**hallucination** (aucune valeur n'était attendue, le champ a pourtant été rempli).

Cette dernière distinction est celle que la plupart des évaluations écrasent, à
tort. Une omission se rattrape : le champ est vide, un humain le voit et le
complète. Une hallucination est invisible - elle produit une valeur plausible que
personne ne remettra en question. Un pipeline qui omet vaut mieux qu'un pipeline
qui invente, et aucune mesure d'exactitude globale ne fait apparaître cette
asymétrie.

D'où deux indicateurs séparés. La **précision** répond à « quand le pipeline
remplit ce champ, puis-je le croire » : les hallucinations la font chuter. Le
**rappel** répond à « rate-t-il des informations » : les omissions la font chuter,
mais il est aveugle aux hallucinations. Un test vérifie explicitement cette
propriété (`test_precision_penalisee_par_les_hallucinations`).

## Architecture

```
document (PDF natif / PDF formulaire / scan)
        │
        ▼
┌────────────────────────┐
│ 1. extraction.py       │  texte natif → pdfplumber
│                        │  formulaire AcroForm → pypdf (valeurs) + positions
│                        │  scan → pypdfium2 + Tesseract   (bascule automatique)
└───────────┬────────────┘
            ▼ texte
┌────────────────────────┐
│ 2. structuration.py    │  LLM + schéma Pydantic forcé via tool_choice
│                        │  découpage en blocs si > 20 000 caractères
└───────────┬────────────┘
            ▼ objet typé
┌────────────────────────┐
│ 3. validation.py       │  contrôles métier + complétude + remarques
└───────────┬────────────┘
            ▼
┌────────────────────────┐
│ 4. export.py           │  CSV / Excel / SQLite
└────────────────────────┘

src/evaluation.py — mesure la justesse contre un jeu annoté (hors pipeline)
```

| Fichier | Rôle |
|---|---|
| `src/schemas.py` | Schémas Pydantic : Facture, CV, Contrat |
| `src/extraction.py` | Texte brut, trois chemins de lecture |
| `src/structuration.py` | Appel LLM à sortie forcée, découpage et fusion |
| `src/validation.py` | Contrôles de cohérence, complétude, remarques |
| `src/evaluation.py` | Précision, rappel, hallucinations par champ |
| `src/pipeline.py` | Orchestration, gestion d'erreur par document |
| `src/export.py` | CSV / Excel / SQLite |
| `app.py` / `main.py` | Interface Streamlit / ligne de commande |
| `evaluer.py` | Campagne d'évaluation |

C'est un **pipeline**, pas un agent : l'ordre des étapes est fixé par le code, le
LLM n'intervient qu'à la structuration. Choix délibéré - pour ce cas d'usage, un
enchaînement déterministe est plus fiable, moins cher et surtout testable.

## Installation

```bash
git clone https://github.com/bahyodiawara97-a11y/extraction-documents.git
cd extraction-documents
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Tesseract est un binaire système, à installer séparément :

```bash
brew install tesseract tesseract-lang          # macOS
sudo apt install tesseract-ocr tesseract-ocr-fra   # Debian / Ubuntu
```

Puis la clé API :

```bash
cp .env.example .env    # y renseigner ANTHROPIC_API_KEY
```

## Utilisation

```bash
streamlit run app.py                                  # interface
python main.py data/input --type facture              # lot en ligne de commande
python main.py data/input --type contrat --format csv
pytest tests/ -q                                      # 133 tests, sans clé API
```

Ajouter un type de document tient en deux gestes : définir une classe Pydantic dans
`src/schemas.py` avec une `description` par champ - ces descriptions sont envoyées
au modèle et pilotent directement la qualité de l'extraction - puis l'enregistrer
dans le dictionnaire `SCHEMAS`. L'interface et le CLI le découvrent seuls.

## Ce que le projet a révélé

Quatre défauts rencontrés en conditions réelles. Ils constituent l'essentiel de la
valeur du projet : chacun était silencieux, aucun ne levait d'erreur.

**Les PDF formulaires étaient lus comme des documents vierges.** Un contrat de bail
au format AcroForm stocke les valeurs saisies dans une structure distincte du texte
de page. `pdfplumber.extract_text()` ne lit que la page : sur un bail de 128 champs
dont 40 remplis, il renvoyait 20 000 caractères d'intitulés et zéro valeur, sans le
moindre avertissement. La correction croise deux bibliothèques parce qu'aucune ne
suffit seule - pypdf décode correctement les valeurs mais ignore leur position,
pdfplumber donne la position mais tronque l'UTF-16 - et les apparie par nom de
champ normalisé. Résultat : 0 valeur détectée avant, 40 après.

**Le modèle écrivait la chaîne « null » au lieu de laisser le champ vide.** Une
valeur syntaxiquement valide et sémantiquement vide. Le taux de remplissage la
comptait comme renseignée, et pandas - qui interprète `"null"` comme une valeur
manquante à la lecture - l'affichait comme une case vide. Le calcul disait
« rempli », l'affichage disait « vide », et les deux lisaient la même donnée. La
correction agit à trois niveaux : reformulation du prompt, nettoyage systématique de
dix-huit variantes connues après extraction, et revérification côté validation. Une
consigne dans un prompt est une requête, pas une garantie.

**Un indicateur nommé « score de confiance » mesurait un taux de complétude.** Les
deux coïncidaient tant que les documents avaient la forme attendue. Une quittance de
soins - sans TVA, parce que les actes médicaux n'y sont pas soumis - a révélé la
divergence : extraction parfaite, score de 0,67, document signalé à tort. Le calcul
était honnête, son nom promettait autre chose. Trois notions ont été séparées, chacune
nommée d'après ce qu'elle mesure : `taux_completude` (un fait), `controles_echoues`
(les règles métier violées, seule indication réelle d'erreur) et `remarques`
(inhabituel sans être faux). Le signalement à relecture ne dépend plus d'un seuil de
complétude.

**Une correction a introduit une régression que 119 tests unitaires n'ont pas vue.**
La reconstruction de lignes ajoutée pour les formulaires étendait l'étendue verticale
d'une ligne à chaque mot ajouté. Une lettre de filigrane haute de 54 points suffisait
alors à élargir la ligne jusqu'à absorber toute la page par cascade : le document
entier se retrouvait sur une seule ligne, montants mélangés. Aucune exception, aucun
texte perdu, seulement un ordre de lecture détruit - et des extractions toujours
plausibles. C'est le harnais d'évaluation, écrit une heure plus tôt, qui l'a détecté.
Les PDF sans formulaire reviennent désormais à `pdfplumber`, le centre de référence
d'une ligne n'est plus jamais étendu, et six tests de régression couvrent le cas.

## Choix techniques

**Sortie structurée forcée.** Le schéma Pydantic est déclaré comme un outil et son
appel imposé via `tool_choice`. Le modèle ne peut pas renvoyer autre chose qu'un
objet conforme au JSON Schema - pas de JSON malformé à rattraper au parsing.

**Découpage plutôt que troncature.** Les documents de plus de 20 000 caractères
étaient tronqués, perdant silencieusement leur fin - c'est-à-dire les signatures,
les totaux et les clauses finales. Ils sont découpés aux sauts de ligne avec 1 500
caractères de recouvrement, extraits bloc par bloc, puis fusionnés : première valeur
non vide pour les champs simples, concaténation dédupliquée pour les listes. Un
garde-fou refuse au-delà de douze blocs, pour que le coût devienne visible avant
d'être facturé.

**Bascule automatique natif / OCR.** Un PDF scanné ne contient aucune couche texte.
Le module lit d'abord le texte natif et, en dessous de 100 caractères, bascule sur
l'OCR. Sans ce test, un scan produit une extraction vide sans erreur.

**Contrôles arithmétiques.** HT + TVA doit retomber sur le TTC à deux centimes près,
le TTC ne peut pas être inférieur au HT, une échéance ne précède pas une émission.
Ces règles testent quelque chose de vérifiable, contrairement à un score composite.

**Un échec ne fait pas tomber le lot.** Chaque document est traité isolément : un
PDF corrompu au milieu de cinquante n'en fait pas perdre quarante-neuf.

**Le jeu d'évaluation est généré, pas annoté à la main.** Un même dictionnaire Python
sert à dessiner le document et à produire sa vérité terrain (`evaluation/generer_documents.py`),
si bien que les deux ne peuvent pas diverger. Chaque document a été relu visuellement
avant validation : la génération garantit la cohérence, pas l'absence d'erreur de
conception.

## Limites connues

Le jeu d'évaluation est petit et entièrement synthétique - c'est la limite
principale. Les mises en page réelles, avec leurs colonnes serrées, leurs acomptes
et leurs remises en pied de tableau, restent à éprouver.

L'OCR se trompe sur des chiffres : observé sur une quittance réelle, un « 53 € » lu
« S3€ ». Le pipeline n'a pas de mécanisme de détection pour ce type d'erreur.

Le schéma `Facture` encode des hypothèses métier - l'existence d'une TVA, d'un
numéro - qui ne valent pas pour tous les documents. Les champs HT et TVA ont été
retirés des champs critiques, mais un schéma dédié aux quittances serait plus juste.

Le texte des documents est envoyé à une API externe. Sur des documents
confidentiels, un modèle auto-hébergé ou une anonymisation préalable serait
nécessaire.

## Pistes

Étendre le jeu d'évaluation à des documents réels, en priorité sur la diversité des
mises en page plutôt que sur le volume. Comparer Tesseract à une API d'OCR managée
sur le même jeu, avec précision, latence et coût. Mémoriser les extractions par
empreinte de fichier pour ne pas repayer un appel sur un document déjà traité.
Exposer les étapes comme des outils et confier l'enchaînement à un agent, puis
comparer fiabilité, coût et latence avec ce pipeline déterministe.
