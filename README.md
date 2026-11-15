# PDF Éditeur

Programme pour **ouvrir, modifier et enregistrer des PDF**, comme dans Adobe Acrobat, avec
une interface simple pensée pour Windows. Il comprend aussi un outil en ligne de commande.

## Installation sous Windows

1. Installez Python depuis <https://www.python.org/downloads/>.
   Pendant l'installation, cochez **« Add python.exe to PATH »**.
2. Double-cliquez sur **`installer.bat`**. Il installe les modules nécessaires et crée un
   raccourci **PDF Éditeur** sur le Bureau.
3. Lancez **PDF Éditeur** depuis le Bureau, ou double-cliquez sur `PDF Editeur.pyw`.

Pour obtenir un vrai programme `.exe` qui fonctionne sans Python (à copier sur un autre PC,
ou à choisir dans « Ouvrir avec » pour vos PDF), double-cliquez sur **`creer_exe.bat`**.
Le fichier créé est `dist\PDF Editeur.exe`.

Sous macOS ou Linux : `pip install -r requirements.txt`, puis `python pdf_editeur.py`
(sous Linux, il faut aussi installer `python3-tk`).

## Ce que fait l'éditeur

| | |
|---|---|
| **Ouvrir** | Bouton *Ouvrir* (Ctrl+O), **glisser-déposer** un PDF dans la fenêtre, ou un fichier récent depuis l'accueil. Les PDF protégés par mot de passe sont pris en charge. |
| **Enregistrer** | *Enregistrer* (Ctrl+S), *Enregistrer sous* (Ctrl+Maj+S) ou *Enregistrer avec mot de passe*. Rien n'est écrit sur le disque tant que vous n'enregistrez pas. |
| **Modifier le texte** | Outil *Modifier* (Ctrl+E) : chaque texte est encadré. Cliquez dessus, tapez, puis Entrée. Le texte garde sa police, sa taille et sa couleur, et la suite de la ligne se décale. Vous pouvez aussi double-cliquer sur un texte. |
| **Mise en forme** | Police (toutes les polices installées), taille, **gras**, *italique*, couleur. |
| **Ajouter du texte** | Outil *Texte* (Ctrl+T) : cliquez sur la page, puis écrivez. |
| **Image / Signer** | Choisissez une image, ou dessinez votre signature à la souris, puis tracez un rectangle sur la page. |
| **Surligner / Note** | Surlignez du texte ou ajoutez un commentaire. |
| **Rechercher et remplacer** | Ctrl+F : les résultats sont encadrés, et « Remplacer tout » garde la mise en forme. |
| **Pages** | Miniatures à gauche : glissez une miniature pour déplacer la page. Le clic droit permet de pivoter, supprimer, insérer une page blanche ou un PDF. |
| **Autres** | Fusionner, exporter des pages, des images PNG ou le texte, filigrane, numéros de page, propriétés, effacer définitivement une zone, imprimer. |
| **Annuler / Rétablir** | Ctrl+Z / Ctrl+Y, autant de fois que nécessaire. |

## Documents scannés

Un PDF scanné ne contient qu'une **image** de la page. À l'ouverture, un bandeau jaune
propose **« Reconnaître le texte (OCR) »** :

1. le texte de l'image est lu (français, anglais, allemand, espagnol… au choix) ; la première
   fois, les fichiers de langue sont téléchargés (quelques Mo, une seule fois) ;
2. le texte reconnu est ajouté **de façon invisible** sur l'image : le document devient
   sélectionnable, cherchable et copiable, sans perte de qualité ;
3. avec l'outil **Modifier**, cliquez sur une ligne et tapez : l'ancien texte est recouvert
   de la couleur du papier, et le nouveau est écrit **dans la couleur de l'encre et dans la
   police la plus ressemblante**. Le programme compare l'image du texte avec chaque police
   installée pour identifier la bonne (Arial, Times, Calibri, Courier…) et sa taille ;
4. **Rechercher et remplacer** fonctionne aussi : la suite de la ligne (l'image) est décalée.

La police estimée s'affiche dans la barre de mise en forme ; vous pouvez la changer avant
de valider. Les PDF déjà « cherchables » produits par un scanner sont reconnus directement.

Conseils pour un bon résultat : scannez à **300 dpi**, bien droit, en couleur ou en niveaux de gris.

## Les polices

Pour qu'un texte modifié garde son apparence, le programme doit disposer de la police
d'origine. Il la cherche dans cet ordre :

1. **la police intégrée au PDF**, si elle contient toutes les lettres nécessaires ;
2. **toutes les polices installées sur l'ordinateur** (Windows, utilisateur, et les polices
   ajoutées au programme), reconnues par leur nom interne (par exemple `Arial-BoldMT` → `arialbd.ttf`) ;
3. **Google Fonts** : si la police manque, elle est téléchargée gratuitement (plus de
   1 500 familles : Roboto, Open Sans, Montserrat, Lato…) ;
4. une police **équivalente** aux mêmes dimensions (par exemple Arimo pour Arial,
   Carlito pour Calibri) ;
5. en dernier recours, la police standard la plus proche.

**Outils › Polices du document** indique quelles polices du PDF sont installées et propose
**« Installer les polices manquantes »** : téléchargement depuis Google Fonts, ou extraction
quand la police est intégrée complète dans le PDF. Si l'option est cochée dans
**Outils › Gérer les polices**, elles sont aussi installées dans Windows, donc utilisables
dans Word, etc. (sans droits administrateur).

Pour une police payante qui n'est ni sur l'ordinateur ni sur Google Fonts (Helvetica Neue,
Futura…), ajoutez son fichier `.ttf` ou `.otf` avec *Ajouter un fichier de police*.

## Ligne de commande

```bash
python pdftool.py --help
```

| Commande | Exemple |
|---|---|
| Informations | `python pdftool.py info doc.pdf` |
| Texte | `python pdftool.py texte doc.pdf --pages 1-3 -o texte.txt` |
| Polices | `python pdftool.py polices doc.pdf --detail` |
| Remplacer un texte | `python pdftool.py remplacer doc.pdf sortie.pdf --ancien "Jean" --nouveau "Marie"` |
| Fusionner | `python pdftool.py fusionner sortie.pdf a.pdf b.pdf` |
| Extraire / supprimer des pages | `python pdftool.py extraire doc.pdf sortie.pdf --pages 2,4-6` |
| Pivoter | `python pdftool.py pivoter doc.pdf sortie.pdf --angle 90 --pages 1` |
| Ajouter du texte | `python pdftool.py ajouter-texte doc.pdf sortie.pdf --texte "Bonjour" --x 100 --y 700` |
| Filigrane | `python pdftool.py filigrane doc.pdf sortie.pdf --texte "CONFIDENTIEL"` |
| Métadonnées | `python pdftool.py metadonnees doc.pdf sortie.pdf --titre "Titre"` |
| Mot de passe | `python pdftool.py chiffrer doc.pdf sortie.pdf --mot-de-passe secret` |
| OCR d'un scan | `python pdftool.py ocr scan.pdf sortie.pdf --langues fra+eng` |

Options de `remplacer` : `--ajuster` (réduit la taille si le texte est plus long),
`--sans-decaler`, `--fichier-police police.ttf`, `--hors-ligne` (pas de téléchargement),
`--ignorer-casse`, `--pages`.

## Limites

- Le texte est modifié **ligne par ligne** : il ne passe pas automatiquement à la ligne
  suivante comme dans un traitement de texte.
- Sur un document scanné, la police est estimée : elle peut différer légèrement de
  l'originale, surtout pour une écriture manuscrite ou une police rare. Un scan de mauvaise
  qualité (flou, penché, basse résolution) donne une reconnaissance moins fiable.
- Le décalage de la suite de la ligne n'est fait que si sa police d'origine est disponible.
