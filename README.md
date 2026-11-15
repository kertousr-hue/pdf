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

### Modifier

| Commande | Exemple |
|---|---|
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
