# pdftool

Programme en Python pour **lire** et **modifier** des fichiers PDF en ligne de commande.

## Installation

```bash
pip install -r requirements.txt
```

## Utilisation

```bash
python pdftool.py --help              # liste des commandes
python pdftool.py COMMANDE --help     # aide d'une commande
```

Les pages se notent à partir de 1 : `--pages 1,3-5`.

### Lire

| Commande | Exemple |
|---|---|
| Informations (pages, titre, auteur…) | `python pdftool.py info doc.pdf` |
| Extraire le texte | `python pdftool.py texte doc.pdf --pages 1-3 -o texte.txt` |
| Identifier les polices | `python pdftool.py polices doc.pdf` |
| Police de chaque morceau de texte | `python pdftool.py polices doc.pdf --detail` |
| Police d'un mot précis | `python pdftool.py polices doc.pdf --chercher "Total"` |

### Modifier

| Commande | Exemple |
|---|---|
| **Remplacer un texte** | `python pdftool.py remplacer doc.pdf sortie.pdf --ancien "Jean Dupont" --nouveau "Marie Martin"` |
| Fusionner | `python pdftool.py fusionner sortie.pdf a.pdf b.pdf` |
| Garder certaines pages | `python pdftool.py extraire doc.pdf sortie.pdf --pages 2,4-6` |
| Supprimer des pages | `python pdftool.py supprimer doc.pdf sortie.pdf --pages 3` |
| Pivoter | `python pdftool.py pivoter doc.pdf sortie.pdf --angle 90 --pages 1` |
| Écrire du texte | `python pdftool.py ajouter-texte doc.pdf sortie.pdf --texte "Bonjour" --x 100 --y 700 --couleur "#cc0000" --pages 1` |
| Filigrane | `python pdftool.py filigrane doc.pdf sortie.pdf --texte "CONFIDENTIEL"` |
| Métadonnées | `python pdftool.py metadonnees doc.pdf sortie.pdf --titre "Titre" --auteur "Moi"` |
| Protéger (AES-256) | `python pdftool.py chiffrer doc.pdf sortie.pdf --mot-de-passe secret` |
| Retirer la protection | `python pdftool.py dechiffrer doc.pdf sortie.pdf --mot-de-passe secret` |

Le fichier source n'est jamais modifié : le résultat est toujours écrit dans un nouveau fichier.

Pour `ajouter-texte`, les coordonnées sont en points (1 pt = 1/72 de pouce), mesurées depuis
le coin **en bas à gauche** de la page. Une page A4 fait 595 × 842 pt.

## Remplacer un texte

`remplacer` efface le texte d'origine (sans toucher aux images ni aux dessins) et écrit le
nouveau texte au même endroit, avec la même taille et la même couleur. Pour la police, le
programme essaie dans cet ordre :

1. le fichier fourni avec `--fichier-police police.ttf` ;
2. la police intégrée dans le PDF, si elle contient tous les caractères nécessaires ;
3. la même police installée sur l'ordinateur (recherche par nom) ;
4. la police standard la plus proche (Helvetica, Times ou Courier, en gras ou en italique).

La commande affiche la police qu'elle a utilisée. La plupart des PDF n'intègrent qu'une
partie de chaque police : si la police d'origine n'est pas installée sur votre ordinateur,
lancez `polices` pour trouver son nom, procurez-vous le fichier, puis passez-le avec
`--fichier-police`.

Options utiles :
- `--ajuster` : réduit la taille si le nouveau texte est plus long que l'ancien ;
- `--taille 12` : force une taille ;
- `--ignorer-casse` : ne distingue pas les majuscules des minuscules ;
- `--pages 1,3` : limite le remplacement à certaines pages.

Limites : le reste de la ligne n'est pas décalé, donc un texte plus long peut chevaucher la
suite et un texte plus court laisse un espace. Le texte d'une image (PDF scanné) ne peut
pas être remplacé.
